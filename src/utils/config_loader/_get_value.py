import os
from typing import Any, Dict, Mapping

class Miss_env_exception(Exception):
    def __init__(self, key: str, *args: object) -> None:
        self.key = key
        self.message = f"Environment variable '{key}' is missing."
        super().__init__(self.message, *args)

class Miss_key_exception(Exception):
    def __init__(self, key: str):
        self.key = key
        self.message = f"Key '{key}' is missing."
        super().__init__(self.message)

def get_value_from_env(key: str) -> str | bool:
    value = os.getenv(key)
    if value is None:
        raise Miss_env_exception(key)
    
    value_lower = value.strip().lower()
    if value_lower == "true":
        return True
    elif value_lower == "false":
        return False
    else:
        return value
    
def get_value_from_dict(config: Mapping[str, Any], key: str) -> Any:
    if key not in config:
        raise Miss_key_exception(key)
    return config[key]

def parse_bool(value: str) -> bool:
    if isinstance(value, bool):
        return value

    value = value.strip().lower()

    if value in ("true", "1", "yes", "y", "on"):
        return True
    if value in ("false", "0", "no", "n", "off"):
        return False

    raise ValueError(f"Invalid boolean value: {value}")