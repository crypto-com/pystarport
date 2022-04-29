import os
from pathlib import Path

import yaml
from deepdiff import DeepDiff

from pystarport.expansion import expand_jsonnet, expand_yaml


def _cross_check(yaml_config, jsonnet_config):
    assert not DeepDiff(
        yaml_config,
        jsonnet_config,
        ignore_order=True,
    )


def test_expansion():
    bases = []
    cronos_has_dotenvs = []
    cronos_no_dotenvs = []
    cronos_has_posix_no_dotenvs = []
    parent = Path(__file__).parent
    for type in [".yaml", ".jsonnet"]:
        bases.append(parent / ("base" + type))
        cronos_has_dotenvs.append(parent / ("cronos_has_dotenv" + type))
        cronos_no_dotenvs.append(parent / ("cronos_no_dotenv" + type))
        cronos_has_posix_no_dotenvs.append(
            parent / ("cronos_has_posix_no_dotenv" + type)
        )

    baseConfig = yaml.safe_load(open(bases[0]))
    # `expand_yaml` is backward compatible, not expanded, and no diff
    yaml_config = expand_yaml(cronos_no_dotenvs[0], None)
    jsonnet_config = expand_jsonnet(cronos_no_dotenvs[1], None)
    assert baseConfig == yaml_config
    _cross_check(yaml_config, jsonnet_config)

    # `expand_yaml` is expanded but no diff
    yaml_config = expand_yaml(cronos_has_dotenvs[0], None)
    jsonnet_config = expand_jsonnet(cronos_has_dotenvs[1], None)
    assert not DeepDiff(
        baseConfig,
        yaml_config,
        ignore_order=True,
    )
    _cross_check(yaml_config, jsonnet_config)

    # overriding dotenv with relative path is expanded and has diff)
    dotenv = "dotenv1"
    yaml_config = expand_yaml(cronos_has_dotenvs[0], dotenv)
    jsonnet_config = expand_jsonnet(cronos_has_dotenvs[1], dotenv)
    assert DeepDiff(
        baseConfig,
        yaml_config,
        ignore_order=True,
    ) == {
        "values_changed": {
            "root['cronos_777-1']['validators'][0]['mnemonic']": {
                "new_value": "good",
                "old_value": "visit craft resemble online window solution west chuckle "
                "music diesel vital settle comic tribe project blame bulb armed flower "
                "region sausage mercy arrive release",
            }
        }
    }
    _cross_check(yaml_config, jsonnet_config)

    # overriding dotenv with absolute path is expanded and has diff
    dotenv = os.path.abspath("test_expansion/dotenv1")
    yaml_config = expand_yaml(cronos_has_dotenvs[0], dotenv)
    jsonnet_config = expand_jsonnet(cronos_has_dotenvs[1], dotenv)
    assert DeepDiff(
        baseConfig,
        yaml_config,
        ignore_order=True,
    ) == {
        "values_changed": {
            "root['cronos_777-1']['validators'][0]['mnemonic']": {
                "new_value": "good",
                "old_value": "visit craft resemble online window solution west chuckle "
                "music diesel vital settle comic tribe project blame bulb armed flower "
                "region sausage mercy arrive release",
            }
        }
    }
    _cross_check(yaml_config, jsonnet_config)

    # overriding dotenv with absolute path is expanded and no diff
    dotenv = os.path.abspath("test_expansion/dotenv")
    yaml_config = expand_yaml(cronos_has_posix_no_dotenvs[0], dotenv)
    jsonnet_config = expand_jsonnet(cronos_has_posix_no_dotenvs[1], dotenv)
    assert not DeepDiff(
        baseConfig,
        yaml_config,
        ignore_order=True,
    )
    _cross_check(yaml_config, jsonnet_config)
