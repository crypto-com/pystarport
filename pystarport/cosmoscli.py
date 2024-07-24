import enum
import hashlib
import json
import subprocess
import tempfile
import threading
import time

import bech32
import durations
from dateutil.parser import isoparse

from .app import CHAIN
from .ledger import ZEMU_BUTTON_PORT, ZEMU_HOST, LedgerButton
from .utils import (
    build_cli_args_safe,
    format_doc_string,
    get_sync_info,
    interact,
    parse_amount,
)


class ModuleAccount(enum.Enum):
    FeeCollector = "fee_collector"
    Mint = "mint"
    Gov = "gov"
    Distribution = "distribution"
    BondedPool = "bonded_tokens_pool"
    NotBondedPool = "not_bonded_tokens_pool"
    IBCTransfer = "transfer"


@format_doc_string(
    options=",".join(v.value for v in ModuleAccount.__members__.values())
)
def module_address(name):
    """
    get address of module accounts

    :param name: name of module account, values: {options}
    """
    data = hashlib.sha256(ModuleAccount(name).value.encode()).digest()[:20]
    return bech32.bech32_encode("cro", bech32.convertbits(data, 8, 5))


class ChainCommand:
    def __init__(self, cmd=None):
        self.cmd = cmd or CHAIN

    def prob_genesis_subcommand(self):
        'test if the command has "genesis" subcommand, introduced in sdk 0.50'
        try:
            output = self("genesis")
        except AssertionError:
            # non-zero return code
            return False

        return "Available Commands" in output.decode()

    def prob_icaauth_subcommand(self):
        'test if the command has "icaauth" subcommand, removed after ibc 8.3'
        try:
            output = self("q", "icaauth")
        except AssertionError:
            # non-zero return code
            return False

        return "Available Commands" in output.decode()

    def __call__(self, cmd, *args, stdin=None, stderr=subprocess.STDOUT, **kwargs):
        "execute chain-maind"
        args = " ".join(build_cli_args_safe(cmd, *args, **kwargs))
        return interact(f"{self.cmd} {args}", input=stdin, stderr=stderr)


