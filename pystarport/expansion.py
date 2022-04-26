import os
from pathlib import Path
from typing import Any, Mapping, Optional, Text

import yaml
from dotenv import dotenv_values, load_dotenv
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


def expand_yaml(config_path, dotenv):
    config = yaml.safe_load(open(config_path))

    def expand(dotenv):
        if not isinstance(dotenv, str):
            raise ValueError(f"Invalid value passed to dotenv: {dotenv}")
        config_vars = dict(os.environ)  # load system env
        env_path = Path(config_path).parent.joinpath(dotenv)
        if not env_path.is_file():
            raise ValueError(
                f"Dotenv specified in config but not found at path: {env_path}"
            )
        config_vars.update(dotenv_values(dotenv_path=env_path))  # type: ignore
        load_dotenv(dotenv_path=env_path)
        return expand_posix_vars(config, config_vars)

    if dotenv is not None:
        if "dotenv" in config:
            _ = config.pop("dotenv", {})  # remove dotenv field if exists
        dotenv_path = dotenv
        config = expand(dotenv_path)
    elif "dotenv" in config:
        dotenv_path = config.pop("dotenv", {})  # pop dotenv field if exists
        config = expand(dotenv_path)

    return config
