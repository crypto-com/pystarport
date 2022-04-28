local config = import './default.jsonnet';
local Utils = import 'utils.jsonnet';

std.manifestYamlDoc(config {
  'cronos_777-1'+: {
    validators: [
      Utils.validator('${VALIDATOR1_MNEMONIC}'),
      Utils.validator('${VALIDATOR2_MNEMONIC}'),
    ],
    accounts: [
      Utils.account(
        'community',
        '10000000000000000000000basetcro',
        '${COMMUNITY_MNEMONIC}',
      ),
      Utils.account(
        'signer1',
        '20000000000000000000000basetcro',
        '${SIGNER1_MNEMONIC}',
      ),
      Utils.account(
        'signer2',
        '30000000000000000000000basetcro',
        '${SIGNER2_MNEMONIC}',
      ),
    ],
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
}, true, false)
