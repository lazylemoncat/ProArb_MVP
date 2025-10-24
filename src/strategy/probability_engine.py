# src/strategy/probability_engine.py

import math
from typing import Dict


def _norm_cdf(x: float) -> float:
    """标准正态分布Φ(x);用erf实现,避免scipy依赖。"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_probability_gt(S: float, K: float, T: float, sigma: float, r: float) -> float:
    """P(S_T > K) = N(d2)
    S: 现货价格
    K: 行权价
    T: 剩余年化时间 (年)
    sigma: 年化隐含波动率 (例如 0.6)
    r: 无风险利率 (例如 0.05)
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        # 边界：到期或无波动/无效参数
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return _norm_cdf(d2)


def interval_probabilities(
    S: float,
    K1: float,
    K_poly: float,
    K2: float,
    T: float,
    sigma: float,
    r: float,
) -> Dict[str, float]:
    """返回四个区间概率：
    1) S_T < K1
    2) K1 ≤ S_T < K_poly
    3) K_poly ≤ S_T < K2
    4) S_T ≥ K2
    引用: P_interval 按 N(d2) 差值计算。
    """
    # 使用 N(d2) 计算 P(S_T >= K)
    p_ge_K1 = bs_probability_gt(S, K1, T, sigma, r)  # N(d2@K1)
    p_ge_Kp = bs_probability_gt(S, K_poly, T, sigma, r)  # N(d2@K_poly)
    p_ge_K2 = bs_probability_gt(S, K2, T, sigma, r)  # N(d2@K2)

    p_lt_K1 = 1.0 - p_ge_K1
    p_K1_to_Kp = max(0.0, p_ge_K1 - p_ge_Kp)
    p_Kp_to_K2 = max(0.0, p_ge_Kp - p_ge_K2)
    p_ge_K2 = p_ge_K2

    # 数值稳定处理（保证和为1）
    probs = [p_lt_K1, p_K1_to_Kp, p_Kp_to_K2, p_ge_K2]
    total = sum(probs)
    if total > 0:
        probs = [max(0.0, p / total) for p in probs]
    return {
        "lt_K1": probs[0],
        "K1_to_Kp": probs[1],
        "Kp_to_K2": probs[2],
        "ge_K2": probs[3],
    }