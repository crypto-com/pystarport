import base64
import configparser
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from enum import Enum
from pathlib import Path
from typing import List

import durations
import jsonmerge
import multitail2
import tomlkit
import yaml
from dateutil.parser import isoparse
from supervisor import xmlrpc
from supervisor.compat import xmlrpclib

from . import ports
from .app import CHAIN, IMAGE, SUPERVISOR_CONFIG_FILE
from .cosmoscli import ChainCommand, CosmosCLI, ModuleAccount, module_address
from .expansion import expand_jsonnet, expand_yaml
from .ledger import ZEMU_BUTTON_PORT, ZEMU_HOST
from .utils import format_doc_string, get_sync_info, interact, write_ini

COMMON_PROG_OPTIONS = {
    # redirect to supervisord's stdout, easier to collect all logs
    "autostart": "true",
    "autorestart": "true",
    "redirect_stderr": "true",
    "startsecs": "3",
}


def home_dir(data_dir, i):
    return data_dir / f"node{i}"


class ClusterCLI:
    "the apis to interact with wallet and blockchain prepared with Cluster"

    def __init__(
        self,
        data,
        chain_id="chainmaind",
        cmd=None,
        zemu_address=ZEMU_HOST,
        zemu_button_port=ZEMU_BUTTON_PORT,
    ):
        self.data_root = data
        self.zemu_address = zemu_address
        self.zemu_button_port = zemu_button_port
        self.chain_id = chain_id
        self.data_dir = data / self.chain_id
        self.config = json.load((self.data_dir / "config.json").open())
        self.cmd = cmd or self.config.get("cmd") or CHAIN

        self._supervisorctl = None
        self.output = None
        self.error = None

    def cosmos_cli(self, i=0):
        return CosmosCLI(
            self.home(i),
            self.node_rpc(i),
            chain_id=self.chain_id,
            cmd=self.cmd,
            zemu_address=self.zemu_address,
            zemu_button_port=self.zemu_button_port,
        )

    @property
    def supervisor(self):
        "http://supervisord.org/api.html"
        # copy from:
        # https://github.com/Supervisor/supervisor/blob/76df237032f7d9fbe80a0adce3829c8b916d5b58/supervisor/options.py#L1718
        if self._supervisorctl is None:
            self._supervisorctl = xmlrpclib.ServerProxy(
                # dumbass ServerProxy won't allow us to pass in a non-HTTP url,
                # so we fake the url we pass into it and
                # always use the transport's
                # 'serverurl' to figure out what to attach to
                "http://127.0.0.1",
                transport=xmlrpc.SupervisorTransport(
                    serverurl=f"unix://{self.data_root}/supervisor.sock"
                ),
            )
        return self._supervisorctl.supervisor

    def reload_supervisor(self):
        subprocess.run(
            [
                sys.executable,
                "-msupervisor.supervisorctl",
                "-c",
                self.data_root / SUPERVISOR_CONFIG_FILE,
                "update",
            ],
            check=True,
        )

    def nodes_len(self):
        "find how many 'node{i}' sub-directories"
        return len(
            [p for p in self.data_dir.iterdir() if re.match(r"^node\d+$", p.name)]
        )

    def copy_validator_key(self, from_node=1, to_node=2):
        "Copy the validtor file in from_node to to_node"
        from_key_file = "{}/node{}/config/priv_validator_key.json".format(
            self.data_dir, from_node
        )
        to_key_file = "{}/node{}/config/priv_validator_key.json".format(
            self.data_dir, to_node
        )
        with open(from_key_file, "r") as f:
            key = f.read()
        with open(to_key_file, "w") as f:
            f.write(key)

    def update_genesis(self, i, genesis_data):
        home = self.home(i)
        genesis_file = home / "config/genesis.json"
        with open(genesis_file, "w") as f:
            f.write(json.dumps(genesis_data, indent=4))

    def stop_node(self, i=0):
        subprocess.run(
            [
                sys.executable,
                "-msupervisor.supervisorctl",
                "-c",
                self.data_root / SUPERVISOR_CONFIG_FILE,
                "stop",
                "{}-node{}".format(self.chain_id, i),
            ]
        )

    def stop_relayer(self):
        subprocess.run(
            [
                sys.executable,
                "-msupervisor.supervisorctl",
                "-c",
                self.data_root / SUPERVISOR_CONFIG_FILE,
                "stop",
                "program:relayer-demo",
            ]
        )

    def restart_relayer(self):
        subprocess.run(
            [
                sys.executable,
                "-msupervisor.supervisorctl",
                "-c",
                self.data_root / SUPERVISOR_CONFIG_FILE,
                "restart",
                "program:relayer-demo",
            ]
        )

    def start_node(self, i):
        subprocess.run(
            [
                sys.executable,
                "-msupervisor.supervisorctl",
                "-c",
                self.data_root / SUPERVISOR_CONFIG_FILE,
                "start",
                "{}-node{}".format(self.chain_id, i),
            ]
        )

    def create_node(
        self,
        base_port=None,
        moniker=None,
        hostname="127.0.0.1",
        statesync=False,
        mnemonic=None,
        broadcastmode="sync",
    ):
        """create new node in the data directory,
        process information is written into supervisor config
        start it manually with supervisor commands

        :return: new node index and config
        """
        i = self.nodes_len()

        # default configs
        if base_port is None:
            # use the node0's base_port + i * 10 as default base port for new ndoe
            base_port = self.config["validators"][0]["base_port"] + i * 10
        if moniker is None:
            moniker = f"node{i}"

        # add config
        assert len(self.config["validators"]) == i
        self.config["validators"].append(
            {
                "base_port": base_port,
                "hostname": hostname,
                "moniker": moniker,
            }
        )
        (self.data_dir / "config.json").write_text(json.dumps(self.config))

        # init home directory
        self.init(i)
        home = self.home(i)
        (home / "config/genesis.json").unlink()
        (home / "config/genesis.json").symlink_to("../../genesis.json")
        (home / "config/client.toml").write_text(
            tomlkit.dumps(
                {
                    "chain-id": self.chain_id,
                    "keyring-backend": "test",
                    "output": "json",
                    "node": self.node_rpc(i),
                    "broadcast-mode": broadcastmode,
                }
            )
        )

        # use p2p peers from node0's config
        node0 = tomlkit.parse((self.data_dir / "node0/config/config.toml").read_text())

        def custom_edit_tm(doc):
            if statesync:
                info = get_sync_info(self.status())
                doc["statesync"].update(
                    {
                        "enable": True,
                        "rpc_servers": ",".join(self.node_rpc(i) for i in range(2)),
                        "trust_height": int(info["latest_block_height"]),
                        "trust_hash": info["latest_block_hash"],
                        "temp_dir": str(self.data_dir),
                        "discovery_time": "5s",
                    }
                )

        edit_tm_cfg(
            home / "config/config.toml",
            base_port,
            node0["p2p"]["persistent_peers"],
            {},
            custom_edit=custom_edit_tm,
        )
        edit_app_cfg(home / "config/app.toml", base_port, {})

        # create validator account
        self.create_account("validator", i, mnemonic)

        # add process config into supervisor
        path = self.data_dir / SUPERVISOR_CONFIG_FILE
        ini = configparser.RawConfigParser()
        ini.read(path)
        chain_id = self.chain_id
        prgname = f"{chain_id}-node{i}"
        section = f"program:{prgname}"
        ini.add_section(section)
        directory = f"%(here)s/node{i}"
        ini[section].update(
            dict(
                COMMON_PROG_OPTIONS,
                directory=directory,
                command=f"{self.cmd} start --home .",
                autostart="false",
                stdout_logfile=f"{directory}.log",
            )
        )
        with path.open("w") as fp:
            ini.write(fp)
        self.reload_supervisor()
        return i

    def home(self, i):
        "home directory of i-th node"
        return home_dir(self.data_dir, i)

    def base_port(self, i):
        return self.config["validators"][i]["base_port"]

    def node_rpc(self, i):
        "rpc url of i-th node"
        return "tcp://127.0.0.1:%d" % ports.rpc_port(self.base_port(i))

    # for query
    def ipport_grpc(self, i):
        "grpc url of i-th node"
        return "127.0.0.1:%d" % ports.grpc_port(self.base_port(i))

    # tx broadcast only
    def ipport_grpc_tx(self, i):
        "grpc url of i-th node"
        return "127.0.0.1:%d" % ports.grpc_port_tx_only(self.base_port(i))

    def node_id(self, i):
        "get i-th node's tendermint node id"
        return self.cosmos_cli(i).node_id()

    def delete_account(self, name, i=0):
        "delete account in i-th node's keyring"
        return self.cosmos_cli(i).delete_account(name)

    def create_account(self, name, i=0, mnemonic=None):
        "create new keypair in i-th node's keyring"
        return self.cosmos_cli(i).create_account(name, mnemonic)

    def create_account_ledger(self, name, i=0):
        "create new ledger keypair"
        return self.cosmos_cli(i).create_account_ledger(name)

    def init(self, i):
        "the i-th node's config is already added"
        return self.cosmos_cli(i).init(self.config["validators"][i]["moniker"])

    def export(self, i=0):
        return self.cosmos_cli(i).export()

    def validate_genesis(self, *args, i=0):
        return self.cosmos_cli(i).validate_genesis(*args)

    def add_genesis_account(self, addr, coins, i=0, **kwargs):
        return self.cosmos_cli(i).add_genesis_account(addr, coins, **kwargs)

    def gentx(
        self, name, coins, *args, i=0, min_self_delegation=1, pubkey=None, **kwargs
    ):
        return self.cosmos_cli(i).gentx(
            name,
            coins,
            *args,
            min_self_delegation=min_self_delegation,
            pubkey=pubkey,
            **kwargs,
        )

    def collect_gentxs(self, gentx_dir, i=0):
        return self.cosmos_cli(i).collect_gentxs(gentx_dir)

    def status(self, i=0):
        return self.cosmos_cli(i).status()

    def block_height(self, i=0):
        return self.cosmos_cli(i).block_height()

    def block_time(self, i=0):
        return self.cosmos_cli(i).block_time()

    def balances(self, addr, height=0, i=0):
        return self.cosmos_cli(i).balances(addr, height)

    def balance(self, addr, denom=None, height=0, i=0):
        return self.cosmos_cli(i).balance(addr, denom, height)

    def query_all_txs(self, addr, i=0):
        return self.cosmos_cli(i).query_all_txs(addr)

    def distribution_commission(self, addr, i=0):
        return self.cosmos_cli(i).distribution_commission(addr)

    def distribution_community(self, i=0):
        return self.cosmos_cli(i).distribution_community()

    def distribution_reward(self, delegator_addr, i=0):
        return self.cosmos_cli(i).distribution_reward(delegator_addr)

    def address(self, name, i=0, bech="acc"):
        return self.cosmos_cli(i).address(name, bech)

    @format_doc_string(
        options=",".join(v.value for v in ModuleAccount.__members__.values())
    )
    def module_address(self, name):
        """
        get address of module accounts

        :param name: name of module account, values: {options}
        """
        return module_address(name)

    def account(self, addr, i=0):
        return self.cosmos_cli(i).account(addr)

    def supply(self, supply_type, i=0):
        return self.cosmos_cli(i).supply(supply_type)

    def validator(self, addr, i=0):
        return self.cosmos_cli(i).validator(addr)

    def validators(self, i=0):
        return self.cosmos_cli(i).validators()

    def staking_params(self, i=0):
        return self.cosmos_cli(i).staking_params()

    def staking_pool(self, bonded=True, i=0):
        return self.cosmos_cli(i).staking_pool(bonded)

    def transfer_offline(self, from_, to, coins, sequence, i=0, fees=None):
        return self.cosmos_cli(i).transfer_offline(from_, to, coins, sequence, fees)

    def transfer(
        self,
        from_,
        to,
        coins,
        i=0,
        generate_only=False,
        event_query_tx=True,
        **kwargs,
    ):
        return self.cosmos_cli(i).transfer(
            from_,
            to,
            coins,
            generate_only,
            event_query_tx=event_query_tx,
            **kwargs,
        )

    def transfer_from_ledger(
        self,
        from_,
        to,
        coins,
        i=0,
        generate_only=False,
        fees=None,
        event_query_tx=True,
        **kwargs,
    ):
        return self.cosmos_cli(i).transfer_from_ledger(
            from_,
            to,
            coins,
            generate_only,
            fees,
            event_query_tx=event_query_tx,
            **kwargs,
        )

    def get_delegated_amount(self, which_addr, i=0):
        return self.cosmos_cli(i).get_delegated_amount(which_addr)

    def delegate_amount(
        self,
        to_addr,
        amount,
        from_addr,
        i=0,
        gas_price=None,
        event_query_tx=True,
        **kwargs,
    ):
        return self.cosmos_cli(i).delegate_amount(
            to_addr,
            amount,
            from_addr,
            gas_price,
            event_query_tx=event_query_tx,
            **kwargs,
        )

    # to_addr: croclcl1...  , from_addr: cro1...
    def unbond_amount(
        self, to_addr, amount, from_addr, i=0, event_query_tx=True, **kwargs
    ):
        return self.cosmos_cli(i).unbond_amount(
            to_addr,
            amount,
            from_addr,
            event_query_tx=event_query_tx,
            **kwargs,
        )

    # to_validator_addr: crocncl1...  ,  from_from_validator_addraddr: crocl1...
    def redelegate_amount(
        self,
        to_validator_addr,
        from_validator_addr,
        amount,
        from_addr,
        i=0,
        event_query_tx=True,
        **kwargs,
    ):
        return self.cosmos_cli(i).redelegate_amount(
            to_validator_addr,
            from_validator_addr,
            amount,
            from_addr,
            event_query_tx=event_query_tx,
            **kwargs,
        )

    def withdraw_all_rewards(self, from_delegator, i=0, event_query_tx=True, **kwargs):
        return self.cosmos_cli(i).withdraw_all_rewards(
            from_delegator,
            event_query_tx=event_query_tx,
            **kwargs,
        )

    def make_multisig(self, name, signer1, signer2, i=0):
        return self.cosmos_cli(i).make_multisig(name, signer1, signer2)

    def sign_multisig_tx(self, tx_file, multi_addr, signer_name, i=0, **kwargs):
        return self.cosmos_cli(i).sign_multisig_tx(
            tx_file, multi_addr, signer_name, **kwargs
        )

    def sign_batch_multisig_tx(
        self, tx_file, multi_addr, signer_name, account_num, sequence, i=0, **kwargs
    ):
        return self.cosmos_cli(i).sign_batch_multisig_tx(
            tx_file, multi_addr, signer_name, account_num, sequence, **kwargs
        )

    def encode_signed_tx(self, signed_tx, i=0, **kwargs):
        return self.cosmos_cli(i).encode_signed_tx(signed_tx, **kwargs)

    def sign_single_tx(self, tx_file, signer_name, i=0, **kwargs):
        return self.cosmos_cli(i).sign_single_tx(tx_file, signer_name, **kwargs)

    def combine_multisig_tx(
        self, tx_file, multi_name, signer1_file, signer2_file, i=0, **kwargs
    ):
        return self.cosmos_cli(i).combine_multisig_tx(
            tx_file,
            multi_name,
            signer1_file,
            signer2_file,
            **kwargs,
        )

    def combine_batch_multisig_tx(
        self, tx_file, multi_name, signer1_file, signer2_file, i=0, **kwargs
    ):
        return self.cosmos_cli(i).combine_batch_multisig_tx(
            tx_file,
            multi_name,
            signer1_file,
            signer2_file,
            **kwargs,
        )

    def broadcast_tx(self, tx_file, i=0, **kwargs):
        return self.cosmos_cli(i).broadcast_tx(tx_file, **kwargs)

    def unjail(self, addr, i=0, event_query_tx=True, **kwargs):
        return self.cosmos_cli(i).unjail(addr, event_query_tx=event_query_tx, **kwargs)

    def create_validator(
        self,
        amount,
        options,
        i,
        **kwargs,
    ):
        """MsgCreateValidator
        create the node with create_node before call this"""
        options.setdefault("moniker", self.config["validators"][i]["moniker"])
        return self.cosmos_cli(i).create_validator(amount, options, **kwargs)

    def create_validator_legacy(
        self,
        amount,
        i,
        **kwargs,
    ):
        """MsgCreateValidator
        create the node with create_node before call this"""
        kwargs.setdefault("moniker", self.config["validators"][i]["moniker"])
        return self.cosmos_cli(i).create_validator_legacy(amount, **kwargs)

    def edit_validator(
        self,
        i,
        commission_rate=None,
        moniker=None,
        identity=None,
        website=None,
        security_contact=None,
        details=None,
        event_query_tx=True,
        **kwargs,
    ):
        """MsgEditValidator"""
        return self.cosmos_cli(i).edit_validator(
            commission_rate,
            moniker,
            identity,
            website,
            security_contact,
            details,
            event_query_tx=event_query_tx,
            **kwargs,
        )

    def gov_propose(self, proposer, kind, proposal, i=0, **kwargs):
        return self.cosmos_cli(i).gov_propose(proposer, kind, proposal, **kwargs)

    def gov_vote(self, voter, proposal_id, option, i=0, event_query_tx=True, **kwargs):
        return self.cosmos_cli(i).gov_vote(
            voter,
            proposal_id,
            option,
            event_query_tx=event_query_tx,
            **kwargs,
        )

    def gov_deposit(
        self, depositor, proposal_id, amount, i=0, event_query_tx=True, **kwargs
    ):
        return self.cosmos_cli(i).gov_deposit(
            depositor,
            proposal_id,
            amount,
            event_query_tx=event_query_tx,
            **kwargs,
        )

    def query_proposals(self, depositor=None, limit=None, status=None, voter=None, i=0):
        return self.cosmos_cli(i).query_proposals(depositor, limit, status, voter)

    def query_proposal(self, proposal_id, i=0):
        res = self.cosmos_cli(i).query_proposal(proposal_id)
        return res.get("proposal") or res

    def query_tally(self, proposal_id, i=0):
        return self.cosmos_cli(i).query_tally(proposal_id)

    def ibc_transfer(
        self,
        from_,
        to,
        amount,
        channel,  # src channel
        target_version,  # chain version number of target chain
        i=0,
        event_query_tx=True,
        **kwargs,
    ):
        return self.cosmos_cli(i).ibc_transfer(
            from_,
            to,
            amount,
            channel,
            target_version,
            event_query_tx=event_query_tx,
            **kwargs,
        )

    def create_nft(
        self,
        from_addr,
        denomid="mydenomid",
        denomname="mydenomname",
        schema='{"title":"Asset Metadata","type":"object",'
        '"properties":{"name":{"type":"string",'
        '"description":"testidentity"},"description":'
        '{"type":"string","description":"testdescription"},'
        '"image":{"type":"string","description":"testdescription"}}}',
        fees=None,
        i=0,
        event_query_tx=True,
        **kwargs,
    ):
        return self.cosmos_cli(i).create_nft(
            from_addr,
            denomid,
            denomname,
            schema,
            fees,
            event_query_tx=event_query_tx,
            **kwargs,
        )

    def query_nft(self, denomid="mydenomid", i=0):
        return self.cosmos_cli(i).query_nft(denomid)

    def query_denom_by_name(self, denomname="mydenomname", i=0):
        return self.cosmos_cli(i).query_denom_by_name(denomname)

    def create_nft_token(
        self,
        from_addr,
        to_addr,
        denomid="mydenomid",
        tokenid="mytokenid",
        uri="myuri",
        fees=None,
        i=0,
        event_query_tx=True,
        **kwargs,
    ):
        return self.cosmos_cli(i).create_nft_token(
            from_addr,
            to_addr,
            denomid,
            tokenid,
            uri,
            fees,
            event_query_tx=event_query_tx,
            **kwargs,
        )

    def query_nft_token(self, denomid="mydenomid", tokenid="mytokenid", i=0):
        return self.cosmos_cli(i).query_nft_token(denomid, tokenid)

    def burn_nft_token(
        self,
        from_addr,
        denomid="mydenomid",
        tokenid="mytokenid",
        i=0,
        event_query_tx=True,
        **kwargs,
    ):
        return self.cosmos_cli(i).burn_nft_token(
            from_addr,
            denomid,
            tokenid,
            event_query_tx=event_query_tx,
            **kwargs,
        )

    def edit_nft_token(
        self,
        from_addr,
        denomid="mydenomid",
        tokenid="mytokenid",
        newuri="newuri",
        newname="newname",
        i=0,
        event_query_tx=True,
        **kwargs,
    ):
        return self.cosmos_cli(i).edit_nft_token(
            from_addr,
            denomid,
            tokenid,
            newuri,
            newname,
            event_query_tx=event_query_tx,
            **kwargs,
        )

    def transfer_nft_token(
        self,
        from_addr,
        to_addr,
        denomid="mydenomid",
        tokenid="mytokenid",
        i=0,
        event_query_tx=True,
        **kwargs,
    ):
        return self.cosmos_cli(i).transfer_nft_token(
            from_addr,
            to_addr,
            denomid,
            tokenid,
            event_query_tx=event_query_tx,
            **kwargs,
        )

    def event_query_tx_for(self, hash, i=0):
        return self.cosmos_cli(i).event_query_tx_for(hash)

    def migrate_keystore(self, i=0):
        return self.cosmos_cli(i).migrate_keystore()

    def ibc_query_channels(self, connid, i=0, **kwargs):
        return self.cosmos_cli(i).ibc_query_channels(connid, **kwargs)

    def ica_register_account(self, connid, i=0, event_query_tx=True, **kwargs):
        return self.cosmos_cli(i).ica_register_account(
            connid,
            event_query_tx=event_query_tx,
            **kwargs,
        )

    def ica_query_account(self, connid, owner, i=0, **kwargs):
        return self.cosmos_cli(i).ica_query_account(connid, owner, **kwargs)

    def ica_submit_tx(
        self,
        connid,
        tx,
        timeout_duration="1h",
        i=0,
        event_query_tx=True,
        **kwargs,
    ):
        return self.cosmos_cli(i).ica_submit_tx(
            connid,
            tx,
            timeout_duration,
            event_query_tx=event_query_tx,
            **kwargs,
        )

    def ica_generate_packet_data(self, tx, memo=None, encoding="proto3", i=0, **kwargs):
        return self.cosmos_cli(i).ica_generate_packet_data(memo, encoding, **kwargs)


