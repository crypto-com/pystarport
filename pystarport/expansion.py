from pathlib import Path
from typing import Any, Mapping, Optional, Text

import yaml
from dotenv import dotenv_values
from dotenv.variables import parse_variables


def expand_posix_vars(obj: Any, variables: Mapping[Text, Optional[Any]]) -> Any:
    """expand_posix_vars recursively expands POSIX values in an object.

    Args:
        obj (any): object in which to interpolate variables.
        variables (dict): dictionary that maps variable names to their value
    """
    if isinstance(obj, (dict,)):
        for key, val in obj.items():
            obj[key] = expand_posix_vars(val, variables)
    elif isinstance(obj, (list,)):
        for index in range(len(obj)):
            obj[index] = expand_posix_vars(obj[index], variables)
    elif isinstance(obj, (str,)):
        obj = _expand(obj, variables)
    return obj


def _expand(value, variables):
    """_expand does POSIX-style variable expansion

    This is adapted from python-dotenv, specifically here:

    https://github.com/theskumar/python-dotenv/commit/17dba65244c1d4d10f591fe37c924bd2c6fd1cfc

    We need this layer here so we can explicitly pass in variables;
    python-dotenv assumes you want to use os.environ.
    """

    if not isinstance(value, (str,)):
        return value
    atoms = parse_variables(value)
    return "".join([str(atom.resolve(variables)) for atom in atoms])


def expand_yaml(config_path, dotenv_from_param):
    config = yaml.safe_load(open(config_path))
    dotenv_from_config = config.pop("dotenv", {})
    merged = {}
    parent = Path(config_path).parent
    for d in [dotenv_from_config, dotenv_from_param]:
        if d not in (None, '', {}):
            env_path = parent.joinpath(d)
            if not env_path.is_file():
                raise ValueError(
                    f"Dotenv specified in config but not found at path: {env_path}"
                )
            merged = {
                **merged,
                **dotenv_values(env_path),
            }
    if merged is not {}:
        config = expand_posix_vars(config, merged)
    return config
