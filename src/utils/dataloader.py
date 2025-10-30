import yaml

def load_manual_data(config_path: str="config.yaml"):
    """
    从配置文件加载输入数据
    Args:
        config_path: 配置文件地址
    """
    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return data