def start_cluster(data_dir):
    cmd = [
        sys.executable,
        "-msupervisor.supervisord",
        "-c",
        data_dir / SUPERVISOR_CONFIG_FILE,
    ]
    return subprocess.Popen(cmd, env=dict(os.environ, PYTHONPATH=":".join(sys.path)))


class TailLogsThread(threading.Thread):
    def __init__(self, base_dir, pats: List[str]):
        self.base_dir = base_dir
        self.tailer = multitail2.MultiTail([str(base_dir / pat) for pat in pats])
        self._stop_event = threading.Event()
        super().__init__()

    def run(self):
        while not self.stopped:
            for (path, _), s in self.tailer.poll():
                print(Path(path).relative_to(self.base_dir), s)

            # TODO Replace this with FAM/inotify for watching filesystem events.
            time.sleep(0.5)

    def stop(self):
        self._stop_event.set()

    @property
    def stopped(self):
        return self._stop_event.is_set()


def start_tail_logs_thread(data_dir):
    t = TailLogsThread(data_dir, ["*/node*.log", "relayer-*.log"])
    t.start()
    return t


def process_config(config, base_port):
    """
    fill default values in config
    """
    for i, val in enumerate(config["validators"]):
        if "moniker" not in val:
            val["moniker"] = f"node{i}"
        if "base_port" not in val:
            val["base_port"] = base_port + i * 10
        if "hostname" not in val:
            val["hostname"] = "127.0.0.1"


