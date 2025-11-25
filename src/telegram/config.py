"""
Telegram bot configuration management for ProArb_MVP.

Handles configuration loading, validation, and environment variable management.
"""

import os
import yaml
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AlertThresholds:
    """Configuration for alert thresholds."""
    ev_threshold: float = 100.0  # USD
    probability_diff_threshold: float = 0.05  # 5%
    data_delay_threshold: int = 30  # seconds
    cooldown_minutes: int = 5  # minutes between similar alerts


@dataclass
class RateLimiting:
    """Configuration for rate limiting."""
    max_messages_per_hour: int = 20
    max_alerts_per_minute: int = 2
    system_alerts_enabled: bool = True


@dataclass
class SummaryConfig:
    """Configuration for periodic summaries."""
    enabled: bool = True
    interval_hours: int = 24
    min_opportunities: int = 5


@dataclass
class TelegramConfig:
    """Main Telegram bot configuration."""

    # Bot settings
    enabled: bool = False
    bot_token: Optional[str] = None
    chat_ids: List[str] = field(default_factory=list)

    # Sub-configurations
    alerts: AlertThresholds = field(default_factory=AlertThresholds)
    rate_limiting: RateLimiting = field(default_factory=RateLimiting)
    summary: SummaryConfig = field(default_factory=SummaryConfig)

    # Localization
    language: str = "zh-CN"  # zh-CN or en-US

    def __post_init__(self):
        """Post-initialization validation and environment loading."""
        self._load_from_environment()
        self._validate()

    def _load_from_environment(self):
        """Load configuration from environment variables."""
        # Bot token from environment (highest priority)
        env_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if env_token:
            self.bot_token = env_token

        # Chat IDs from environment (comma-separated)
        env_chat_ids = os.getenv("TELEGRAM_CHAT_IDS")
        if env_chat_ids:
            self.chat_ids = [chat_id.strip() for chat_id in env_chat_ids.split(",")]

        # Enable/disable from environment
        env_enabled = os.getenv("TELEGRAM_ENABLED")
        if env_enabled is not None:
            self.enabled = env_enabled.lower() in ("true", "1", "yes")

    def _validate(self):
        """Validate configuration settings."""
        if self.enabled and not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required when telegram is enabled")

        if self.enabled and not self.chat_ids:
            raise ValueError("TELEGRAM_CHAT_IDS is required when telegram is enabled")

        # Validate thresholds
        if self.alerts.ev_threshold < 0:
            raise ValueError("EV threshold must be non-negative")

        if not (0 <= self.alerts.probability_diff_threshold <= 1):
            raise ValueError("Probability difference threshold must be between 0 and 1")

        if self.alerts.data_delay_threshold < 0:
            raise ValueError("Data delay threshold must be non-negative")

        if self.alerts.cooldown_minutes < 0:
            raise ValueError("Cooldown minutes must be non-negative")

    @classmethod
    def from_file(cls, config_path: str) -> "TelegramConfig":
        """Load configuration from YAML file."""
        config_file = Path(config_path)

        if not config_file.exists():
            # Return default configuration if file doesn't exist
            return cls()

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)

            telegram_config = config_data.get('telegram', {})

            # Extract nested configurations
            alerts_data = telegram_config.pop('alerts', {})
            rate_limiting_data = telegram_config.pop('rate_limiting', {})
            summary_data = telegram_config.pop('summary', {})

            # Create configuration instances
            alerts = AlertThresholds(**alerts_data)
            rate_limiting = RateLimiting(**rate_limiting_data)
            summary = SummaryConfig(**summary_data)

            # Create main config
            return cls(
                alerts=alerts,
                rate_limiting=rate_limiting,
                summary=summary,
                **telegram_config
            )

        except Exception as e:
            print(f"Error loading telegram config from {config_path}: {e}")
            return cls()

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "TelegramConfig":
        """Load configuration from dictionary."""
        # Extract nested configurations
        alerts_data = config_dict.pop('alerts', {})
        rate_limiting_data = config_dict.pop('rate_limiting', {})
        summary_data = config_dict.pop('summary', {})

        # Create configuration instances
        alerts = AlertThresholds(**alerts_data)
        rate_limiting = RateLimiting(**rate_limiting_data)
        summary = SummaryConfig(**summary_data)

        return cls(
            alerts=alerts,
            rate_limiting=rate_limiting,
            summary=summary,
            **config_dict
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            'enabled': self.enabled,
            'bot_token': self.bot_token,
            'chat_ids': self.chat_ids,
            'alerts': {
                'ev_threshold': self.alerts.ev_threshold,
                'probability_diff_threshold': self.alerts.probability_diff_threshold,
                'data_delay_threshold': self.alerts.data_delay_threshold,
                'cooldown_minutes': self.alerts.cooldown_minutes
            },
            'rate_limiting': {
                'max_messages_per_hour': self.rate_limiting.max_messages_per_hour,
                'max_alerts_per_minute': self.rate_limiting.max_alerts_per_minute,
                'system_alerts_enabled': self.rate_limiting.system_alerts_enabled
            },
            'summary': {
                'enabled': self.summary.enabled,
                'interval_hours': self.summary.interval_hours,
                'min_opportunities': self.summary.min_opportunities
            },
            'language': self.language
        }

    def is_enabled(self) -> bool:
        """Check if Telegram notifications are enabled."""
        return self.enabled and self.bot_token is not None and len(self.chat_ids) > 0

    def get_effective_chat_ids(self) -> List[str]:
        """Get list of effective chat IDs (filtered for validity)."""
        # Basic validation - remove empty strings
        valid_chat_ids = [chat_id for chat_id in self.chat_ids if chat_id.strip()]

        # You could add more sophisticated validation here
        # (e.g., checking for numeric IDs, format validation, etc.)

        return valid_chat_ids

    def should_send_alert(self, ev_value: float, probability_diff: float, data_delay: int) -> bool:
        """Check if an alert should be sent based on thresholds."""
        if not self.is_enabled():
            return False

        # Check EV threshold
        if abs(ev_value) >= self.alerts.ev_threshold:
            return True

        # Check probability difference threshold
        if abs(probability_diff) >= self.alerts.probability_diff_threshold:
            return True

        # Check data delay threshold
        if data_delay >= self.alerts.data_delay_threshold:
            return True

        return False

    def should_send_system_alert(self) -> bool:
        """Check if system alerts are enabled."""
        return self.is_enabled() and self.rate_limiting.system_alerts_enabled

    def should_send_summary(self, opportunity_count: int, hours_since_last: int) -> bool:
        """Check if summary should be sent."""
        if not self.is_enabled() or not self.summary.enabled:
            return False

        return (opportunity_count >= self.summary.min_opportunities or
                hours_since_last >= self.summary.interval_hours)


# Default configuration instance
DEFAULT_CONFIG = TelegramConfig()

# Configuration file path (relative to project root)
DEFAULT_CONFIG_PATH = "config.yaml"