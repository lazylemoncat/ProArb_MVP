"""
Tests for signal_id_generator module.

Validates unified signal_id generation, parsing, and extraction functions.
"""

import pytest
from datetime import datetime, timezone
from src.utils.signal_id_generator import (
    generate_signal_id,
    generate_signal_id_legacy_compat,
    parse_signal_id,
    extract_timestamp_from_signal_id,
    extract_market_id_from_signal_id,
)


class TestGenerateSignalId:
    """Test signal_id generation."""

    def test_generate_signal_id_no_prefix(self):
        """Test signal_id generation without prefix."""
        market_id = "BTC_105000_NO"
        timestamp = datetime(2025, 12, 28, 12, 0, 10, 123456, tzinfo=timezone.utc)

        signal_id = generate_signal_id(market_id=market_id, timestamp=timestamp)

        assert signal_id == "20251228_120010_123456_BTC_105000_NO"

    def test_generate_signal_id_with_prefix(self):
        """Test signal_id generation with SNAP prefix."""
        market_id = "BTC_105000_NO"
        timestamp = datetime(2025, 12, 28, 12, 0, 10, 123456, tzinfo=timezone.utc)

        signal_id = generate_signal_id(
            market_id=market_id,
            timestamp=timestamp,
            prefix="SNAP"
        )

        assert signal_id == "SNAP_20251228_120010_123456_BTC_105000_NO"

    def test_generate_signal_id_default_timestamp(self):
        """Test signal_id generation with default (current) timestamp."""
        market_id = "ETH_3500_YES"

        signal_id = generate_signal_id(market_id=market_id)

        # Should contain market_id
        assert "ETH_3500_YES" in signal_id
        # Should have correct format (no prefix)
        parts = signal_id.split("_")
        assert len(parts) == 5  # YYYYMMDD, HHMMSS, microseconds, ETH, 3500, YES

    def test_generate_signal_id_naive_timestamp(self):
        """Test signal_id generation with naive (non-timezone-aware) timestamp."""
        market_id = "BTC_105000_NO"
        # Naive timestamp (no timezone)
        timestamp = datetime(2025, 12, 28, 12, 0, 10, 123456)

        signal_id = generate_signal_id(market_id=market_id, timestamp=timestamp)

        # Should still work and produce correct format
        assert signal_id == "20251228_120010_123456_BTC_105000_NO"

    def test_generate_signal_id_uniqueness(self):
        """Test that signal_ids with different microseconds are unique."""
        market_id = "BTC_105000_NO"
        timestamp1 = datetime(2025, 12, 28, 12, 0, 10, 123456, tzinfo=timezone.utc)
        timestamp2 = datetime(2025, 12, 28, 12, 0, 10, 654321, tzinfo=timezone.utc)

        signal_id1 = generate_signal_id(market_id=market_id, timestamp=timestamp1)
        signal_id2 = generate_signal_id(market_id=market_id, timestamp=timestamp2)

        assert signal_id1 != signal_id2
        assert "123456" in signal_id1
        assert "654321" in signal_id2


class TestGenerateSignalIdLegacyCompat:
    """Test legacy signal_id generation (without microseconds)."""

    def test_legacy_format(self):
        """Test legacy signal_id format."""
        market_id = "BTC_105000_NO"
        timestamp = datetime(2025, 12, 28, 12, 0, 10, 123456, tzinfo=timezone.utc)

        signal_id = generate_signal_id_legacy_compat(
            market_id=market_id,
            timestamp=timestamp
        )

        # Legacy format does NOT include microseconds
        assert signal_id == "20251228_120010_BTC_105000_NO"


class TestParseSignalId:
    """Test signal_id parsing."""

    def test_parse_signal_id_with_snap_prefix(self):
        """Test parsing signal_id with SNAP prefix."""
        signal_id = "SNAP_20251228_120010_123456_BTC_105000_NO"

        parsed = parse_signal_id(signal_id)

        assert parsed["prefix"] == "SNAP"
        assert parsed["date"] == "20251228"
        assert parsed["time"] == "120010"
        assert parsed["microseconds"] == "123456"
        assert parsed["market_id"] == "BTC_105000_NO"

    def test_parse_signal_id_no_prefix(self):
        """Test parsing signal_id without prefix."""
        signal_id = "20251228_120010_123456_BTC_105000_NO"

        parsed = parse_signal_id(signal_id)

        assert parsed["prefix"] == ""
        assert parsed["date"] == "20251228"
        assert parsed["time"] == "120010"
        assert parsed["microseconds"] == "123456"
        assert parsed["market_id"] == "BTC_105000_NO"

    def test_parse_signal_id_legacy_format(self):
        """Test parsing legacy signal_id (without microseconds)."""
        signal_id = "20251228_120010_BTC_105000_NO"

        parsed = parse_signal_id(signal_id)

        assert parsed["prefix"] == ""
        assert parsed["date"] == "20251228"
        assert parsed["time"] == "120010"
        assert parsed["microseconds"] == ""
        assert parsed["market_id"] == "BTC_105000_NO"

    def test_parse_signal_id_complex_market_id(self):
        """Test parsing signal_id with complex market_id containing underscores."""
        signal_id = "20251228_120010_123456_ETH_3500_YES"

        parsed = parse_signal_id(signal_id)

        assert parsed["market_id"] == "ETH_3500_YES"


