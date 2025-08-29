local chainmain_devnet = import 'chain-main_sample.jsonnet';
local cronos_devnet = import 'cronos_sample.jsonnet';

{
  'cronos_777-1': cronos_devnet['cronos_777-1'] { 'coin-type': 60 },
  'chainmain_777-1': chainmain_devnet['chainmain_777-1'] { 'coin-type': 1 },
  relayer: {
    // https://hermes.informal.systems/documentation/configuration/index.html
    chains: [
      {
        id: 'chainmain_777-1',  // id needs to match the chain ID
        account_prefix: 'tcro',
        default_gas: 1000000,
        max_gas: 3000000,
        gas_multiplier: 1.1,
        address_type: {
          derivation: 'cosmos',
        },
        gas_price: {
          price: 0.025,
          denom: 'basetcro',
        },
      },
      {
        id: 'cronos_777-1',  // id needs to match the chain ID
        account_prefix: 'tcrc',
        default_gas: 600000,
        max_gas: 3600000,
        gas_multiplier: 1.1,
        address_type: {
          derivation: 'ethermint',
          proto_type: {
            pk_type: '/ethermint.crypto.v1.ethsecp256k1.PubKey',
          },
        },
        gas_price: {
          price: 100000000000000,
          denom: 'basetcro',
        },
        extension_options: [
          {
            type: 'ethermint_dynamic_fee',
            value: '500000000000',
          },
        ],
      },
    ],
  },
}
