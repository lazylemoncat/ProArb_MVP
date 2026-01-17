from src.utils.loadAllConfig.env_loader import Env_config, load_env_config, parse_env_config

def test_parse_env_config():
    env = {
        "deribit_client_secret": "secret",
        "deribit_user_id": "user",
        "deribit_client_id": "client",
        "polymarket_secret": "poly",
        "POLYMARKET_PROXY_ADDRESS": "proxy",
        "SIGNER_URL": "url",
        "SIGNING_TOKEN": "token",
        "TELEGRAM_ENABLED": "True",
        "TELEGRAM_ALART_ENABLED": "False",
        "TELEGRAM_TRADING_ENABLED": "True",
        "TELEGRAM_BOT_TOKEN_ALERT": "a",
        "TELEGRAM_BOT_TOKEN_TRADING": "b",
        "TELEGRAM_CHAT_ID": "1",
        "TELEGRAM_TOKEN": "t",
        "MAX_RETRIES": "3",
        "RETRY_DELAY_SECONDS": "5",
        "RETRY_BACKOFF": "2",
        "TELEGRAM_MAX_MSG_PER_SEC": "10",
    }

    cfg = parse_env_config(env)

    assert cfg.MAX_RETRIES == 3
    assert cfg.TELEGRAM_ENABLED is True
    assert cfg.TELEGRAM_ALART_ENABLED is False
    assert cfg.RETRY_BACKOFF == 2