def init_devnet(
    data_dir,
    config,
    base_port,
    image=IMAGE,
    cmd=None,
    gen_compose_file=False,
):
    """
    init data directory
    """

    def create_account(cli, account, use_ledger=False):
        if use_ledger:
            acct = cli.create_account_ledger(account["name"])
        elif account.get("address"):
            # if address field exists, will use account with that address directly
            acct = {"name": account.get("name"), "address": account.get("address")}
        else:
            mnemonic = account.get("mnemonic")
            acct = cli.create_account(account["name"], mnemonic=mnemonic)
            if mnemonic:
                acct["mnemonic"] = mnemonic
        vesting = account.get("vesting")
        if not vesting:
            cli.add_genesis_account(acct["address"], account["coins"])
        else:
            genesis_time = isoparse(genesis["genesis_time"])
            end_time = genesis_time + datetime.timedelta(
                seconds=durations.Duration(vesting).to_seconds()
            )
            vend = int(end_time.timestamp())
            # allow vest only some of coins allocated, where account["coins"] must larger than account["vesting_coins"] if any vesting_coins specified in config.yaml. # noqa 501
            vesting_amount = account.get("vesting_coins", account["coins"])
            cli.add_genesis_account(
                acct["address"],
                account["coins"],
                vesting_amount=vesting_amount,
                vesting_end_time=vend,
            )
        return acct

    process_config(config, base_port)

    (data_dir / "config.json").write_text(json.dumps(config))

    cmd = cmd or config.get("cmd") or CHAIN

    # init home directories
    for i, val in enumerate(config["validators"]):
        ChainCommand(cmd)(
            "init",
            val["moniker"],
            config.get("cmd-flags"),
            chain_id=config["chain_id"],
            home=home_dir(data_dir, i),
        )
        if "consensus_key" in val:
            # restore consensus private key
            with (home_dir(data_dir, i) / "config/priv_validator_key.json").open(
                "w"
            ) as fp:
                json.dump(
                    {
                        "address": hashlib.sha256(
                            base64.b64decode(val["consensus_key"]["pub"])
                        )
                        .hexdigest()[:40]
                        .upper(),
                        "pub_key": {
                            "type": "tendermint/PubKeyEd25519",
                            "value": val["consensus_key"]["pub"],
                        },
                        "priv_key": {
                            "type": "tendermint/PrivKeyEd25519",
                            "value": val["consensus_key"]["priv"],
                        },
                    },
                    fp,
                )
    if "genesis_file" in config:
        with open(
            config["genesis_file"] % {"here": Path(config["path"]).parent}, "rb"
        ) as f:
            genesis_bytes = f.read()
    else:
        genesis_bytes = (data_dir / "node0/config/genesis.json").read_bytes()
    (data_dir / "genesis.json").write_bytes(genesis_bytes)
    (data_dir / "gentx").mkdir()
    for i, val in enumerate(config["validators"]):
        src = data_dir / f"node{i}/config/genesis.json"
        src.unlink()
        src.symlink_to("../../genesis.json")
        (data_dir / f"node{i}/config/gentx").symlink_to("../../gentx")

        # write client config
        rpc_port = ports.rpc_port(val["base_port"])
        (data_dir / f"node{i}/config/client.toml").write_text(
            tomlkit.dumps(
                jsonmerge.merge(
                    {
                        "chain-id": config["chain_id"],
                        "keyring-backend": "test",
                        "output": "json",
                        "node": f"tcp://{val['hostname']}:{rpc_port}",
                        "broadcast-mode": "sync",
                    },
                    val.get("client_config", {}),
                )
            )
        )

    # now we can create ClusterCLI
    cli = ClusterCLI(data_dir.parent, chain_id=config["chain_id"], cmd=cmd)

    # patch the genesis file
    genesis = jsonmerge.merge(
        json.loads((data_dir / "genesis.json").read_text()),
        config.get("genesis", {}),
    )
    (data_dir / "genesis.json").write_text(json.dumps(genesis))

    # create accounts
    accounts = []
    for i, node in enumerate(config["validators"]):
        mnemonic = node.get("mnemonic")
        account = cli.create_account("validator", i, mnemonic=mnemonic)
        if mnemonic:
            account["mnemonic"] = mnemonic
        accounts.append(account)
        if "coins" in node:
            cli.add_genesis_account(account["address"], node["coins"], i)
        if "staked" in node:
            optional_fields = [
                "commission_max_change_rate",
                "commission_max_rate",
                "commission_rate",
                "details",
                "security_contact",
                "gas_prices",
            ]
            extra_kwargs = {
                name: str(node[name]) for name in optional_fields if name in node
            }
            cli.gentx(
                "validator",
                node["staked"],
                config.get("cmd-flags"),
                i=i,
                min_self_delegation=node.get("min_self_delegation", 1),
                pubkey=node.get("pubkey"),
                **extra_kwargs,
            )

    # create accounts
    for account in config.get("accounts", []):
        account = create_account(cli, account)
        accounts.append(account)

    account_hw = config.get("hw_account")
    if account_hw:
        account = create_account(cli, account_hw, True)
        accounts.append(account)

    # output accounts
    (data_dir / "accounts.json").write_text(json.dumps(accounts))

    # collect-gentxs if directory not empty
    if next((data_dir / "gentx").iterdir(), None) is not None:
        cli.collect_gentxs(data_dir / "gentx", 0)

    # realise the symbolic links, so the node directories can be used independently
    genesis_bytes = (data_dir / "genesis.json").read_bytes()
    for i in range(len(config["validators"])):
        (data_dir / f"node{i}/config/gentx").unlink()
        tmp = data_dir / f"node{i}/config/genesis.json"
        tmp.unlink()
        tmp.write_bytes(genesis_bytes)

    # write tendermint config
    peers = config.get("peers") or ",".join(
        [
            "tcp://%s@%s:%d"
            % (cli.node_id(i), val["hostname"], ports.p2p_port(val["base_port"]))
            for i, val in enumerate(config["validators"])
        ]
    )
    for i, val in enumerate(config["validators"]):
        self_peer = "tcp://%s@%s:%d" % (
            cli.node_id(i),
            val["hostname"],
            ports.p2p_port(val["base_port"]),
        )
        clean_peers = try_remove_peer(peers, self_peer)
        edit_tm_cfg(
            data_dir / f"node{i}/config/config.toml",
            val["base_port"],
            clean_peers,
            jsonmerge.merge(config.get("config", {}), val.get("config", {})),
        )
        edit_app_cfg(
            data_dir / f"node{i}/config/app.toml",
            val["base_port"],
            jsonmerge.merge(config.get("app-config", {}), val.get("app-config", {})),
        )

    # if the first validator is using statesync mode, then don't validate genesis,
    # because the new binary may be a breaking one.
    doc = tomlkit.parse((data_dir / "node0/config/config.toml").read_text())
    if not doc["statesync"]["enable"]:
        cli.validate_genesis(config.get("cmd-flags", {}))

    # write supervisord config file
    start_flags = " ".join(
        [config.get("start-flags", ""), config.get("cmd-flags", "")]
    ).strip()
    with (data_dir / SUPERVISOR_CONFIG_FILE).open("w") as fp:
        write_ini(
            fp,
            supervisord_ini(
                cmd,
                config["validators"],
                config["chain_id"],
                start_flags=start_flags,
            ),
        )

    if gen_compose_file:
        yaml.dump(
            docker_compose_yml(cmd, config["validators"], data_dir, image),
            (data_dir / "docker-compose.yml").open("w"),
        )


