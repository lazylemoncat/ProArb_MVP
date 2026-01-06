"""
Tests for TG_bot and raw.csv sending functionality.
"""
import pytest
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.telegram.TG_bot import TG_bot
from src.main import (
    get_previous_day_raw_csv_path,
    send_previous_day_raw_csv,
    with_raw_date_prefix,
)


class TestTGBot:
    """Tests for TG_bot class."""

    @pytest.mark.asyncio
    async def test_publish_with_mock(self):
        """Test publish method with mocked notifier."""
        with patch("src.telegram.TG_bot.TelegramNotifier") as MockNotifier:
            mock_notifier = MagicMock()
            mock_notifier.send_message = AsyncMock(return_value=(True, "123"))
            MockNotifier.return_value = mock_notifier

            bot = TG_bot(name="test", token="test_token", chat_id="test_chat")
            success, msg_id = await bot.publish("test message")

            assert success is True
            assert msg_id == "123"
            mock_notifier.send_message.assert_called_once_with(
                text="test message", parse_mode=""
            )

    @pytest.mark.asyncio
    async def test_send_document_with_mock(self):
        """Test send_document method with mocked notifier."""
        with patch("src.telegram.TG_bot.TelegramNotifier") as MockNotifier:
            mock_notifier = MagicMock()
            mock_notifier.send_document = AsyncMock(return_value=(True, "456"))
            MockNotifier.return_value = mock_notifier

            bot = TG_bot(name="test", token="test_token", chat_id="test_chat")
            success, msg_id = await bot.send_document(
                file_path="/path/to/file.csv", caption="Test caption"
            )

            assert success is True
            assert msg_id == "456"
            mock_notifier.send_document.assert_called_once_with(
                file_path="/path/to/file.csv", caption="Test caption"
            )

    @pytest.mark.asyncio
    async def test_send_document_failure(self):
        """Test send_document method when sending fails."""
        with patch("src.telegram.TG_bot.TelegramNotifier") as MockNotifier:
            mock_notifier = MagicMock()
            mock_notifier.send_document = AsyncMock(return_value=(False, None))
            MockNotifier.return_value = mock_notifier

            bot = TG_bot(name="test", token="test_token", chat_id="test_chat")
            success, msg_id = await bot.send_document(
                file_path="/path/to/file.csv", caption="Test caption"
            )

            assert success is False
            assert msg_id is None


class TestRawCsvPath:
    """Tests for raw.csv path functions."""

    def test_with_raw_date_prefix_default(self):
        """Test with_raw_date_prefix with default date."""
        result = with_raw_date_prefix("./data/raw_results.csv")
        today = datetime.now(timezone.utc).date()
        expected = f"data/{today:%Y%m%d}_raw.csv"
        assert expected in result

    def test_with_raw_date_prefix_specific_date(self):
        """Test with_raw_date_prefix with specific date."""
        from datetime import date

        test_date = date(2025, 12, 25)
        result = with_raw_date_prefix("./data/raw_results.csv", d=test_date)
        assert "20251225_raw.csv" in result

    def test_get_previous_day_raw_csv_path(self):
        """Test get_previous_day_raw_csv_path returns correct path."""
        result = get_previous_day_raw_csv_path("./data/raw_results.csv")
        yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1))
        expected = f"{yesterday:%Y%m%d}_raw.csv"
        assert expected in result


class TestSendPreviousDayRawCsv:
    """Tests for send_previous_day_raw_csv function."""

    @pytest.mark.asyncio
    async def test_send_previous_day_raw_csv_file_not_found(self):
        """Test send_previous_day_raw_csv when file doesn't exist."""
        with patch("src.telegram.TG_bot.TelegramNotifier") as MockNotifier:
            mock_notifier = MagicMock()
            MockNotifier.return_value = mock_notifier

            bot = TG_bot(name="test", token="test_token", chat_id="test_chat")

            # Use a path that doesn't exist
            result = await send_previous_day_raw_csv(
                bot, "./nonexistent/raw_results.csv"
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_send_previous_day_raw_csv_success(self):
        """Test send_previous_day_raw_csv with existing file."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create yesterday's raw.csv file
            yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1))
            raw_filename = f"{yesterday:%Y%m%d}_raw.csv"
            raw_file_path = Path(tmp_dir) / raw_filename

            # Create the file with some test data
            raw_file_path.write_text("col1,col2\nval1,val2\n")

            with patch("src.telegram.TG_bot.TelegramNotifier") as MockNotifier:
                mock_notifier = MagicMock()
                mock_notifier.send_document = AsyncMock(return_value=(True, "789"))
                MockNotifier.return_value = mock_notifier

                bot = TG_bot(name="test", token="test_token", chat_id="test_chat")

                # Base path template
                base_path = str(Path(tmp_dir) / "raw_results.csv")

                result = await send_previous_day_raw_csv(bot, base_path)

                assert result is True
                mock_notifier.send_document.assert_called_once()
                call_args = mock_notifier.send_document.call_args
                assert raw_filename in call_args.kwargs.get(
                    "file_path", call_args.args[0] if call_args.args else ""
                )

    @pytest.mark.asyncio
    async def test_send_previous_day_raw_csv_send_failure(self):
        """Test send_previous_day_raw_csv when Telegram send fails."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create yesterday's raw.csv file
            yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1))
            raw_filename = f"{yesterday:%Y%m%d}_raw.csv"
            raw_file_path = Path(tmp_dir) / raw_filename
            raw_file_path.write_text("col1,col2\nval1,val2\n")

            with patch("src.telegram.TG_bot.TelegramNotifier") as MockNotifier:
                mock_notifier = MagicMock()
                mock_notifier.send_document = AsyncMock(return_value=(False, None))
                MockNotifier.return_value = mock_notifier

                bot = TG_bot(name="test", token="test_token", chat_id="test_chat")
                base_path = str(Path(tmp_dir) / "raw_results.csv")

                result = await send_previous_day_raw_csv(bot, base_path)

                assert result is False


# Integration test - requires actual credentials
class TestTGBotIntegration:
    """Integration tests that require real Telegram credentials."""

    @pytest.mark.skip(reason="Requires real Telegram credentials")
    @pytest.mark.asyncio
    async def test_publish_real(self):
        """Test publish method with real Telegram API."""
        from src.utils.dataloader import load_all_configs

        env_config, _, _ = load_all_configs(dotenv_path="dev.env")
        alert_token = str(env_config.TELEGRAM_BOT_TOKEN_ALERT)
        chat_id = str(env_config.TELEGRAM_CHAT_ID)
        alert_bot = TG_bot(name="alert", token=alert_token, chat_id=chat_id)

        success, msg_id = await alert_bot.publish("test message")
        assert success is True
        assert msg_id is not None

    @pytest.mark.skip(reason="Requires real Telegram credentials and file")
    @pytest.mark.asyncio
    async def test_send_document_real(self):
        """Test send_document method with real Telegram API."""
        from src.utils.dataloader import load_all_configs

        env_config, _, _ = load_all_configs(dotenv_path="dev.env")
        alert_token = str(env_config.TELEGRAM_BOT_TOKEN_ALERT)
        chat_id = str(env_config.TELEGRAM_CHAT_ID)
        alert_bot = TG_bot(name="alert", token=alert_token, chat_id=chat_id)

        # Create a temp file to send
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as tmp_file:
            tmp_file.write("test,data\n1,2\n")
            tmp_path = tmp_file.name

        success, msg_id = await alert_bot.send_document(
            file_path=tmp_path, caption="Test document"
        )
        assert success is True
        assert msg_id is not None

        # Cleanup
        Path(tmp_path).unlink()
