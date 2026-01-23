from src.core.config import load_all_configs, Env_config, Config, Trading_config

def test_dataloader():
    env_config, config, tradinf_config = load_all_configs()
    assert isinstance(env_config, Env_config)
    assert isinstance(config, Config)
    assert isinstance(tradinf_config, Trading_config)