def get_relayer_chain_config(relayer_chains_config, chain_id):
    return next((i for i in relayer_chains_config if i["id"] == chain_id), {})


def relayer_chain_config_hermes(data_dir, chain, relayer_chains_config):
    chain_id = chain["chain_id"]
    cfg = json.load((data_dir / chain_id / "config.json").open())
    base_port = cfg["validators"][0]["base_port"]
    rpc_port = ports.rpc_port(base_port)
    grpc_port = ports.grpc_port(base_port)
    config = {
        "key_name": "relayer",
        "id": chain_id,
        "rpc_addr": f"http://127.0.0.1:{rpc_port}",
        "grpc_addr": f"http://127.0.0.1:{grpc_port}",
        "rpc_timeout": "10s",
        "account_prefix": chain.get("account-prefix", "cro"),
        "store_prefix": "ibc",
        "max_gas": 300000,
        "gas_price": {"price": 0, "denom": "basecro"},
        "trusting_period": "336h",
    }
    raw = subprocess.check_output(["hermes", "--version"]).decode("utf-8")
    version = raw.strip().split("+")[0].removeprefix("hermes ")
    is_legacy = tuple(map(int, version.split("."))) < (1, 6, 0)
    if is_legacy:
        config["websocket_addr"] = f"ws://localhost:{rpc_port}/websocket"
    else:
        config["event_source"] = {
            "mode": "push",
            "url": f"ws://127.0.0.1:{rpc_port}/websocket",
            "batch_delay": "200ms",
        }
    return jsonmerge.merge(
        config,
        get_relayer_chain_config(relayer_chains_config, chain_id),
    )


