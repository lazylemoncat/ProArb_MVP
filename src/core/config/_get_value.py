import os
from typing import Any, Mapping


class Miss_env_exception(Exception):
    """
    缺少环境变量的自定义异常
    """
    def __init__(self, key: str, *args: object) -> None:
        self.key = key
        self.message = f"Environment variable '{key}' is missing."
        super().__init__(self.message, *args)

class Miss_key_exception(Exception):
    """
    字典缺少键的自定义异常
    """
    def __init__(self, key: str):
        self.key = key
        self.message = f"Key '{key}' is missing."
        super().__init__(self.message)

def get_value_from_env(key: str) -> str | bool:
    """
    从环境变量中获取值,解析字符串返回字符串或布尔值
    
    Args:
        key: 指定要获取的环境变量的名
    
    Returns:
        若字符串小写为 true 或 false, 则返回布尔值, 否则返回获取的值的字符串形式
    
    Raises:
        Miss_env_exception: 没有该环境变量
    """
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
    """
    从字典中键对应的值

    Args:
        config: 传入的字典对象
        key: 要获取的键
    
    Returns:
        字典中键对应的值

    Raises:
        Miss_key_exception: 字典对象中没有该键
    """
    if key not in config:
        raise Miss_key_exception(key)
    return config[key]

def parse_bool(
        value: str, 
        true_bools: tuple[str, ...] = ("true", "1", "yes", "y", "on"),
        false_bools: tuple[str, ...] = ("false", "0", "no", "n", "off")
    ) -> bool:
    """
    从字符串中解析是否为布尔值

    Atgs:
        value: 要解析的字符串
        true_bools: 判定为 True 的字符串元组
        false_bools: 判定为 False 的字符串元组

    returns:
        True | False
    
    Raises:
        ValueError: 字符串不被判定为 True 或 False
    """
    if isinstance(value, bool):
        return value

    value = value.strip().lower()

    if value in true_bools:
        return True
    elif value in false_bools:
        return False

    raise ValueError(f"Invalid boolean value: {value}")