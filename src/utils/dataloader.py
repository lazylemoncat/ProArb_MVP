# ================= data_loader.py =================
import yaml

def load_manual_data(config_path="config.yaml"):
    """从配置文件加载输入数据"""
    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return data


def fetch_single_market_data(market_id):
    """示例API调用: 模拟返回市场数据"""
    # 实际生产中应使用 requests 访问 Polymarket/Deribit API
    dummy = {
        "market_id": market_id,
        "polymarket_yes": 0.12,
        "deribit_spot": 60000,
        "deribit_k1": 113000,
        "deribit_k2": 115000,
        "deribit_k1_price": 0.015,
        "deribit_k2_price": 0.008,
    }
    return dummy