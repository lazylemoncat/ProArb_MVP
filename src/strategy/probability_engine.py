import math
from typing import Dict


def _norm_cdf(x: float) -> float:
    """标准正态分布Φ(x);用erf实现,避免scipy依赖。"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_probability_gt(S: float, K: float, T: float, sigma: float, r: float = 0.05) -> float:
    """
    Black-Scholes 风险中性概率 P(S_T > K)

    参数:
        S: 当前标的价格
        K: 行权价
        T: 剩余到期时间（单位：年）
        sigma: 隐含波动率(例如 0.7)
        r: 无风险利率(默认 5%)
    """
    # 参数检查与边界处理
    if S <= 0 or K <= 0:
        raise ValueError("S 和 K 必须为正数")

    if T <= 0:
        # T 近似为 0 时返回稳定值，防止跳变
        if S > K:
            return 0.99999
        elif S < K:
            return 0.00001
        else:
            return 0.5

    if sigma <= 0:
        return 1.0 if S > K else 0.0

    # Black-Scholes d2 计算
    d2 = (math.log(S / K) + (r - 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
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