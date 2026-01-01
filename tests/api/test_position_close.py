"""
测试 /api/close 端点
"""
import pytest
from fastapi.testclient import TestClient
import pandas as pd
from pathlib import Path

from src.api_server import app


@pytest.fixture
def test_positions_csv(tmp_path):
    """创建测试用的 positions.csv"""
    csv_path = tmp_path / "positions.csv"
    test_data = {
        'signal_id': ['sig_001', 'sig_002', 'sig_003', 'sig_004', 'sig_005'],
        'order_id': ['order_001', 'order_002', 'order_003', 'order_004', 'order_005'],
        'timestamp': ['2026-01-01T10:00:00Z'] * 5,
        'market_title': ['Market 1', 'Market 2', 'Market 3', 'Market 4', 'Market 5'],
        'status': ['OPEN', 'CLOSE', 'close', 'OPEN', 'CLOSE'],  # 测试大小写
        'action': ['buy'] * 5,
        'amount_usd': [200.0, 150.0, 100.0, 250.0, 180.0],
        'days_to_expiry': [14.5, 9.2, 11.3, 19.1, 7.5],
        'pm_data': ['{}'] * 5,
        'dr_data': ['{}'] * 5,
    }
    df = pd.DataFrame(test_data)
    df.to_csv(csv_path, index=False)
    return csv_path


def test_get_all_positions():
    """测试获取所有仓位"""
    client = TestClient(app)
    response = client.get("/api/position")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_get_closed_positions():
    """测试获取已关闭的仓位"""
    client = TestClient(app)
    response = client.get("/api/close")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)

    # 验证所有返回的仓位状态都是 CLOSE
    for position in data:
        assert position['status'] == 'CLOSE'


def test_closed_positions_count():
    """测试关闭仓位的数量"""
    # 读取实际的 CSV 文件
    csv_path = Path("./data/positions.csv")
    if csv_path.exists():
        df = pd.read_csv(csv_path)
        expected_close_count = len(df[df['status'].str.upper() == 'CLOSE'])

        client = TestClient(app)
        response = client.get("/api/close")
        assert response.status_code == 200
        data = response.json()

        assert len(data) == expected_close_count


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
