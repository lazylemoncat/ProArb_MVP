"""
测试 Position 端点返回的嵌套结构
"""
import pytest
from fastapi.testclient import TestClient

from src.api_server import app


def test_position_response_structure():
    """测试 position 端点返回的数据结构"""
    client = TestClient(app)
    response = client.get("/api/position")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)

    if len(data) > 0:
        position = data[0]

        # A. 基础索引
        assert "signal_id" in position
        assert "order_id" in position
        assert "timestamp" in position
        assert "market_id" in position

        # B. 交易核心
        assert "status" in position
        assert position["status"] in ["OPEN", "CLOSE"]
        assert "action" in position
        assert position["action"] in ["buy", "sell"]
        assert "amount_usd" in position
        assert "days_to_expiry" in position

        # C. PM 数据
        assert "pm_data" in position
        pm_data = position["pm_data"]
        assert "shares" in pm_data
        assert "yes_avg_price_t0" in pm_data
        assert "no_avg_price_t0" in pm_data
        assert "slippage_usd" in pm_data
        assert "yes_price" in pm_data
        assert "no_price" in pm_data

        # D. DR 数据
        assert "dr_data" in position
        dr_data = position["dr_data"]
        assert "index_price_t0" in dr_data
        assert "contracts" in dr_data
        assert "fee_usd" in dr_data

        # K1 数据
        assert "k1" in dr_data
        k1 = dr_data["k1"]
        assert "instrument" in k1
        assert "price_t0" in k1
        assert "iv" in k1

        # K2 数据
        assert "k2" in dr_data
        k2 = dr_data["k2"]
        assert "instrument" in k2
        assert "price_t0" in k2
        assert "iv" in k2

        # Risk 数据
        assert "risk" in dr_data
        risk = dr_data["risk"]
        assert "iv_t0" in risk
        assert "prob_t0" in risk
        assert "iv_floor" in risk
        assert "iv_ceiling" in risk


def test_close_position_response_structure():
    """测试 close 端点返回的数据结构"""
    client = TestClient(app)
    response = client.get("/api/close")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)

    # 验证所有返回的仓位都是 CLOSE 状态
    for position in data:
        assert position["status"] == "CLOSE"

        # 验证结构完整性（至少检查嵌套对象存在）
        assert "pm_data" in position
        assert "dr_data" in position
        assert "k1" in position["dr_data"]
        assert "k2" in position["dr_data"]
        assert "risk" in position["dr_data"]


def test_position_data_types():
    """测试数据类型正确性"""
    client = TestClient(app)
    response = client.get("/api/position")

    assert response.status_code == 200
    data = response.json()

    if len(data) > 0:
        position = data[0]

        # 数值类型检查
        assert isinstance(position["amount_usd"], (int, float))
        assert isinstance(position["days_to_expiry"], (int, float))

        # PM 数据类型
        pm = position["pm_data"]
        assert isinstance(pm["shares"], (int, float))
        assert isinstance(pm["yes_avg_price_t0"], (int, float))
        assert isinstance(pm["slippage_usd"], (int, float))

        # DR 数据类型
        dr = position["dr_data"]
        assert isinstance(dr["index_price_t0"], (int, float))
        assert isinstance(dr["contracts"], (int, float))
        assert isinstance(dr["fee_usd"], (int, float))

        # K1/K2 数据类型
        assert isinstance(dr["k1"]["price_t0"], (int, float))
        assert isinstance(dr["k1"]["iv"], (int, float))
        assert isinstance(dr["k2"]["price_t0"], (int, float))
        assert isinstance(dr["k2"]["iv"], (int, float))

        # Risk 数据类型
        assert isinstance(dr["risk"]["iv_t0"], (int, float))
        assert isinstance(dr["risk"]["prob_t0"], (int, float))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
