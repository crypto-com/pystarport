# Changelog

*Feb 7, 2023*

## v0.2.5

- [#51](https://github.com/crypto-com/pystarport/pull/51) support include yaml
- [#52](https://github.com/crypto-com/pystarport/pull/52) support jsonnet as config language
- [#56](https://github.com/crypto-com/pystarport/pull/56) Support override config.toml for all validators
- [#69](https://github.com/crypto-com/pystarport/pull/69) Support hermes 1.x
- [#70](https://github.com/crypto-com/pystarport/pull/70) Add config item `cmd-flags` to supply custom flags for all
  chain binary commands
- [#71](https://github.com/crypto-com/pystarport/pull/71) strip ansi codes from the node's output
- [#73](https://github.com/crypto-com/pystarport/pull/73) Support more optional validator fields:
  commission_rate/commission_max_rate/commission_max_change_rate/details/security_contact
- [#78](https://github.com/crypto-com/pystarport/pull/78) Set working directory for node processes in supervisor
- [#79](https://github.com/crypto-com/pystarport/pull/79) Add directory for relayer log
- [#81](https://github.com/crypto-com/pystarport/pull/81) Fix grpc port in client.toml

*Feb 18, 2022*

## v0.2.4

- [#41](https://github.com/crypto-com/pystarport/pull/41) don't install the license as data files.
- [#42](https://github.com/crypto-com/pystarport/pull/42) add `--no_remove` option to keep existing data directory.
- [#43](https://github.com/crypto-com/pystarport/pull/43) prefer cmd parameter passed in cli to the one in config file.
- [#46](https://github.com/crypto-com/pystarport/pull/46) support tendermint 0.35.
- [#48](https://github.com/crypto-com/pystarport/pull/48) don't validate genesis for state-sync mode.

*Dec 3, 2021*

## v0.2.3

- [29](https://github.com/crypto-com/pystarport/pull/29) Allow vesting portion of the allocated fund in account
- [28](https://github.com/crypto-com/pystarport/pull/28) Support overwrite default relayer config with configs used to setup chains
- [13](https://github.com/crypto-com/pystarport/issues/13) Support configure start command flags
- [19](https://github.com/crypto-com/pystarport/issues/19) Support `config` to patch `config.toml` for each validator
- [37](https://github.com/crypto-com/pystarport/pull/37) Add expansion feature

*Jul 6, 2021*

## v0.2.2

- [12](https://github.com/crypto-com/pystarport/issues/12) Add back mnemonics
  
- [11](https://github.com/crypto-com/pystarport/pull/11)
  Add min-gas prices 
  Add quotes on validator pubkey, as ProtoJSON is used in 0.43


*Jun 17, 2021*
## v0.2.1

- [5](https://github.com/crypto-com/pystarport/issues/5) Add `query_denom_by_name` to check existing denom before issuing
- [2](https://github.com/crypto-com/pystarport/issues/2) Add mnemonic option field for accounts

## v0.2.0

- Support `app-config` to patch `app.toml` for each validator

