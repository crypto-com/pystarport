import os
from pathlib import Path

import yaml
from deepdiff import DeepDiff

from pystarport.expansion import expand_yaml


def test_expansion():
    parent = Path(__file__).parent
    base = parent / "base.yaml"
    cronos_has_dotenv = parent / "cronos_has_dotenv.yaml"
    cronos_no_dotenv = parent / "cronos_no_dotenv.yaml"
    cronos_has_posix_no_dotenv = parent / "cronos_has_posix_no_dotenv.yaml"

    baseConfig = yaml.safe_load(open(base))
    # `expand_yaml` is backward compatible, not expanded, and no diff
    assert baseConfig == expand_yaml(cronos_no_dotenv, None)

    # `expand_yaml` is expanded but no diff
    assert not DeepDiff(
        baseConfig,
        expand_yaml(cronos_has_dotenv, None),
        ignore_order=True,
    )

    # overriding dotenv with relative path is expanded and has diff)
    assert DeepDiff(
        baseConfig,
        expand_yaml(cronos_has_dotenv, "dotenv1"),
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

    # overriding dotenv with absolute path is expanded and has diff
    assert DeepDiff(
        baseConfig,
        expand_yaml(cronos_has_dotenv, os.path.abspath("test_expansion/dotenv1")),
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

    # overriding dotenv with absolute path is expanded and no diff
    assert not DeepDiff(
        baseConfig,
        expand_yaml(
            cronos_has_posix_no_dotenv, os.path.abspath("test_expansion/dotenv")
        ),
        ignore_order=True,
    )
