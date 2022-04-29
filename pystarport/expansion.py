import json
import os
from pathlib import Path
from typing import Any, Mapping, Optional, Text

import _jsonnet
import jsonmerge
import yaml
from dotenv import dotenv_values, load_dotenv
from dotenv.variables import parse_variables
from yamlinclude import YamlIncludeConstructor


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


def expand(config, dotenv, path):
    config_vars = dict(os.environ)  # load system env

    if dotenv is not None:
        if "dotenv" in config:
            _ = config.pop("dotenv", {})  # remove dotenv field if exists
    elif "dotenv" in config:
        dotenv = config.pop("dotenv", {})  # pop dotenv field if exists

    if dotenv:
        if not isinstance(dotenv, str):
            raise ValueError(f"Invalid value passed to dotenv: {dotenv}")
        env_path = path.parent / dotenv
        if not env_path.is_file():
            raise ValueError(
                f"Dotenv specified in config but not found at path: {env_path}"
            )
        config_vars.update(dotenv_values(dotenv_path=env_path))  # type: ignore
        load_dotenv(dotenv_path=env_path)

    return expand_posix_vars(config, config_vars)


def expand_yaml(config_path, dotenv):
    path = Path(config_path)
    YamlIncludeConstructor.add_to_loader_class(
        loader_class=yaml.FullLoader,
        base_dir=path.parent,
    )

    with open(path) as f:
        config = yaml.load(f, Loader=yaml.FullLoader)

    include = config.pop("include", {})
    if include:
        config = jsonmerge.merge(include, config)

    config = expand(config, dotenv, path)
    return config


def expand_jsonnet(config_path, dotenv):
    path = Path(config_path)
    config = json.loads(_jsonnet.evaluate_file(str(config_path)))
    config = expand(config, dotenv, path)
    return config