def relayer_chain_config_rly(data_dir, chain, relayer_chains_config):
    chain_id = chain["chain_id"]
    folder = data_dir / chain_id
    cfg = json.load((folder / "config.json").open())
    base_port = cfg["validators"][0]["base_port"]
    rpc_port = ports.rpc_port(base_port)
    json_rpc_addr = ports.evmrpc_port(base_port)
    chain_config = get_relayer_chain_config(relayer_chains_config, chain_id)
    address_type = chain_config.get("address_type", {})
    derivation = address_type.get("derivation")
    gas_price = chain_config.get("gas_price", {})
    price = gas_price.get("price", 0)
    denom = gas_price.get("denom", "basecro")
    prices = f"{price}{denom}"
    precompiled = chain_config.get("precompiled_contract_address", "")
    return {
        "type": "cosmos",
        "value": {
            "key-directory": f"{folder}/node0",
            "key": "relayer",
            "chain-id": chain_id,
            "rpc-addr": f"http://127.0.0.1:{rpc_port}",
            "json-rpc-addr": f"http://127.0.0.1:{json_rpc_addr}",
            "account-prefix": chain.get("account-prefix", "cro"),
            "keyring-backend": chain_config.get("keyring-backend", "test"),
            "gas-adjustment": chain_config.get("gas_multiplier", 1.2),
            "feegrants": chain_config.get("feegrants", None),
            "gas-prices": prices,
            "extension-options": chain_config.get("extension_options", []),
            "min-gas-amount": 0,
            "max-gas-amount": chain_config.get("max_gas", 300000),
            "debug": chain_config.get("debug", False),
            "timeout": chain_config.get("timeout", "20s"),
            "block-timeout": "",
            "output-format": "json",
            "sign-mode": "direct",
            "extra-codecs": [derivation] if derivation else [],
            "coin-type": chain.get("coin-type", 118),
            "precompiled-contract-address": precompiled,
            "signing-algorithm": "",
            "broadcast-mode": "batch",
            "min-loop-duration": "0s",
        },
    }


