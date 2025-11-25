"""
Message formatter for Telegram notifications in ProArb_MVP.

Handles message formatting, template rendering, and field formatting
according to the specification in docs/message-templates.md.
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import json


@dataclass
class OpportunityData:
    """Data structure for arbitrage opportunity notifications."""
    event_description: str
    ev_value: float
    strategy_number: int
    strategy_description: str
    probability_diff: float
    pm_token_type: str  # "YES" or "NO"
    pm_price: float
    deribit_price: float
    pme_risk: float
    data_delay_seconds: int
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        """Post-initialization setup."""
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


@dataclass
class SystemStatusData:
    """Data structure for system status notifications."""
    status_description: str
    reason: str
    impact: str
    operation: str
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        """Post-initialization setup."""
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


@dataclass
class SummaryData:
    """Data structure for periodic summary notifications."""
    period_hours: int
    total_opportunities: int
    best_ev_value: float
    best_event_description: str
    strategy1_count: int
    strategy2_count: int
    data_quality_percentage: float
    average_delay_seconds: float
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        """Post-initialization setup."""
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


class MessageFormatter:
    """Formats messages for Telegram notifications according to specifications."""

    def __init__(self, language: str = "zh-CN"):
        """Initialize formatter with language settings."""
        self.language = language
        self._load_strings()

    def _load_strings(self):
        """Load localized strings based on language setting."""
        if self.language == "zh-CN":
            self.strings = {
                "opportunity": "套利机会",
                "system_status": "系统状态",
                "data_quality": "数据质量",
                "strategy": "策略",
                "risk": "风险",
                "data_delay": "数据延迟",
                "prob_diff": "概率差",
                "ev_label": "EV",
                "cause": "原因",
                "impact": "影响",
                "operation": "操作",
                "summary": "总结",
                "summary_h": "h总结",
                "total_opportunities": "总机会",
                "best_ev": "最佳 EV",
                "strategy_distribution": "策略分布",
                "data_quality_label": "数据质量",
                "avg_delay": "平均延迟"
            }
        else:
            self.strings = {
                "opportunity": "Arbitrage",
                "system_status": "System Status",
                "data_quality": "Data Quality",
                "strategy": "Strategy",
                "risk": "Risk",
                "data_delay": "Data Delay",
                "prob_diff": "Prob Diff",
                "ev_label": "EV",
                "cause": "Cause",
                "impact": "Impact",
                "operation": "Action",
                "summary": "Summary",
                "summary_h": "h Summary",
                "total_opportunities": "Total Opportunities",
                "best_ev": "Best EV",
                "strategy_distribution": "Strategy Distribution",
                "data_quality_label": "Data Quality",
                "avg_delay": "Avg Delay"
            }

    def format_opportunity_message(self, data: OpportunityData, simplified: bool = False) -> str:
        """Format arbitrage opportunity notification message."""
        # Format timestamp
        timestamp_str = data.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

        # Format main header
        ev_sign = "+" if data.ev_value >= 0 else ""
        header = f"🔴 [{self.strings['opportunity']}] {data.event_description} | {self.strings['ev_label']}: {ev_sign}${data.ev_value:.2f}"

        # Format strategy line
        prob_sign = "+" if data.probability_diff >= 0 else ""
        strategy_line = f"📊 {self.strings['strategy']}{data.strategy_number}: {data.strategy_description} | {self.strings['prob_diff']}: {prob_sign}{data.probability_diff:.1%}"

        # Format price line
        price_line = f"💰 PM-{data.pm_token_type} ${data.pm_price:.2f} | Deribit ${data.deribit_price:.2f}"

        if simplified:
            # Simplified format for low-quality data
            message_lines = [
                header,
                strategy_line,
                price_line,
                f"⏰ {timestamp_str}"
            ]
        else:
            # Full format
            risk_line = f"⚠️ {self.strings['risk']}: PME ${data.pme_risk:.0f} | {self.strings['data_delay']}: {data.data_delay_seconds}s"
            message_lines = [
                header,
                strategy_line,
                price_line,
                risk_line,
                f"⏰ {timestamp_str}"
            ]

        return "\n".join(message_lines)

    def format_system_status_message(self, data: SystemStatusData) -> str:
        """Format system status notification message."""
        timestamp_str = data.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

        message_lines = [
            f"🟡 [{self.strings['system_status']}] {data.status_description}",
            f"❌ {self.strings['cause']}: {data.reason}",
            f"📊 {self.strings['impact']}: {data.impact}",
            f"🔄 {self.strings['operation']}: {data.operation}",
            f"⏰ {timestamp_str}"
        ]

        return "\n".join(message_lines)

    def format_data_quality_message(self, status_description: str, details: str, impact: str, suggestion: str) -> str:
        """Format data quality notification message."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        message_lines = [
            f"🟡 [{self.strings['data_quality']}] {status_description}",
            f"📊 详情: {details}",
            f"🔍 {self.strings['impact']}: {impact}",
            f"📈 建议: {suggestion}",
            f"⏰ {timestamp}"
        ]

        return "\n".join(message_lines)

    def format_summary_message(self, data: SummaryData) -> str:
        """Format periodic summary notification message."""
        timestamp_str = data.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

        # Calculate percentages
        total = data.strategy1_count + data.strategy2_count
        if total > 0:
            strategy1_pct = (data.strategy1_count / total) * 100
            strategy2_pct = (data.strategy2_count / total) * 100
        else:
            strategy1_pct = strategy2_pct = 0

        # Format main header
        header = f"📊 [{data.period_hours}{self.strings['summary_h']}] 发现 {data.total_opportunities} 个{self.strings['opportunity']}"

        # Format best opportunity line
        best_ev_sign = "+" if data.best_ev_value >= 0 else ""
        best_line = f"💎 {self.strings['best_ev']}: {best_ev_sign}${data.best_ev_value:.1f} ({data.best_event_description})"

        # Format strategy distribution line
        strategy_line = f"📈 {self.strings['strategy_distribution']}: {self.strings['strategy']}: {data.strategy1_count} ({strategy1_pct:.0f}%) | 策略2: {data.strategy2_count} ({strategy2_pct:.0f}%)"

        # Format data quality line
        quality_line = f"📊 {self.strings['data_quality_label']}: {data.data_quality_percentage:.1f}% | {self.strings['avg_delay']}: {data.average_delay_seconds:.1f}s"

        message_lines = [
            header,
            best_line,
            strategy_line,
            quality_line,
            f"⏰ {timestamp_str}"
        ]

        return "\n".join(message_lines)

    def format_startup_message(self, monitored_markets: List[str], ev_threshold: float, prob_threshold: float) -> str:
        """Format system startup notification message."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        markets_str = ", ".join(monitored_markets)

        message_lines = [
            "🟢 [系统启动] ProArb监控已启动",
            f"📊 监控市场: {markets_str}",
            f"🔍 检测阈值: EV > ${ev_threshold:.0f} | 概率差 > {prob_threshold:.1%}",
            f"⏰ 启动时间: {timestamp}"
        ]

        return "\n".join(message_lines)

    def format_shutdown_message(self, runtime_hours: int, runtime_minutes: int, notifications_sent: int,
                               last_ev: float, last_opportunity_time: str) -> str:
        """Format system shutdown notification message."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        runtime_str = f"{runtime_hours}h {runtime_minutes}m" if runtime_hours > 0 else f"{runtime_minutes}m"
        last_ev_sign = "+" if last_ev >= 0 else ""

        message_lines = [
            "🔵 [系统关闭] ProArb监控正在关闭",
            f"📊 运行时长: {runtime_str} | 发送通知: {notifications_sent}",
            f"📈 最后机会: {last_ev_sign}${last_ev:.2f} ({last_opportunity_time})",
            f"⏰ 关闭时间: {timestamp}"
        ]

        return "\n".join(message_lines)

    def format_json_debug(self, data: Dict[str, Any]) -> str:
        """Format data as JSON for debugging purposes."""
        return f"```json\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```"

    def truncate_message(self, message: str, max_length: int = 4000) -> str:
        """Truncate message to fit within Telegram limits while preserving structure."""
        if len(message) <= max_length:
            return message

        # Try to truncate at line break to preserve structure
        lines = message.split('\n')
        truncated_lines = []
        current_length = 0

        for line in lines:
            if current_length + len(line) + 1 <= max_length - 50:  # Leave room for truncation indicator
                truncated_lines.append(line)
                current_length += len(line) + 1
            else:
                break

        truncated_message = '\n'.join(truncated_lines)
        truncated_message += "\n\n... (message truncated)"

        return truncated_message

    def validate_message_length(self, message: str) -> tuple[bool, int]:
        """Validate message length against Telegram limits."""
        telegram_limit = 4096
        recommended_limit = 400

        is_valid = len(message) <= telegram_limit
        is_recommended = len(message) <= recommended_limit

        return is_valid, len(message)

    def format_number(self, value: float, decimal_places: int = 2) -> str:
        """Format number with appropriate precision and thousand separators."""
        if abs(value) >= 1000000:
            return f"{value/1000000:.{decimal_places}f}M"
        elif abs(value) >= 1000:
            return f"{value/1000:.{decimal_places}f}K"
        else:
            return f"{value:.{decimal_places}f}"

    def format_percentage(self, value: float, decimal_places: int = 1) -> str:
        """Format decimal as percentage."""
        sign = "+" if value >= 0 else ""
        return f"{sign}{value*100:.{decimal_places}f}%"

    def format_duration(self, seconds: int) -> str:
        """Format duration in human-readable format."""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            return f"{minutes}m {remaining_seconds}s" if remaining_seconds > 0 else f"{minutes}m"
        else:
            hours = seconds // 3600
            remaining_minutes = (seconds % 3600) // 60
            return f"{hours}h {remaining_minutes}m" if remaining_minutes > 0 else f"{hours}h"


# Factory function for creating formatter instances
def create_formatter(language: str = "zh-CN") -> MessageFormatter:
    """Create a MessageFormatter instance with the specified language."""
    return MessageFormatter(language)


# Default formatter instance
DEFAULT_FORMATTER = MessageFormatter()