class CosmosCLI:
    "the apis to interact with wallet and blockchain"

    def __init__(
        self,
        data_dir,
        node_rpc,
        chain_id=None,
        cmd=None,
        zemu_address=ZEMU_HOST,
        zemu_button_port=ZEMU_BUTTON_PORT,
    ):
        self.data_dir = data_dir
        if chain_id is None:
            src = (self.data_dir / "config" / "genesis.json").read_text()
            self._genesis = json.loads(src)
            self.chain_id = self._genesis["chain_id"]
        else:
            self.chain_id = chain_id
        self.node_rpc = node_rpc
        self.raw = ChainCommand(cmd)
        self.leger_button = LedgerButton(zemu_address, zemu_button_port)
        self.output = None
        self.error = None
        self.has_genesis_subcommand = self.raw.prob_genesis_subcommand()
        self.has_icaauth_subcommand = self.raw.prob_icaauth_subcommand()

    def node_id(self):
        "get tendermint node id"
        output = self.raw("tendermint", "show-node-id", home=self.data_dir)
        return output.decode().strip()

    def delete_account(self, name):
        "delete wallet account in node's keyring"
        return self.raw(
            "keys",
            "delete",
            name,
            "-y",
            "--force",
            home=self.data_dir,
            output="json",
            keyring_backend="test",
        )

    def create_account(self, name, mnemonic=None):
        "create new keypair in node's keyring"
        if mnemonic is None:
            output = self.raw(
                "keys",
                "add",
                name,
                home=self.data_dir,
                output="json",
                keyring_backend="test",
            )
        else:
            output = self.raw(
                "keys",
                "add",
                name,
                "--recover",
                home=self.data_dir,
                output="json",
                keyring_backend="test",
                stdin=mnemonic.encode() + b"\n",
            )
        return json.loads(output)

    def create_account_ledger(self, name):
        "create new ledger keypair"

        def send_request():
            try:
                self.output = self.raw(
                    "keys",
                    "add",
                    name,
                    "--ledger",
                    home=self.data_dir,
                    output="json",
                    keyring_backend="test",
                )
            except Exception as e:
                self.error = e

        t = threading.Thread(target=send_request)
        t.start()
        time.sleep(3)
        for _ in range(0, 3):
            self.leger_button.press_right()
            time.sleep(0.2)
        self.leger_button.press_both()
        t.join()
        if self.error:
            raise self.error
        return json.loads(self.output)

    def init(self, moniker):
        "the node's config is already added"
        return self.raw(
            "init",
            moniker,
            chain_id=self.chain_id,
            home=self.data_dir,
        )

    def genesis_subcommand(self, *args, **kwargs):
        if self.has_genesis_subcommand:
            return self.raw("genesis", *args, **kwargs)
        else:
            return self.raw(*args, **kwargs)

    def validate_genesis(self, *args):
        return self.genesis_subcommand("validate-genesis", *args, home=self.data_dir)

    def add_genesis_account(self, addr, coins, **kwargs):
        return self.genesis_subcommand(
            "add-genesis-account",
            addr,
            coins,
            home=self.data_dir,
            output="json",
            **kwargs,
        )

    def gentx(self, name, coins, *args, min_self_delegation=1, pubkey=None, **kwargs):
        return self.genesis_subcommand(
            "gentx",
            name,
            coins,
            *args,
            min_self_delegation=str(min_self_delegation),
            home=self.data_dir,
            chain_id=self.chain_id,
            keyring_backend="test",
            pubkey=pubkey,
            **kwargs,
        )

    def collect_gentxs(self, gentx_dir):
        return self.genesis_subcommand("collect-gentxs", gentx_dir, home=self.data_dir)

    def status(self):
        return json.loads(self.raw("status", node=self.node_rpc))

    def block_height(self):
        return int(get_sync_info(self.status())["latest_block_height"])

    def block_time(self):
        return isoparse(get_sync_info(self.status())["latest_block_time"])

    def balances(self, addr, height=0):
        return json.loads(
            self.raw(
                "query", "bank", "balances", addr, height=height, home=self.data_dir
            )
        )["balances"]

    def balance(self, addr, denom=None, height=0):
        coins = self.balances(addr, height=height)
        if denom is None:
            if len(coins) == 0:
                return 0
            coin = coins[0]
            return int(coin["amount"])
        denoms = {coin["denom"]: int(coin["amount"]) for coin in coins}
        return denoms.get(denom, 0)

    def query_tx(self, tx_type, tx_value):
        tx = self.raw(
            "query",
            "tx",
            "--type",
            tx_type,
            tx_value,
            home=self.data_dir,
            node=self.node_rpc,
        )
        return json.loads(tx)

    def query_all_txs(self, addr):
        txs = self.raw(
            "query",
            "txs-all",
            addr,
            home=self.data_dir,
            keyring_backend="test",
            node=self.node_rpc,
        )
        return json.loads(txs)

    def distribution_commission(self, addr):
        res = json.loads(
            self.raw(
                "query",
                "distribution",
                "commission",
                addr,
                output="json",
                node=self.node_rpc,
            )
        )["commission"]
        return parse_amount((res.get("commission") or res)[0])

    def distribution_community(self):
        res = json.loads(
            self.raw(
                "query",
                "distribution",
                "community-pool",
                output="json",
                node=self.node_rpc,
            )
        )
        return parse_amount(res["pool"][0])

    def distribution_reward(self, delegator_addr):
        res = json.loads(
            self.raw(
                "query",
                "distribution",
                "rewards",
                delegator_addr,
                output="json",
                node=self.node_rpc,
            )
        )
        return parse_amount(res["total"][0])

    def address(self, name, bech="acc"):
        output = self.raw(
            "keys",
            "show",
            name,
            "-a",
            home=self.data_dir,
            keyring_backend="test",
            bech=bech,
        )
        return output.strip().decode()

    def account(self, addr):
        return json.loads(
            self.raw(
                "query", "auth", "account", addr, output="json", node=self.node_rpc
            )
        )

    def supply(self, supply_type):
        return json.loads(
            self.raw("query", "supply", supply_type, output="json", node=self.node_rpc)
        )

    def validator(self, addr):
        res = json.loads(
            self.raw(
                "query",
                "staking",
                "validator",
                addr,
                output="json",
                node=self.node_rpc,
            )
        )
        return res.get("validator") or res

    def validators(self):
        return json.loads(
            self.raw(
                "query", "staking", "validators", output="json", node=self.node_rpc
            )
        )["validators"]

    def staking_params(self):
        res = json.loads(
            self.raw("query", "staking", "params", output="json", node=self.node_rpc)
        )
        return res.get("params") or res

    def staking_pool(self, bonded=True):
        res = self.raw("query", "staking", "pool", output="json", node=self.node_rpc)
        res = json.loads(res)
        res = res.get("pool") or res
        return int(res["bonded_tokens" if bonded else "not_bonded_tokens"])

    def transfer(
        self,
        from_,
        to,
        coins,
        generate_only=False,
        event_query_tx=True,
        **kwargs,
    ):
        rsp = json.loads(
            self.raw(
                "tx",
                "bank",
                "send",
                from_,
                to,
                coins,
                "-y",
                "--generate-only" if generate_only else None,
                home=self.data_dir,
                keyring_backend="test",
                chain_id=self.chain_id,
                node=self.node_rpc,
                **kwargs,
            )
        )
        if not generate_only and rsp["code"] == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def transfer_from_ledger(
        self,
        from_,
        to,
        coins,
        generate_only=False,
        fees=None,
        event_query_tx=True,
        **kwargs,
    ):
        def send_request():
            try:
                self.output = json.loads(
                    self.raw(
                        "tx",
                        "bank",
                        "send",
                        from_,
                        to,
                        coins,
                        "-y",
                        "--generate-only" if generate_only else "",
                        "--ledger",
                        home=self.data_dir,
                        keyring_backend="test",
                        chain_id=self.chain_id,
                        node=self.node_rpc,
                        fees=fees,
                        sign_mode="amino-json",
                        **kwargs,
                    )
                )
                if not generate_only and self.output["code"] == 0 and event_query_tx:
                    self.output = self.event_query_tx_for(self.output["txhash"])
            except Exception as e:
                self.error = e

        t = threading.Thread(target=send_request)
        t.start()
        time.sleep(3)
        for _ in range(0, 11):
            self.leger_button.press_right()
            time.sleep(0.4)
        self.leger_button.press_both()
        t.join()
        if self.error:
            raise self.error
        return self.output

    def get_delegated_amount(self, which_addr):
        return json.loads(
            self.raw(
                "query",
                "staking",
                "delegations",
                which_addr,
                home=self.data_dir,
                node=self.node_rpc,
                output="json",
            )
        )

    def delegate_amount(
        self,
        to_addr,
        amount,
        from_addr,
        gas_price=None,
        event_query_tx=True,
        **kwargs,
    ):
        rsp = json.loads(
            self.raw(
                "tx",
                "staking",
                "delegate",
                to_addr,
                amount,
                "-y",
                home=self.data_dir,
                from_=from_addr,
                keyring_backend="test",
                chain_id=self.chain_id,
                node=self.node_rpc,
                gas_prices=gas_price,
                **kwargs,
            )
        )
        if rsp["code"] == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    # to_addr: croclcl1...  , from_addr: cro1...
    def unbond_amount(self, to_addr, amount, from_addr, event_query_tx=True, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "staking",
                "unbond",
                to_addr,
                amount,
                "-y",
                home=self.data_dir,
                from_=from_addr,
                keyring_backend="test",
                chain_id=self.chain_id,
                node=self.node_rpc,
                **kwargs,
            )
        )
        if rsp["code"] == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    # to_validator_addr: crocncl1...  ,  from_from_validator_addraddr: crocl1...
    def redelegate_amount(
        self,
        to_validator_addr,
        from_validator_addr,
        amount,
        from_addr,
        event_query_tx=True,
        **kwargs,
    ):
        rsp = json.loads(
            self.raw(
                "tx",
                "staking",
                "redelegate",
                from_validator_addr,
                to_validator_addr,
                amount,
                "-y",
                home=self.data_dir,
                from_=from_addr,
                keyring_backend="test",
                chain_id=self.chain_id,
                node=self.node_rpc,
                **kwargs,
            )
        )
        if rsp["code"] == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    # from_delegator can be account name or address
    def withdraw_all_rewards(self, from_delegator, event_query_tx=True, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "distribution",
                "withdraw-all-rewards",
                "-y",
                from_=from_delegator,
                home=self.data_dir,
                keyring_backend="test",
                chain_id=self.chain_id,
                node=self.node_rpc,
                **kwargs,
            )
        )
        if rsp["code"] == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def make_multisig(self, name, signer1, signer2):
        self.raw(
            "keys",
            "add",
            name,
            multisig=f"{signer1},{signer2}",
            multisig_threshold="2",
            home=self.data_dir,
            keyring_backend="test",
        )

    def sign_multisig_tx(self, tx_file, multi_addr, signer_name, **kwargs):
        return json.loads(
            self.raw(
                "tx",
                "sign",
                tx_file,
                from_=signer_name,
                multisig=multi_addr,
                home=self.data_dir,
                keyring_backend="test",
                chain_id=self.chain_id,
                node=self.node_rpc,
                **kwargs,
            )
        )

    def sign_batch_multisig_tx(
        self,
        tx_file,
        multi_addr,
        signer_name,
        account_number,
        sequence_number,
        **kwargs,
    ):
        r = self.raw(
            "tx",
            "sign-batch",
            "--offline",
            tx_file,
            account_number=account_number,
            sequence=sequence_number,
            from_=signer_name,
            multisig=multi_addr,
            home=self.data_dir,
            keyring_backend="test",
            chain_id=self.chain_id,
            node=self.node_rpc,
            **kwargs,
        )
        return r.decode("utf-8")

    def encode_signed_tx(self, signed_tx, **kwargs):
        return self.raw(
            "tx",
            "encode",
            signed_tx,
            **kwargs,
        )

    def sign_single_tx(self, tx_file, signer_name, **kwargs):
        return json.loads(
            self.raw(
                "tx",
                "sign",
                tx_file,
                from_=signer_name,
                home=self.data_dir,
                keyring_backend="test",
                chain_id=self.chain_id,
                node=self.node_rpc,
                **kwargs,
            )
        )

    def combine_multisig_tx(
        self, tx_file, multi_name, signer1_file, signer2_file, **kwargs
    ):
        return json.loads(
            self.raw(
                "tx",
                "multisign",
                tx_file,
                multi_name,
                signer1_file,
                signer2_file,
                home=self.data_dir,
                keyring_backend="test",
                chain_id=self.chain_id,
                node=self.node_rpc,
                **kwargs,
            )
        )

    def combine_batch_multisig_tx(
        self, tx_file, multi_name, signer1_file, signer2_file, **kwargs
    ):
        r = self.raw(
            "tx",
            "multisign-batch",
            tx_file,
            multi_name,
            signer1_file,
            signer2_file,
            home=self.data_dir,
            keyring_backend="test",
            chain_id=self.chain_id,
            node=self.node_rpc,
            **kwargs,
        )
        return r.decode("utf-8")

    def broadcast_tx(self, tx_file, **kwargs):
        r = self.raw(
            "tx",
            "broadcast",
            tx_file,
            node=self.node_rpc,
            broadcast_mode="sync",
            **kwargs,
        )
        return r.decode("utf-8")

    def unjail(self, addr, event_query_tx=True, **kwargs):
        rsp = json.loads(
            self.raw(
                "tx",
                "slashing",
                "unjail",
                "-y",
                from_=addr,
                home=self.data_dir,
                node=self.node_rpc,
                keyring_backend="test",
                chain_id=self.chain_id,
                **kwargs,
            )
        )
        if rsp["code"] == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def create_validator(
        self,
        amount,
        options,
        event_query_tx=True,
        **kwargs,
    ):
        options = {
            "commission-max-change-rate": "0.01",
            "commission-rate": "0.1",
            "commission-max-rate": "0.2",
            "min-self-delegation": "1",
            "amount": amount,
        } | options

        if "pubkey" not in options:
            pubkey = (
                self.raw(
                    "tendermint",
                    "show-validator",
                    home=self.data_dir,
                )
                .strip()
                .decode()
            )
            options["pubkey"] = json.loads(pubkey)

        with tempfile.NamedTemporaryFile("w") as fp:
            json.dump(options, fp)
            fp.flush()
            raw = self.raw(
                "tx",
                "staking",
                "create-validator",
                fp.name,
                "-y",
                from_=self.address("validator"),
                # basic
                home=self.data_dir,
                node=self.node_rpc,
                keyring_backend="test",
                chain_id=self.chain_id,
                **kwargs,
            )
        rsp = json.loads(raw)
        if rsp["code"] == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def create_validator_legacy(
        self,
        amount,
        moniker=None,
        commission_max_change_rate="0.01",
        commission_rate="0.1",
        commission_max_rate="0.2",
        min_self_delegation="1",
        event_query_tx=True,
        **kwargs,
    ):
        """MsgCreateValidator
        create the node with create_node before call this"""
        pubkey = (
            self.raw(
                "tendermint",
                "show-validator",
                home=self.data_dir,
            )
            .strip()
            .decode()
        )
        options = {
            "amount": amount,
            "min-self-delegation": min_self_delegation,
            "commission-rate": commission_rate,
            "commission-max-rate": commission_max_rate,
            "commission-max-change-rate": commission_max_change_rate,
            "moniker": moniker,
        }
        options["pubkey"] = "'" + pubkey + "'"
        raw = self.raw(
            "tx",
            "staking",
            "create-validator",
            "-y",
            from_=self.address("validator"),
            # basic
            home=self.data_dir,
            node=self.node_rpc,
            keyring_backend="test",
            chain_id=self.chain_id,
            **{k: v for k, v in options.items() if v is not None},
            **kwargs,
        )
        rsp = json.loads(raw)
        if rsp["code"] == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def edit_validator(
        self,
        commission_rate=None,
        new_moniker=None,
        identity=None,
        website=None,
        security_contact=None,
        details=None,
        event_query_tx=True,
        **kwargs,
    ):
        """MsgEditValidator"""
        options = dict(
            commission_rate=commission_rate,
            # description
            new_moniker=new_moniker,
            identity=identity,
            website=website,
            security_contact=security_contact,
            details=details,
        )
        rsp = json.loads(
            self.raw(
                "tx",
                "staking",
                "edit-validator",
                "-y",
                from_=self.address("validator"),
                home=self.data_dir,
                node=self.node_rpc,
                keyring_backend="test",
                chain_id=self.chain_id,
                **{k: v for k, v in options.items() if v is not None},
                **kwargs,
            )
        )
        if rsp["code"] == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def gov_propose(self, proposer, kind, proposal, **kwargs):
        if kind == "software-upgrade":
            return json.loads(
                self.raw(
                    "tx",
                    "gov",
                    "submit-proposal",
                    kind,
                    proposal["name"],
                    "-y",
                    from_=proposer,
                    # content
                    title=proposal.get("title"),
                    description=proposal.get("description"),
                    upgrade_height=proposal.get("upgrade-height"),
                    upgrade_time=proposal.get("upgrade-time"),
                    upgrade_info=proposal.get("upgrade-info"),
                    deposit=proposal.get("deposit"),
                    # basic
                    home=self.data_dir,
                    node=self.node_rpc,
                    keyring_backend="test",
                    chain_id=self.chain_id,
                    **kwargs,
                )
            )
        elif kind == "cancel-software-upgrade":
            return json.loads(
                self.raw(
                    "tx",
                    "gov",
                    "submit-proposal",
                    kind,
                    "-y",
                    from_=proposer,
                    # content
                    title=proposal.get("title"),
                    description=proposal.get("description"),
                    deposit=proposal.get("deposit"),
                    # basic
                    home=self.data_dir,
                    node=self.node_rpc,
                    keyring_backend="test",
                    chain_id=self.chain_id,
                    **kwargs,
                )
            )
        else:
            with tempfile.NamedTemporaryFile("w") as fp:
                json.dump(proposal, fp)
                fp.flush()
                return json.loads(
                    self.raw(
                        "tx",
                        "gov",
                        "submit-proposal",
                        kind,
                        fp.name,
                        "-y",
                        from_=proposer,
                        # basic
                        home=self.data_dir,
                        node=self.node_rpc,
                        keyring_backend="test",
                        chain_id=self.chain_id,
                        **kwargs,
                    )
                )

    def gov_vote(self, voter, proposal_id, option, event_query_tx=True, **kwargs):
        print(voter)
        print(proposal_id)
        print(option)
        rsp = json.loads(
            self.raw(
                "tx",
                "gov",
                "vote",
                proposal_id,
                option,
                "-y",
                from_=voter,
                home=self.data_dir,
                node=self.node_rpc,
                keyring_backend="test",
                chain_id=self.chain_id,
                stderr=subprocess.DEVNULL,
                **kwargs,
            )
        )
        if rsp["code"] == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def gov_deposit(
        self, depositor, proposal_id, amount, event_query_tx=True, **kwargs
    ):
        rsp = json.loads(
            self.raw(
                "tx",
                "gov",
                "deposit",
                proposal_id,
                amount,
                "-y",
                from_=depositor,
                home=self.data_dir,
                node=self.node_rpc,
                keyring_backend="test",
                chain_id=self.chain_id,
                **kwargs,
            )
        )
        if rsp["code"] == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def query_proposals(self, depositor=None, limit=None, status=None, voter=None):
        return json.loads(
            self.raw(
                "query",
                "gov",
                "proposals",
                depositor=depositor,
                count_total=limit,
                status=status,
                voter=voter,
                output="json",
                node=self.node_rpc,
            )
        )

    def query_proposal(self, proposal_id):
        res = json.loads(
            self.raw(
                "query",
                "gov",
                "proposal",
                proposal_id,
                output="json",
                node=self.node_rpc,
            )
        )
        return res.get("proposal") or res

    def query_tally(self, proposal_id):
        res = json.loads(
            self.raw(
                "query",
                "gov",
                "tally",
                proposal_id,
                output="json",
                node=self.node_rpc,
            )
        )
        return res.get("tally") or res

    def ibc_transfer(
        self,
        from_,
        to,
        amount,
        channel,  # src channel
        target_version,  # chain version number of target chain
        event_query_tx=True,
        **kwargs,
    ):
        rsp = json.loads(
            self.raw(
                "tx",
                "ibc-transfer",
                "transfer",
                "transfer",  # src port
                channel,
                to,
                amount,
                "-y",
                # FIXME https://github.com/cosmos/cosmos-sdk/issues/8059
                "--absolute-timeouts",
                from_=from_,
                home=self.data_dir,
                node=self.node_rpc,
                keyring_backend="test",
                chain_id=self.chain_id,
                packet_timeout_height=f"{target_version}-10000000000",
                packet_timeout_timestamp=0,
                **kwargs,
            )
        )
        if rsp["code"] == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def export(self):
        return self.raw("export", home=self.data_dir)

    def unsaferesetall(self):
        return self.raw("unsafe-reset-all")

    def create_nft(
        self,
        from_addr,
        denomid,
        denomname,
        schema,
        fees,
        event_query_tx=True,
        **kwargs,
    ):
        rsp = json.loads(
            self.raw(
                "tx",
                "nft",
                "issue",
                denomid,
                "-y",
                fees=fees,
                name=denomname,
                schema=schema,
                home=self.data_dir,
                from_=from_addr,
                keyring_backend="test",
                chain_id=self.chain_id,
                node=self.node_rpc,
                **kwargs,
            )
        )
        if rsp["code"] == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def query_nft(self, denomid):
        return json.loads(
            self.raw(
                "query",
                "nft",
                "denom",
                denomid,
                output="json",
                home=self.data_dir,
                node=self.node_rpc,
            )
        )

    def query_denom_by_name(self, denomname):
        return json.loads(
            self.raw(
                "query",
                "nft",
                "denom-by-name",
                denomname,
                output="json",
                home=self.data_dir,
                node=self.node_rpc,
            )
        )

    def create_nft_token(
        self,
        from_addr,
        to_addr,
        denomid,
        tokenid,
        uri,
        fees,
        event_query_tx=True,
        **kwargs,
    ):
        rsp = json.loads(
            self.raw(
                "tx",
                "nft",
                "mint",
                denomid,
                tokenid,
                "-y",
                uri=uri,
                recipient=to_addr,
                home=self.data_dir,
                from_=from_addr,
                keyring_backend="test",
                chain_id=self.chain_id,
                node=self.node_rpc,
                **kwargs,
            )
        )
        if rsp["code"] == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def query_nft_token(self, denomid, tokenid):
        return json.loads(
            self.raw(
                "query",
                "nft",
                "token",
                denomid,
                tokenid,
                output="json",
                home=self.data_dir,
                node=self.node_rpc,
            )
        )

    def burn_nft_token(
        self, from_addr, denomid, tokenid, event_query_tx=True, **kwargs
    ):
        rsp = json.loads(
            self.raw(
                "tx",
                "nft",
                "burn",
                denomid,
                tokenid,
                "-y",
                from_=from_addr,
                keyring_backend="test",
                home=self.data_dir,
                chain_id=self.chain_id,
                node=self.node_rpc,
                **kwargs,
            )
        )
        if rsp["code"] == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def edit_nft_token(
        self,
        from_addr,
        denomid,
        tokenid,
        newuri,
        newname,
        event_query_tx=True,
        **kwargs,
    ):
        rsp = json.loads(
            self.raw(
                "tx",
                "nft",
                "edit",
                denomid,
                tokenid,
                "-y",
                from_=from_addr,
                uri=newuri,
                name=newname,
                keyring_backend="test",
                home=self.data_dir,
                chain_id=self.chain_id,
                node=self.node_rpc,
                **kwargs,
            )
        )
        if rsp["code"] == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def transfer_nft_token(
        self,
        from_addr,
        to_addr,
        denomid,
        tokenid,
        event_query_tx=True,
        **kwargs,
    ):
        rsp = json.loads(
            self.raw(
                "tx",
                "nft",
                "transfer",
                to_addr,
                denomid,
                tokenid,
                "-y",
                from_=from_addr,
                keyring_backend="test",
                home=self.data_dir,
                chain_id=self.chain_id,
                node=self.node_rpc,
                **kwargs,
            )
        )
        if rsp["code"] == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def event_query_tx_for(self, hash):
        return json.loads(
            self.raw(
                "query",
                "event-query-tx-for",
                hash,
                home=self.data_dir,
                stderr=subprocess.DEVNULL,
            )
        )

    def migrate_keystore(self):
        return self.raw("keys", "migrate", home=self.data_dir)

    def ibc_query_channels(self, connid, **kwargs):
        default_kwargs = {
            "node": self.node_rpc,
            "output": "json",
        }
        return json.loads(
            self.raw(
                "q",
                "ibc",
                "channel",
                "connections",
                connid,
                **(default_kwargs | kwargs),
            )
        )

    def ica_subcommand(self, *args, **kwargs):
        if self.has_icaauth_subcommand:
            return self.raw("tx", *args, **kwargs)
        else:
            return self.raw(*args, **kwargs)

    def ica_register_account(self, connid, event_query_tx=True, **kwargs):
        "execute on host chain to attach an account to the connection"
        default_kwargs = {
            "home": self.data_dir,
            "node": self.node_rpc,
            "chain_id": self.chain_id,
            "keyring_backend": "test",
        }
        args = (
            ["icaauth", "register-account"]
            if self.has_icaauth_subcommand
            else ["ica", "controller", "register"]
        )
        rsp = json.loads(
            self.raw(
                "tx",
                *args,
                connid,
                "-y",
                **(default_kwargs | kwargs),
            )
        )
        if rsp["code"] == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def ica_query_account(self, connid, owner, **kwargs):
        default_kwargs = {
            "node": self.node_rpc,
            "output": "json",
        }
        args = (
            ["icaauth", "interchain-account-address", connid, owner]
            if self.has_icaauth_subcommand
            else ["ica", "controller", "interchain-account", owner, connid]
        )
        return json.loads(
            self.raw(
                "q",
                *args,
                **(default_kwargs | kwargs),
            )
        )

    def ica_submit_tx(
        self,
        connid,
        tx,
        timeout_duration="1h",
        event_query_tx=True,
        **kwargs,
    ):
        default_kwargs = {
            "home": self.data_dir,
            "node": self.node_rpc,
            "chain_id": self.chain_id,
            "keyring_backend": "test",
        }
        if self.has_icaauth_subcommand:
            args = ["icaauth", "submit-tx"]
        else:
            args = ["ica", "controller", "send-tx"]

        duration_args = []
        if timeout_duration:
            if self.has_icaauth_subcommand:
                duration_args = ["--timeout-duration", timeout_duration]
            else:
                timeout = int(durations.Duration(timeout_duration).to_seconds() * 1e9)
                duration_args = ["--relative-packet-timeout", timeout]

        rsp = json.loads(
            self.raw(
                "tx",
                *args,
                connid,
                tx,
                *duration_args,
                "-y",
                **(default_kwargs | kwargs),
            )
        )
        if rsp["code"] == 0 and event_query_tx:
            rsp = self.event_query_tx_for(rsp["txhash"])
        return rsp

    def ica_generate_packet_data(self, tx, memo=None, encoding="proto3", **kwargs):
        return json.loads(
            self.raw(
                "tx",
                "interchain-accounts",
                "host",
                "generate-packet-data",
                tx,
                memo=memo,
                encoding=encoding,
                home=self.data_dir,
                **kwargs,
            )
        )