class Relayer(Enum):
    HERMES = "hermes"
    RLY = "rly"


def init_cluster(
    data_dir,
    config_path,
    base_port,
    dotenv=None,
    image=IMAGE,
    cmd=None,
    gen_compose_file=False,
    relayer=Relayer.HERMES.value,
):
    is_hermes = relayer == Relayer.HERMES.value
    extension = Path(config_path).suffix
    if extension == ".jsonnet":
        config = expand_jsonnet(config_path, dotenv)
    else:
        config = expand_yaml(config_path, dotenv)

    relayer_config = config.pop("relayer", {})
    for chain_id, cfg in config.items():
        cfg["path"] = str(config_path)
        cfg["chain_id"] = chain_id

    chains = list(config.values())
    for chain in chains:
        (data_dir / chain["chain_id"]).mkdir()
        init_devnet(
            data_dir / chain["chain_id"], chain, base_port, image, cmd, gen_compose_file
        )
    with (data_dir / SUPERVISOR_CONFIG_FILE).open("w") as fp:
        write_ini(
            fp,
            supervisord_ini_group(config.keys(), is_hermes),
        )
    if len(chains) > 1:
        cfg = relayer_config.pop("chains", {})
        if is_hermes:
            # write relayer config for hermes
            relayer_config_hermes = data_dir / "relayer.toml"
            relayer_config_hermes.write_text(
                tomlkit.dumps(
                    jsonmerge.merge(
                        {
                            "global": {
                                "log_level": "info",
                            },
                            "chains": [
                                relayer_chain_config_hermes(data_dir, c, cfg)
                                for c in chains
                            ],
                        },
                        relayer_config,
                    )
                )
            )
        else:
            # write relayer config folder for rly
            relayer_config_dir = data_dir / "relayer/config"
            relayer_config_dir.mkdir(parents=True, exist_ok=True)
            relayer_config_rly = relayer_config_dir / "config.yaml"
            log_level = relayer_config.get("global", {}).get("log_level", "")
            relayer_config_rly.write_text(
                yaml.dump(
                    {
                        "global": {
                            "api-listen-addr": ":5183",
                            "timeout": "10s",
                            "memo": "",
                            "light-cache-size": 20,
                            "log-level": log_level,
                        },
                        "chains": {
                            c["chain_id"]: relayer_chain_config_rly(data_dir, c, cfg)
                            for c in chains
                        },
                    }
                )
            )
        for chain in chains:
            key_name = chain.get("key_name", "relayer")
            mnemonic = find_account(data_dir, chain["chain_id"], key_name)["mnemonic"]
            mnemonic_path = Path(data_dir) / "relayer.env"
            mnemonic_path.write_text(mnemonic)
            if is_hermes:
                # restore the relayer account for hermes
                subprocess.run(
                    [
                        "hermes",
                        "--config",
                        relayer_config_hermes,
                        "keys",
                        "add",
                        "--chain",
                        chain["chain_id"],
                        "--mnemonic-file",
                        str(mnemonic_path),
                        "--overwrite",
                        "--hd-path",
                        "m/44'/" + str(chain.get("coin-type", 394)) + "'/0'/0/0",
                    ],
                    check=True,
                )
            else:
                # restore the relayer account for rly
                subprocess.run(
                    [
                        "rly",
                        "keys",
                        "restore",
                        chain["chain_id"],
                        "relayer",
                        mnemonic,
                        "--home",
                        str(data_dir / "relayer"),
                    ],
                    check=True,
                )


