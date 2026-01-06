"""
Tests for EV data management functions.
"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.maintain_data.ev import (
    get_ev_entries,
    get_ev_by_signal_id,
    ev_exists,
    pydantic_field_names,
)
from src.maintain_data.maintain_data import maintain_data, _normalize_timestamp_to_utc
from src.api.models import EVResponse


class TestPydanticFieldNames:
    """Tests for pydantic_field_names function."""

    def test_returns_field_names_for_ev_response(self):
        """Should return all field names from EVResponse model."""
        fields = pydantic_field_names(EVResponse)
        assert "signal_id" in fields
        assert "timestamp" in fields
        assert "market_title" in fields
        assert "strategy" in fields

    def test_raises_for_non_pydantic_class(self):
        """Should raise TypeError for non-Pydantic classes."""
        with pytest.raises(TypeError):
            pydantic_field_names(dict)


class TestNormalizeTimestampToUtc:
    """Tests for timestamp normalization."""

    def test_normalizes_iso_string(self):
        """Should normalize ISO string to UTC."""
        result = _normalize_timestamp_to_utc("2025-01-06T12:00:00")
        assert "+00:00" in result or "Z" in result

    def test_normalizes_unix_timestamp(self):
        """Should normalize Unix timestamp to UTC ISO string."""
        result = _normalize_timestamp_to_utc(1704542400)  # 2024-01-06T12:00:00 UTC
        assert "2024-01-06" in result

    def test_handles_none_value(self):
        """Should return current UTC time for None."""
        result = _normalize_timestamp_to_utc(None)
        assert result is not None
        assert len(result) > 0

    def test_handles_empty_string(self):
        """Should return current UTC time for empty string."""
        result = _normalize_timestamp_to_utc("")
        assert result is not None
        assert len(result) > 0


class TestEvExists:
    """Tests for ev_exists function."""

    def test_returns_false_for_empty_csv(self, tmp_path):
        """Should return False for empty CSV."""
        ev_path = tmp_path / "ev.csv"
        # Create empty CSV with headers
        with patch("src.maintain_data.ev.CsvHandler") as mock_handler:
            mock_handler.check_csv = MagicMock()
            with patch("pandas.read_csv") as mock_read:
                import pandas as pd
                mock_read.return_value = pd.DataFrame()
                result = ev_exists("test_signal", str(ev_path))
                assert result is False


class TestMaintainData:
    """Tests for maintain_data function."""

    @pytest.mark.asyncio
    async def test_skips_nonexistent_file(self, tmp_path):
        """Should skip maintenance if ev.csv doesn't exist."""
        with patch("src.maintain_data.maintain_data.CsvHandler") as mock_handler:
            mock_handler.check_csv = MagicMock()
            with patch("pathlib.Path.exists", return_value=False):
                # Should not raise
                await maintain_data()

    @pytest.mark.asyncio
    async def test_handles_empty_csv(self, tmp_path):
        """Should handle empty CSV gracefully."""
        with patch("src.maintain_data.maintain_data.CsvHandler") as mock_handler:
            mock_handler.check_csv = MagicMock()
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pandas.read_csv") as mock_read:
                    import pandas as pd
                    mock_read.return_value = pd.DataFrame()
                    # Should not raise
                    await maintain_data()
