# src/strategy/record_models.py

from dataclasses import dataclass
from datetime import datetime
from typing import Dict

from .cost_model import CostParams
from .expected_value import EVInputs


# ================================
# 7. 记录结构（用于日志/数据库）
# ================================
@dataclass
class OpeningRecord:
    timestamp: datetime
    ev_inputs: EVInputs
    ev_result: Dict[str, float]
    cost_params: CostParams

@dataclass
class ReestimateRecord:
    timestamp: datetime
    realized_pnl_to_t: float
    reestimated_ev: float