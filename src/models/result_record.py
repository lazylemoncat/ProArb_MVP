from dataclasses import dataclass, asdict
from typing import Dict, Any

@dataclass
class ResultRecord:
    """
    套利结果记录(PRD字段 + 策略拆分)
    - EV: 两种策略中较优者 max(ev_yes, ev_no)，用于兼容旧报表
    - EV_IM_ratio: EV / IM(同样按较优者计算)
    """
    market_title: str
    timestamp: str
    investment: float
    spot: float
    poly_yes_price: float
    deribit_prob: float

    expected_pnl_yes: float
    total_costs: float
    EV: float
    IM: float
    EV_IM_ratio: float

    # 分策略输出
    ev_yes: float   # 策略一（做多YES）的EV
    ev_no: float    # 策略二（做空YES/做多NO）的EV

    suggest1: str
    suggest2: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
