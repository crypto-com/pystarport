# Usage

## Available Commands

```shell
pystarport -c
```

Commands below are useful for starting a blockchain locally and managing it:

- `pystarport init`: preparation to start a local blockchain based on the provided configuration file.
- `pystarport start`: start the local blockchain.
- `pystarport serve`: combination of `pystarport init` and `pystarport start`.
- `pystarport supervisorctl`: use the embedded [supervisor](http://supervisord.org/) to manage processes of multiple blockchain nodes and the relayer.

You can append `--help` to any command for more information.

## The Configuration File

The configuration file is a crucial part to set up the local blockchain environment. It can be in `.yaml` or `.jsonnet` format. (`.jsonnet` format is preferred for its flexibility and ability to generate complex configurations programmatically). Some examples of configuration files for starting Cronos or Cronos POS blockchain are provided in the `docs/sample_pystarport_configs` directory.

### Configuration File Structure for Single Blockchain

#### `chain_id`

The unique identifier for the blockchain. For example, `cronos_777-1`.

In this case, the Cosmos chain ID is `cronos_777-1`, and the EVM chain ID is `777`.

#### `cmd`

The command to start the blockchain node (e.g., `chain-maind` or `cronosd`), make sure they are present in the `PATH`.

#### `start-flags`

Additional flags to pass to the command when starting the node.

#### `validators`

A list of validator configurations, each containing:

- `coins`: the amount and denomination of coins the validator has.
- `staked`: the amount and denomination of coins the validator has staked.
- `gas_prices`: the gas prices for the validator's transactions. (Only required for EVM chains)
- `mnemonic`: the mnemonic phrase for the validator's key.
- `base_port`: the base port for the validator's RPC server.
- (optional) `moniker`: human readable name for the node (default is node1, node2, etc.)

For a full node configuration, you can omit the `coins`, `staked`, `gas_prices`, and `mnemonic` fields.

```jsonnet
validators: [
  {
    moniker: "fullnode_jsonnet_example",
    base_port: 26780
  }
]
```

#### `accounts`

A list of genesis account configurations with coins, each containing:

- `name`: the name of the genesis account imported to local keyring.
- `coins`: the amount of coins the genesis account has.
- `address`: the address of the genesis account. (If this field exists, `mnemonic` field will be ignored. This field can be left out, if `mnemonic` is provided)
- `mnemonic`: the mnemonic phrase for the genesis account.

#### `config` and `app-config`

`config` section patches `config.toml` and `app-config` section patches `app.toml`.

E.g. to use this config in the `app.toml` for the local blockchain

```toml
minimum-gas-prices="0.025basetcro"

[json-rpc]
block-range-cap = 10000
```

Add section below to the config yaml file

```yaml
app-config:
  minimum-gas-prices: "0.025basetcro"
  json-rpc:
    block-range-cap: 10000
```

or config jsonnet file

```jsonnet
app-config: {
  minimum-gas-prices: "0.025basetcro",
  json-rpc: {
    block-range-cap: 10000
  }
}
```

By default, all validators have the same `config.toml` and `app.toml`. If you would like to customize these files for each validator, you can do so by specifying the `config` and `app-config` sections for each validator in the configuration file.

```jsonnet
validators: [
  {
    moniker: "validator_jsonnet_example",
    coins: '200000000000000000basetcro',
    staked: '100000000000000000basetcro',
    mnemonic: "valid mnemonic",
    base_port: 26750,
    // this validator requires different minimum gas prices
    'app-config': {
      minimum-gas-prices: "0.05basetcro"
    },
  },
  'app-config': {
    minimum-gas-prices: "0.025basetcro",
  }
]
```

#### `genesis`

`genesis` section patches the `genesis.json` file. Its syntax is similar to the `config` and `app-config` sections.
**Note:** The genesis is the initial state of the entire local blockchain, hence it does not allow customization for each validator like the `config` and `app-config` sections.


### Configuration File Structure for Blockchains with IBC

The configuration file for blockchains with IBC (Inter-Blockchain Communication) is similar to that of single blockchains, but it includes the additional section for relayer configurations. And you will also see the `.jsonnet` format is simpler than the `.yaml` format. For more relayer configurations, please refer to the [Hermes documentation](https://hermes.informal.systems/documentation/configuration/description.html).

## Start Local Blockchain

### Single Blockchain

```shell
# make sure <your_node_command, e.g. chain-maind> is in your PATH
pystarport start --config=<path_to_your_single_blockchain_config_file>
```

### Start Blockchains with IBC

```shell
# make sure <your_node_command, e.g. chain-maind> is in your PATH
# make sure hermes is in your PATH
pystarport start --config=<path_to_your_blockchains_with_ibc_config_file>

# wait for blockchains to reach at lease block height 2, then create an IBC channel
hermes create channel [OPTIONS] --a-chain <A_CHAIN_ID> --b-chain <B_CHAIN_ID> --a-port <A_PORT_ID> --b-port <B_PORT_ID> --new-client-connection

# wait for channels to be created successfully, then start the relayer
supervisorctl -c /path/to/supervisor/task.ini start relayer-demo
```
