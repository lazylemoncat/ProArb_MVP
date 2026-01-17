import pytest

from src.utils.config_loader._get_value import (
    Miss_env_exception,
    Miss_key_exception,
    get_value_from_dict,
    get_value_from_env,
    parse_bool,
)


def test_env_not_exist(monkeypatch):
    monkeypatch.delenv("TEST_KEY", raising=False)

    with pytest.raises(Miss_env_exception):
        get_value_from_env("TEST_KEY")

def test_env_true(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "  TrUe ")

    result = get_value_from_env("TEST_KEY")

    assert result is True

def test_env_false(monkeypatch):
    monkeypatch.setenv("TEST_KEY", " false  ")

    result = get_value_from_env("TEST_KEY")

    assert result is False

def test_env_string(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "hello_world")

    result = get_value_from_env("TEST_KEY")

    assert result == "hello_world"

@pytest.mark.parametrize(
    "env_value, expected",
    [
        ("true", True),
        ("TRUE", True),
        (" false ", False),
        ("abc", "abc"),
    ],
)
def test_env_values(monkeypatch, env_value, expected):
    monkeypatch.setenv("TEST_KEY", env_value)

    assert get_value_from_env("TEST_KEY") == expected

def test_key_not_exist():
    config = {"a": 1, "b": 2}

    with pytest.raises(Miss_key_exception):
        get_value_from_dict(config, "c")

def test_key_exist():
    config = {"a": 1, "b": 2}

    result = get_value_from_dict(config, "a")

    assert result == 1

@pytest.mark.parametrize(
    "config, key, expected",
    [
        ({"a": 1}, "a", 1),
        ({"b": "text"}, "b", "text"),
        ({"c": True}, "c", True),
        ({"d": None}, "d", None),
        ({"e": [1, 2]}, "e", [1, 2]),
    ],
)
def test_value_types(config, key, expected):
    assert get_value_from_dict(config, key) == expected

@pytest.mark.parametrize(
    "value",
    ["true", "TRUE", " True ", "1", "yes", "y", "on"],
)
def test_parse_bool_true_values(value):
    assert parse_bool(value) is True

@pytest.mark.parametrize(
    "value",
    ["false", "FALSE", " False ", "0", "no", "n", "off"],
)
def test_parse_bool_false_values(value):
    assert parse_bool(value) is False

@pytest.mark.parametrize(
    "value",
    ["", " ", "2", "maybe", "enable", "disable", "null"],
)
def test_parse_bool_invalid_values(value):
    with pytest.raises(ValueError):
        parse_bool(value)