class TestExtractTimestampFromSignalId:
    """Test timestamp extraction from signal_id."""

    def test_extract_timestamp_with_microseconds(self):
        """Test extracting timestamp with microseconds."""
        signal_id = "20251228_120010_123456_BTC_105000_NO"

        timestamp = extract_timestamp_from_signal_id(signal_id)

        expected = datetime(2025, 12, 28, 12, 0, 10, 123456, tzinfo=timezone.utc)
        assert timestamp == expected

    def test_extract_timestamp_legacy_format(self):
        """Test extracting timestamp from legacy format (no microseconds)."""
        signal_id = "20251228_120010_BTC_105000_NO"

        timestamp = extract_timestamp_from_signal_id(signal_id)

        # Microseconds should be 0
        expected = datetime(2025, 12, 28, 12, 0, 10, 0, tzinfo=timezone.utc)
        assert timestamp == expected

    def test_extract_timestamp_with_prefix(self):
        """Test extracting timestamp from signal_id with prefix."""
        signal_id = "SNAP_20251228_120010_123456_BTC_105000_NO"

        timestamp = extract_timestamp_from_signal_id(signal_id)

        expected = datetime(2025, 12, 28, 12, 0, 10, 123456, tzinfo=timezone.utc)
        assert timestamp == expected


class TestExtractMarketIdFromSignalId:
    """Test market_id extraction from signal_id."""

    def test_extract_market_id_no_prefix(self):
        """Test extracting market_id without prefix."""
        signal_id = "20251228_120010_123456_BTC_105000_NO"

        market_id = extract_market_id_from_signal_id(signal_id)

        assert market_id == "BTC_105000_NO"

    def test_extract_market_id_with_prefix(self):
        """Test extracting market_id with prefix."""
        signal_id = "SNAP_20251228_120010_123456_BTC_105000_NO"

        market_id = extract_market_id_from_signal_id(signal_id)

        assert market_id == "BTC_105000_NO"

    def test_extract_market_id_legacy_format(self):
        """Test extracting market_id from legacy format."""
        signal_id = "20251228_120010_BTC_105000_NO"

        market_id = extract_market_id_from_signal_id(signal_id)

        assert market_id == "BTC_105000_NO"


class TestRoundTrip:
    """Test round-trip conversion (generate -> parse -> extract)."""

    def test_round_trip_no_prefix(self):
        """Test round-trip without prefix."""
        original_market_id = "BTC_105000_NO"
        original_timestamp = datetime(2025, 12, 28, 12, 0, 10, 123456, tzinfo=timezone.utc)

        # Generate
        signal_id = generate_signal_id(
            market_id=original_market_id,
            timestamp=original_timestamp
        )

        # Extract
        extracted_timestamp = extract_timestamp_from_signal_id(signal_id)
        extracted_market_id = extract_market_id_from_signal_id(signal_id)

        # Verify
        assert extracted_timestamp == original_timestamp
        assert extracted_market_id == original_market_id

    def test_round_trip_with_prefix(self):
        """Test round-trip with SNAP prefix."""
        original_market_id = "ETH_3500_YES"
        original_timestamp = datetime(2025, 12, 28, 15, 30, 45, 789012, tzinfo=timezone.utc)

        # Generate
        signal_id = generate_signal_id(
            market_id=original_market_id,
            timestamp=original_timestamp,
            prefix="SNAP"
        )

        # Extract
        extracted_timestamp = extract_timestamp_from_signal_id(signal_id)
        extracted_market_id = extract_market_id_from_signal_id(signal_id)

        # Verify
        assert extracted_timestamp == original_timestamp
        assert extracted_market_id == original_market_id