def find_account(data_dir, chain_id, name):
    accounts = json.load((data_dir / chain_id / "accounts.json").open())
    return next(acct for acct in accounts if acct["name"] == name)


def supervisord_ini(cmd, validators, chain_id, start_flags=""):
    ini = {}
    for i, node in enumerate(validators):
        directory = f"%(here)s/node{i}"
        ini[f"program:{chain_id}-node{i}"] = dict(
            COMMON_PROG_OPTIONS,
            directory=directory,
            command=f"{cmd} start --home . {start_flags}",
            stdout_logfile=f"{directory}.log",
        )
    return ini


def supervisord_ini_group(chain_ids, is_hermes):
    directory = "%(here)s"
    cfg = {
        "include": {
            "files": " ".join(
                f"{directory}/{chain_id}/tasks.ini" for chain_id in chain_ids
            )
        },
        "supervisord": {
            "pidfile": f"{directory}/supervisord.pid",
            "nodaemon": "true",
            "logfile": "/dev/null",
            "logfile_maxbytes": "0",
            "strip_ansi": "true",
        },
        "rpcinterface:supervisor": {
            "supervisor.rpcinterface_factory": "supervisor.rpcinterface:"
            "make_main_rpcinterface",
        },
        "unix_http_server": {"file": f"{directory}/supervisor.sock"},
        "supervisorctl": {"serverurl": f"unix://{directory}/supervisor.sock"},
    }
    command = "hermes --config relayer.toml start"
    if not is_hermes:
        command = "rly start chainmain-cronos --home relayer"
    cfg["program:relayer-demo"] = dict(
        COMMON_PROG_OPTIONS,
        directory=directory,
        command=command,
        stdout_logfile=f"{directory}/relayer-demo.log",
        autostart="false",
    )
    return cfg


