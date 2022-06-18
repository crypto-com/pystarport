local config = import './base.jsonnet';
local Utils = import 'utils.jsonnet';

config {
  'cronos_777-1'+: {
    validators: Utils.validators([
      '${VALIDATOR1_MNEMONIC}',
      '${VALIDATOR2_MNEMONIC}',
    ]),
    accounts: Utils.accounts([{
      name: 'community',
      coins: '10000000000000000000000basetcro',
      mnemonic: '${COMMUNITY_MNEMONIC}',
    }, {
      name: 'signer1',
      coins: '20000000000000000000000basetcro',
      mnemonic: '${SIGNER1_MNEMONIC}',
    }, {
      name: 'signer2',
      coins: '30000000000000000000000basetcro',
      mnemonic: '${SIGNER2_MNEMONIC}',
    }]),
    genesis+: {
      app_state+: {
        cronos: {
          params: {
            cronos_admin: '${CRONOS_ADMIN}',
            enable_auto_deployment: true,
            ibc_cro_denom: '${IBC_CRO_DENOM}',
          },
        },
      },
    },
  },
}