def docker_compose_yml(cmd, validators, data_dir, image):
    return {
        "version": "3",
        "services": {
            f"node{i}": {
                "image": image,
                "command": "chaind start",
                "volumes": [f"{data_dir.absolute() / f'node{i}'}:/.chain-maind:Z"],
            }
            for i, val in enumerate(validators)
        },
    }


def edit_tm_cfg(path, base_port, peers, config, *, custom_edit=None):
    "field name changed after tendermint 0.35, support both flavours."
    with open(path) as f:
        doc = tomlkit.parse(f.read())
    doc["mode"] = "validator"
    # tendermint is start in process, not needed
    # doc['proxy_app'] = 'tcp://127.0.0.1:%d' % abci_port(base_port)
    rpc = doc["rpc"]
    rpc["laddr"] = "tcp://127.0.0.1:%d" % ports.rpc_port(base_port)
    rpc["pprof_laddr"] = rpc["pprof-laddr"] = "127.0.0.1:%d" % (
        ports.pprof_port(base_port),
    )
    rpc["timeout_broadcast_tx_commit"] = rpc["timeout-broadcast-tx-commit"] = "30s"
    rpc["grpc_laddr"] = rpc["grpc-laddr"] = "tcp://127.0.0.1:%d" % (
        ports.grpc_port_tx_only(base_port),
    )
    p2p = doc["p2p"]
    # p2p["use-legacy"] = True
    p2p["laddr"] = "tcp://127.0.0.1:%d" % ports.p2p_port(base_port)
    p2p["persistent_peers"] = p2p["persistent-peers"] = peers
    p2p["addr_book_strict"] = p2p["addr-book-strict"] = False
    p2p["allow_duplicate_ip"] = p2p["allow-duplicate-ip"] = True
    doc["consensus"]["timeout_commit"] = doc["consensus"]["timeout-commit"] = "1s"
    patch_toml_doc(doc, config)
    if custom_edit is not None:
        custom_edit(doc)
    with open(path, "w") as f:
        f.write(tomlkit.dumps(doc))


def patch_toml_doc(doc, patch):
    for k, v in patch.items():
        if isinstance(v, dict):
            patch_toml_doc(doc.setdefault(k, {}), v)
        else:
            doc[k] = v


def edit_app_cfg(path, base_port, app_config):
    default_patch = {
        "api": {
            "enable": True,
            "swagger": True,
            "enable-unsafe-cors": True,
            "address": "tcp://127.0.0.1:%d" % ports.api_port(base_port),
        },
        "grpc": {
            "address": "127.0.0.1:%d" % ports.grpc_port(base_port),
        },
        "pruning": "nothing",
        "state-sync": {
            "snapshot-interval": 5,
            "snapshot-keep-recent": 10,
        },
        "minimum-gas-prices": "0basecro",
    }

    app_config = format_value(
        app_config,
        {
            "EVMRPC_PORT": ports.evmrpc_port(base_port),
            "EVMRPC_PORT_WS": ports.evmrpc_ws_port(base_port),
        },
    )
    with open(path) as f:
        doc = tomlkit.parse(f.read())
    doc["grpc-web"] = {}
    doc["grpc-web"]["address"] = "127.0.0.1:%d" % ports.grpc_web_port(base_port)
    patch_toml_doc(doc, jsonmerge.merge(default_patch, app_config))
    open(path, "w").write(tomlkit.dumps(doc))


def format_value(v, ctx):
    if isinstance(v, str):
        return v.format(**ctx)
    elif isinstance(v, dict):
        return {k: format_value(vv, ctx) for k, vv in v.items()}
    else:
        return v


def try_remove_peer(peers, peer):
    "try remove peer from peers, do nothing if don't contains the peer."
    items = peers.split(",")
    try:
        items.remove(peer)
    except ValueError:
        return peers
    else:
        return ",".join(items)


if __name__ == "__main__":
    interact("rm -r data; mkdir data", ignore_error=True)
    data_dir = Path("data")
    init_cluster(data_dir, "config.yaml", 26650)
    supervisord = start_cluster(data_dir)
    t = start_tail_logs_thread(data_dir)
    supervisord.wait()
    t.stop()
    t.join()
