"""
Binance BTC Options Liquidity Monitor

Monitors BTC options orderbook data on Binance and saves to binance.csv.
Similar to Deribit liquidity monitoring - tracks multiple strike prices around spot.

Usage:
    python -m src.scripts.binance_options_monitor

API Endpoints used:
    - GET /eapi/v1/index - Spot index price for BTC
    - GET /eapi/v1/exchangeInfo - Available option instruments
    - GET /eapi/v1/depth - Orderbook depth (bid/ask levels)
    - GET /eapi/v1/mark - Mark price and IV
    - GET /eapi/v1/ticker - 24hr ticker statistics

Note:
    Binance Options API (EAPI) may have regional restrictions.
    If you encounter connection issues, try using a VPN or proxy.
"""

import asyncio
import aiohttp
import csv
import logging
import os
from dataclasses import dataclass, fields, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Binance EAPI base URLs (try in order if one fails)
BINANCE_EAPI_BASE_URLS = [
    "https://eapi.binance.com",
    "https://vapi.binance.com",  # Alternative endpoint
]

# Default configuration
DEFAULT_CHECK_INTERVAL_SEC = 10
DEFAULT_STRIKE_OFFSETS = [-3000, -2000, -1000, 1000, 4000, 5000]  # Offsets from rounded spot
DEFAULT_CSV_PATH = "./data/binance.csv"
DEFAULT_TIMEOUT_SEC = 30  # Increased timeout
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY_SEC = 2  # Base delay for exponential backoff


@dataclass
class BinanceStrikeData:
    """Data for a single strike price."""
    strike: int
    symbol: str
    bid1_price: float
    bid1_size: float
    bid2_price: float
    bid2_size: float
    bid3_price: float
    bid3_size: float
    ask1_price: float
    ask1_size: float
    ask2_price: float
    ask2_size: float
    ask3_price: float
    ask3_size: float
    iv: float
    mark_price: float
    settlement_price: float


@dataclass
class BinanceOptionsSnapshot:
    """Complete snapshot of Binance BTC options data."""
    timestamp: str  # YYYYMMDD_HHMMSS format
    index_price: float  # BTC spot price

    # Strike k1 (lowest)
    BN_k1_strike: int
    BN_k1_bid1_price: float
    BN_k1_bid1_size: float
    BN_k1_bid2_price: float
    BN_k1_bid2_size: float
    BN_k1_bid3_price: float
    BN_k1_bid3_size: float
    BN_k1_ask1_price: float
    BN_k1_ask1_size: float
    BN_k1_ask2_price: float
    BN_k1_ask2_size: float
    BN_k1_ask3_price: float
    BN_k1_ask3_size: float
    BN_k1_iv: float
    BN_k1_mark_price: float
    BN_k1_settlement_price: float

    # Strike k2
    BN_k2_strike: int
    BN_k2_bid1_price: float
    BN_k2_bid1_size: float
    BN_k2_bid2_price: float
    BN_k2_bid2_size: float
    BN_k2_bid3_price: float
    BN_k2_bid3_size: float
    BN_k2_ask1_price: float
    BN_k2_ask1_size: float
    BN_k2_ask2_price: float
    BN_k2_ask2_size: float
    BN_k2_ask3_price: float
    BN_k2_ask3_size: float
    BN_k2_iv: float
    BN_k2_mark_price: float
    BN_k2_settlement_price: float

    # Strike k3
    BN_k3_strike: int
    BN_k3_bid1_price: float
    BN_k3_bid1_size: float
    BN_k3_bid2_price: float
    BN_k3_bid2_size: float
    BN_k3_bid3_price: float
    BN_k3_bid3_size: float
    BN_k3_ask1_price: float
    BN_k3_ask1_size: float
    BN_k3_ask2_price: float
    BN_k3_ask2_size: float
    BN_k3_ask3_price: float
    BN_k3_ask3_size: float
    BN_k3_iv: float
    BN_k3_mark_price: float
    BN_k3_settlement_price: float

    # Strike k4
    BN_k4_strike: int
    BN_k4_bid1_price: float
    BN_k4_bid1_size: float
    BN_k4_bid2_price: float
    BN_k4_bid2_size: float
    BN_k4_bid3_price: float
    BN_k4_bid3_size: float
    BN_k4_ask1_price: float
    BN_k4_ask1_size: float
    BN_k4_ask2_price: float
    BN_k4_ask2_size: float
    BN_k4_ask3_price: float
    BN_k4_ask3_size: float
    BN_k4_iv: float
    BN_k4_mark_price: float
    BN_k4_settlement_price: float

    # Strike k5
    BN_k5_strike: int
    BN_k5_bid1_price: float
    BN_k5_bid1_size: float
    BN_k5_bid2_price: float
    BN_k5_bid2_size: float
    BN_k5_bid3_price: float
    BN_k5_bid3_size: float
    BN_k5_ask1_price: float
    BN_k5_ask1_size: float
    BN_k5_ask2_price: float
    BN_k5_ask2_size: float
    BN_k5_ask3_price: float
    BN_k5_ask3_size: float
    BN_k5_iv: float
    BN_k5_mark_price: float
    BN_k5_settlement_price: float

    # Strike k6 (highest)
    BN_k6_strike: int
    BN_k6_bid1_price: float
    BN_k6_bid1_size: float
    BN_k6_bid2_price: float
    BN_k6_bid2_size: float
    BN_k6_bid3_price: float
    BN_k6_bid3_size: float
    BN_k6_ask1_price: float
    BN_k6_ask1_size: float
    BN_k6_ask2_price: float
    BN_k6_ask2_size: float
    BN_k6_ask3_price: float
    BN_k6_ask3_size: float
    BN_k6_iv: float
    BN_k6_mark_price: float
    BN_k6_settlement_price: float


class BinanceOptionsAPI:
    """Binance European Options API client with retry logic."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str = None,
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay_sec: int = DEFAULT_RETRY_DELAY_SEC
    ):
        self.session = session
        self.base_urls = BINANCE_EAPI_BASE_URLS if base_url is None else [base_url]
        self.current_base_url_idx = 0
        self.timeout = aiohttp.ClientTimeout(total=timeout_sec)
        self.max_retries = max_retries
        self.retry_delay_sec = retry_delay_sec

    @property
    def base_url(self) -> str:
        """Get current base URL."""
        return self.base_urls[self.current_base_url_idx]

    def _switch_base_url(self) -> bool:
        """
        Switch to next available base URL.

        Returns:
            True if switched successfully, False if no more URLs available
        """
        if self.current_base_url_idx < len(self.base_urls) - 1:
            self.current_base_url_idx += 1
            logger.info(f"Switching to alternative base URL: {self.base_url}")
            return True
        return False

    async def _request_with_retry(
        self,
        endpoint: str,
        params: dict = None,
        description: str = "API request"
    ) -> dict:
        """
        Make HTTP request with retry logic and exponential backoff.

        Args:
            endpoint: API endpoint path (e.g., /eapi/v1/index)
            params: Query parameters
            description: Description for logging

        Returns:
            Response JSON as dict

        Raises:
            Exception: If all retries fail
        """
        last_error = None

        for attempt in range(self.max_retries):
            for url_idx in range(len(self.base_urls)):
                base_url = self.base_urls[(self.current_base_url_idx + url_idx) % len(self.base_urls)]
                url = f"{base_url}{endpoint}"

                try:
                    logger.debug(f"{description}: attempt {attempt + 1}/{self.max_retries}, URL: {url}")

                    async with self.session.get(
                        url,
                        params=params,
                        timeout=self.timeout
                    ) as resp:
                        if resp.status == 200:
                            # Update current base URL to the working one
                            self.current_base_url_idx = (self.current_base_url_idx + url_idx) % len(self.base_urls)
                            return await resp.json()
                        elif resp.status == 429:
                            # Rate limited - wait and retry
                            retry_after = int(resp.headers.get("Retry-After", self.retry_delay_sec))
                            logger.warning(f"Rate limited. Waiting {retry_after}s before retry...")
                            await asyncio.sleep(retry_after)
                            continue
                        else:
                            text = await resp.text()
                            last_error = Exception(f"{description} failed: {resp.status} - {text}")
                            logger.warning(f"{description} failed with status {resp.status}: {text}")

                except asyncio.TimeoutError as e:
                    last_error = e
                    logger.warning(f"{description} timeout on {base_url} (attempt {attempt + 1})")

                except aiohttp.ClientError as e:
                    last_error = e
                    logger.warning(f"{description} connection error on {base_url}: {e}")

                except Exception as e:
                    last_error = e
                    logger.warning(f"{description} unexpected error: {e}")

            # Exponential backoff before next retry round
            if attempt < self.max_retries - 1:
                delay = self.retry_delay_sec * (2 ** attempt)
                logger.info(f"Retrying in {delay}s (attempt {attempt + 2}/{self.max_retries})...")
                await asyncio.sleep(delay)

        raise Exception(f"{description} failed after {self.max_retries} attempts: {last_error}")

    async def get_index_price(self, underlying: str = "BTCUSDT") -> float:
        """
        Get the spot index price for BTC.

        Args:
            underlying: The underlying asset (default: BTCUSDT)

        Returns:
            Current index price as float
        """
        params = {"underlying": underlying}
        data = await self._request_with_retry(
            "/eapi/v1/index",
            params=params,
            description="Get index price"
        )
        return float(data.get("indexPrice", 0))

    async def get_exchange_info(self) -> dict:
        """
        Get exchange info including available option symbols.

        Returns:
            Exchange info dict with optionSymbols list
        """
        return await self._request_with_retry(
            "/eapi/v1/exchangeInfo",
            description="Get exchange info"
        )

    async def get_depth(self, symbol: str, limit: int = 10) -> dict:
        """
        Get orderbook depth for an option symbol.

        Args:
            symbol: Option symbol (e.g., BTC-250120-92000-C)
            limit: Depth limit (default 10, max 1000)

        Returns:
            Orderbook dict with bids and asks
        """
        params = {"symbol": symbol, "limit": limit}

        try:
            return await self._request_with_retry(
                "/eapi/v1/depth",
                params=params,
                description=f"Get depth for {symbol}"
            )
        except Exception as e:
            logger.warning(f"Failed to get depth for {symbol}: {e}")
            return {"bids": [], "asks": []}

    async def get_mark_price(self, symbol: Optional[str] = None) -> list:
        """
        Get mark price and IV for option(s).

        Args:
            symbol: Optional specific symbol, or None for all

        Returns:
            List of mark price data dicts
        """
        params = {}
        if symbol:
            params["symbol"] = symbol

        data = await self._request_with_retry(
            "/eapi/v1/mark",
            params=params if params else None,
            description="Get mark price"
        )

        # Returns list when no symbol specified, single dict when symbol specified
        if isinstance(data, list):
            return data
        return [data]

    async def get_ticker(self, symbol: Optional[str] = None) -> list:
        """
        Get 24hr ticker statistics for option(s).

        Args:
            symbol: Optional specific symbol, or None for all

        Returns:
            List of ticker data dicts
        """
        params = {}
        if symbol:
            params["symbol"] = symbol

        data = await self._request_with_retry(
            "/eapi/v1/ticker",
            params=params if params else None,
            description="Get ticker"
        )

        if isinstance(data, list):
            return data
        return [data]


class BinanceOptionsMonitor:
    """
    Monitor Binance BTC options liquidity and save to CSV.

    Tracks multiple strike prices around the current BTC spot price,
    similar to Deribit liquidity monitoring.
    """

    def __init__(
        self,
        csv_path: str = DEFAULT_CSV_PATH,
        check_interval_sec: int = DEFAULT_CHECK_INTERVAL_SEC,
        strike_offsets: list = None,
        base_url: str = None,
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
        max_retries: int = DEFAULT_MAX_RETRIES,
        proxy: str = None
    ):
        self.csv_path = csv_path
        self.check_interval_sec = check_interval_sec
        self.strike_offsets = strike_offsets or DEFAULT_STRIKE_OFFSETS
        self.base_url = base_url
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries
        self.proxy = proxy
        self.session: Optional[aiohttp.ClientSession] = None
        self.api: Optional[BinanceOptionsAPI] = None

        # Ensure data directory exists
        Path(csv_path).parent.mkdir(parents=True, exist_ok=True)

    def _round_to_strike(self, price: float, step: int = 1000) -> int:
        """Round price to nearest strike step (e.g., 1000)."""
        return int(round(price / step) * step)

    def _calculate_target_strikes(self, spot_price: float) -> list[int]:
        """
        Calculate target strike prices based on spot price.

        Example: If spot is 92029, rounded to 92000, with offsets [-3000, -2000, -1000, 1000, 4000, 5000]:
            k1 = 89000, k2 = 90000, k3 = 91000, k4 = 93000, k5 = 96000, k6 = 97000
        """
        rounded_spot = self._round_to_strike(spot_price)
        strikes = [rounded_spot + offset for offset in self.strike_offsets]
        return sorted(strikes)

    def _find_nearest_expiry_symbol(
        self,
        symbols: list[dict],
        strike: int,
        option_type: str = "C"
    ) -> Optional[str]:
        """
        Find the option symbol with nearest expiry for a given strike.

        Args:
            symbols: List of option symbols from exchange info
            strike: Target strike price
            option_type: C for Call, P for Put

        Returns:
            Symbol string or None if not found
        """
        matching = []
        for sym in symbols:
            sym_name = sym.get("symbol", "")
            # Binance option symbol format: BTC-YYMMDD-STRIKE-C/P
            parts = sym_name.split("-")
            if len(parts) != 4:
                continue

            asset, expiry_str, strike_str, opt_type = parts
            if asset != "BTC" or opt_type != option_type:
                continue

            try:
                sym_strike = int(strike_str)
                if sym_strike != strike:
                    continue

                # Parse expiry date (format: YYMMDD)
                expiry_date = datetime.strptime(expiry_str, "%y%m%d")
                matching.append((sym_name, expiry_date))
            except (ValueError, TypeError):
                continue

        if not matching:
            return None

        # Sort by expiry date, pick nearest future expiry
        now = datetime.now()
        future_expiries = [(s, d) for s, d in matching if d >= now]

        if future_expiries:
            future_expiries.sort(key=lambda x: x[1])
            return future_expiries[0][0]

        # If no future expiries, return most recent
        matching.sort(key=lambda x: x[1], reverse=True)
        return matching[0][0]

    async def _fetch_strike_data(
        self,
        symbol: str,
        strike: int,
        mark_data: dict,
        ticker_data: dict
    ) -> BinanceStrikeData:
        """
        Fetch complete data for a single strike.

        Args:
            symbol: Option symbol
            strike: Strike price
            mark_data: Pre-fetched mark price data dict (keyed by symbol)
            ticker_data: Pre-fetched ticker data dict (keyed by symbol)

        Returns:
            BinanceStrikeData object
        """
        # Get orderbook depth
        depth = await self.api.get_depth(symbol, limit=10)

        bids = depth.get("bids", [])
        asks = depth.get("asks", [])

        # Extract 3 levels of bids/asks
        def get_level(orders: list, idx: int) -> tuple[float, float]:
            if idx < len(orders):
                return float(orders[idx][0]), float(orders[idx][1])
            return 0.0, 0.0

        bid1_price, bid1_size = get_level(bids, 0)
        bid2_price, bid2_size = get_level(bids, 1)
        bid3_price, bid3_size = get_level(bids, 2)
        ask1_price, ask1_size = get_level(asks, 0)
        ask2_price, ask2_size = get_level(asks, 1)
        ask3_price, ask3_size = get_level(asks, 2)

        # Get mark price and IV from pre-fetched data
        mark_info = mark_data.get(symbol, {})
        iv = float(mark_info.get("markIV", 0))
        mark_price = float(mark_info.get("markPrice", 0))

        # Get settlement price from ticker (if available)
        ticker_info = ticker_data.get(symbol, {})
        # Note: Binance may not provide settlement price for active contracts
        # Use exercisePrice or lastPrice as fallback
        settlement_price = float(ticker_info.get("exercisePrice", 0) or ticker_info.get("lastPrice", 0))

        return BinanceStrikeData(
            strike=strike,
            symbol=symbol,
            bid1_price=bid1_price,
            bid1_size=bid1_size,
            bid2_price=bid2_price,
            bid2_size=bid2_size,
            bid3_price=bid3_price,
            bid3_size=bid3_size,
            ask1_price=ask1_price,
            ask1_size=ask1_size,
            ask2_price=ask2_price,
            ask2_size=ask2_size,
            ask3_price=ask3_price,
            ask3_size=ask3_size,
            iv=iv,
            mark_price=mark_price,
            settlement_price=settlement_price
        )

    async def fetch_snapshot(self) -> Optional[BinanceOptionsSnapshot]:
        """
        Fetch complete options snapshot for all target strikes.

        Returns:
            BinanceOptionsSnapshot or None if fetch fails
        """
        try:
            # Get index price
            index_price = await self.api.get_index_price()
            logger.info(f"BTC index price: {index_price}")

            # Calculate target strikes
            target_strikes = self._calculate_target_strikes(index_price)
            logger.info(f"Target strikes: {target_strikes}")

            # Get exchange info for available symbols
            exchange_info = await self.api.get_exchange_info()
            option_symbols = exchange_info.get("optionSymbols", [])

            # Find symbols for each target strike
            symbols_map = {}
            for strike in target_strikes:
                symbol = self._find_nearest_expiry_symbol(option_symbols, strike, "C")
                if symbol:
                    symbols_map[strike] = symbol
                    logger.debug(f"Strike {strike} -> {symbol}")
                else:
                    logger.warning(f"No symbol found for strike {strike}")

            if len(symbols_map) < 6:
                logger.warning(f"Only found {len(symbols_map)}/6 target strikes")

            # Pre-fetch mark price and ticker data for all symbols
            mark_data_list = await self.api.get_mark_price()
            mark_data = {m["symbol"]: m for m in mark_data_list}

            ticker_data_list = await self.api.get_ticker()
            ticker_data = {t["symbol"]: t for t in ticker_data_list}

            # Fetch data for each strike
            strike_data_list = []
            for strike in target_strikes:
                symbol = symbols_map.get(strike)
                if symbol:
                    data = await self._fetch_strike_data(
                        symbol, strike, mark_data, ticker_data
                    )
                    strike_data_list.append(data)
                else:
                    # Create empty data for missing strike
                    strike_data_list.append(BinanceStrikeData(
                        strike=strike, symbol="",
                        bid1_price=0, bid1_size=0, bid2_price=0, bid2_size=0,
                        bid3_price=0, bid3_size=0, ask1_price=0, ask1_size=0,
                        ask2_price=0, ask2_size=0, ask3_price=0, ask3_size=0,
                        iv=0, mark_price=0, settlement_price=0
                    ))

            # Ensure we have exactly 6 strikes (pad with empty if needed)
            while len(strike_data_list) < 6:
                last_strike = strike_data_list[-1].strike + 1000 if strike_data_list else 0
                strike_data_list.append(BinanceStrikeData(
                    strike=last_strike, symbol="",
                    bid1_price=0, bid1_size=0, bid2_price=0, bid2_size=0,
                    bid3_price=0, bid3_size=0, ask1_price=0, ask1_size=0,
                    ask2_price=0, ask2_size=0, ask3_price=0, ask3_size=0,
                    iv=0, mark_price=0, settlement_price=0
                ))

            # Build timestamp
            now = datetime.now(timezone.utc)
            timestamp = now.strftime("%Y%m%d_%H%M%S")

            # Create snapshot
            k1, k2, k3, k4, k5, k6 = strike_data_list[:6]

            snapshot = BinanceOptionsSnapshot(
                timestamp=timestamp,
                index_price=index_price,
                # k1
                BN_k1_strike=k1.strike,
                BN_k1_bid1_price=k1.bid1_price, BN_k1_bid1_size=k1.bid1_size,
                BN_k1_bid2_price=k1.bid2_price, BN_k1_bid2_size=k1.bid2_size,
                BN_k1_bid3_price=k1.bid3_price, BN_k1_bid3_size=k1.bid3_size,
                BN_k1_ask1_price=k1.ask1_price, BN_k1_ask1_size=k1.ask1_size,
                BN_k1_ask2_price=k1.ask2_price, BN_k1_ask2_size=k1.ask2_size,
                BN_k1_ask3_price=k1.ask3_price, BN_k1_ask3_size=k1.ask3_size,
                BN_k1_iv=k1.iv, BN_k1_mark_price=k1.mark_price,
                BN_k1_settlement_price=k1.settlement_price,
                # k2
                BN_k2_strike=k2.strike,
                BN_k2_bid1_price=k2.bid1_price, BN_k2_bid1_size=k2.bid1_size,
                BN_k2_bid2_price=k2.bid2_price, BN_k2_bid2_size=k2.bid2_size,
                BN_k2_bid3_price=k2.bid3_price, BN_k2_bid3_size=k2.bid3_size,
                BN_k2_ask1_price=k2.ask1_price, BN_k2_ask1_size=k2.ask1_size,
                BN_k2_ask2_price=k2.ask2_price, BN_k2_ask2_size=k2.ask2_size,
                BN_k2_ask3_price=k2.ask3_price, BN_k2_ask3_size=k2.ask3_size,
                BN_k2_iv=k2.iv, BN_k2_mark_price=k2.mark_price,
                BN_k2_settlement_price=k2.settlement_price,
                # k3
                BN_k3_strike=k3.strike,
                BN_k3_bid1_price=k3.bid1_price, BN_k3_bid1_size=k3.bid1_size,
                BN_k3_bid2_price=k3.bid2_price, BN_k3_bid2_size=k3.bid2_size,
                BN_k3_bid3_price=k3.bid3_price, BN_k3_bid3_size=k3.bid3_size,
                BN_k3_ask1_price=k3.ask1_price, BN_k3_ask1_size=k3.ask1_size,
                BN_k3_ask2_price=k3.ask2_price, BN_k3_ask2_size=k3.ask2_size,
                BN_k3_ask3_price=k3.ask3_price, BN_k3_ask3_size=k3.ask3_size,
                BN_k3_iv=k3.iv, BN_k3_mark_price=k3.mark_price,
                BN_k3_settlement_price=k3.settlement_price,
                # k4
                BN_k4_strike=k4.strike,
                BN_k4_bid1_price=k4.bid1_price, BN_k4_bid1_size=k4.bid1_size,
                BN_k4_bid2_price=k4.bid2_price, BN_k4_bid2_size=k4.bid2_size,
                BN_k4_bid3_price=k4.bid3_price, BN_k4_bid3_size=k4.bid3_size,
                BN_k4_ask1_price=k4.ask1_price, BN_k4_ask1_size=k4.ask1_size,
                BN_k4_ask2_price=k4.ask2_price, BN_k4_ask2_size=k4.ask2_size,
                BN_k4_ask3_price=k4.ask3_price, BN_k4_ask3_size=k4.ask3_size,
                BN_k4_iv=k4.iv, BN_k4_mark_price=k4.mark_price,
                BN_k4_settlement_price=k4.settlement_price,
                # k5
                BN_k5_strike=k5.strike,
                BN_k5_bid1_price=k5.bid1_price, BN_k5_bid1_size=k5.bid1_size,
                BN_k5_bid2_price=k5.bid2_price, BN_k5_bid2_size=k5.bid2_size,
                BN_k5_bid3_price=k5.bid3_price, BN_k5_bid3_size=k5.bid3_size,
                BN_k5_ask1_price=k5.ask1_price, BN_k5_ask1_size=k5.ask1_size,
                BN_k5_ask2_price=k5.ask2_price, BN_k5_ask2_size=k5.ask2_size,
                BN_k5_ask3_price=k5.ask3_price, BN_k5_ask3_size=k5.ask3_size,
                BN_k5_iv=k5.iv, BN_k5_mark_price=k5.mark_price,
                BN_k5_settlement_price=k5.settlement_price,
                # k6
                BN_k6_strike=k6.strike,
                BN_k6_bid1_price=k6.bid1_price, BN_k6_bid1_size=k6.bid1_size,
                BN_k6_bid2_price=k6.bid2_price, BN_k6_bid2_size=k6.bid2_size,
                BN_k6_bid3_price=k6.bid3_price, BN_k6_bid3_size=k6.bid3_size,
                BN_k6_ask1_price=k6.ask1_price, BN_k6_ask1_size=k6.ask1_size,
                BN_k6_ask2_price=k6.ask2_price, BN_k6_ask2_size=k6.ask2_size,
                BN_k6_ask3_price=k6.ask3_price, BN_k6_ask3_size=k6.ask3_size,
                BN_k6_iv=k6.iv, BN_k6_mark_price=k6.mark_price,
                BN_k6_settlement_price=k6.settlement_price,
            )

            return snapshot

        except Exception as e:
            logger.error(f"Failed to fetch snapshot: {e}", exc_info=True)
            return None

    def save_snapshot(self, snapshot: BinanceOptionsSnapshot) -> None:
        """
        Save snapshot to CSV file.

        Args:
            snapshot: BinanceOptionsSnapshot to save
        """
        # Convert to dict
        row = asdict(snapshot)

        # Get field names from dataclass
        fieldnames = [f.name for f in fields(BinanceOptionsSnapshot)]

        # Check if file exists and has headers
        file_exists = os.path.isfile(self.csv_path)

        with open(self.csv_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)

            if not file_exists:
                writer.writeheader()

            writer.writerow(row)

        logger.info(f"Saved snapshot to {self.csv_path} at {snapshot.timestamp}")

    async def run_once(self) -> bool:
        """
        Run a single fetch and save cycle.

        Returns:
            True if successful, False otherwise
        """
        snapshot = await self.fetch_snapshot()
        if snapshot:
            self.save_snapshot(snapshot)
            return True
        return False

    def _create_session(self) -> aiohttp.ClientSession:
        """Create aiohttp session with optional proxy support."""
        connector = None
        if self.proxy:
            logger.info(f"Using proxy: {self.proxy}")

        # Configure TCP connector with longer timeouts
        connector = aiohttp.TCPConnector(
            limit=10,
            ttl_dns_cache=300,
            enable_cleanup_closed=True
        )

        return aiohttp.ClientSession(
            connector=connector,
            trust_env=True  # Respect HTTP_PROXY/HTTPS_PROXY environment variables
        )

    async def run_loop(self) -> None:
        """Run continuous monitoring loop."""
        logger.info(f"Starting Binance options monitor (interval: {self.check_interval_sec}s)")
        logger.info(f"Strike offsets: {self.strike_offsets}")
        logger.info(f"CSV path: {self.csv_path}")
        logger.info(f"Timeout: {self.timeout_sec}s, Max retries: {self.max_retries}")
        if self.base_url:
            logger.info(f"Base URL: {self.base_url}")
        if self.proxy:
            logger.info(f"Proxy: {self.proxy}")

        async with self._create_session() as session:
            self.session = session
            self.api = BinanceOptionsAPI(
                session,
                base_url=self.base_url,
                timeout_sec=self.timeout_sec,
                max_retries=self.max_retries
            )

            while True:
                try:
                    success = await self.run_once()
                    if not success:
                        logger.warning("Snapshot fetch failed, will retry next interval")
                except Exception as e:
                    logger.error(f"Error in monitoring loop: {e}", exc_info=True)

                await asyncio.sleep(self.check_interval_sec)

    async def run_single(self) -> None:
        """Run a single fetch (for testing)."""
        async with self._create_session() as session:
            self.session = session
            self.api = BinanceOptionsAPI(
                session,
                base_url=self.base_url,
                timeout_sec=self.timeout_sec,
                max_retries=self.max_retries
            )
            await self.run_once()


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Binance BTC Options Liquidity Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage (continuous monitoring)
  python -m src.scripts.binance_options_monitor

  # Single fetch for testing
  python -m src.scripts.binance_options_monitor --once

  # Custom strike offsets
  python -m src.scripts.binance_options_monitor --offsets "-3000,-2000,-1000,1000,2000,3000"

  # With proxy (for regions where Binance is restricted)
  python -m src.scripts.binance_options_monitor --proxy "http://127.0.0.1:7890"

  # Or set environment variable:
  export HTTPS_PROXY="http://127.0.0.1:7890"
  python -m src.scripts.binance_options_monitor

Note:
  Binance Options API may be restricted in certain regions.
  If you encounter timeout errors, try using a VPN or proxy.
        """
    )
    parser.add_argument(
        "--csv",
        default=DEFAULT_CSV_PATH,
        help=f"Path to output CSV file (default: {DEFAULT_CSV_PATH})"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_CHECK_INTERVAL_SEC,
        help=f"Check interval in seconds (default: {DEFAULT_CHECK_INTERVAL_SEC})"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (for testing)"
    )
    parser.add_argument(
        "--offsets",
        type=str,
        default=None,
        help="Comma-separated strike offsets (e.g., '-3000,-2000,-1000,1000,4000,5000')"
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help=f"Binance EAPI base URL (default: tries {BINANCE_EAPI_BASE_URLS})"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SEC,
        help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT_SEC})"
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"Maximum retry attempts (default: {DEFAULT_MAX_RETRIES})"
    )
    parser.add_argument(
        "--proxy",
        type=str,
        default=None,
        help="HTTP/HTTPS proxy URL (e.g., 'http://127.0.0.1:7890'). "
             "Can also use HTTPS_PROXY environment variable."
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    # Set logging level
    if args.debug:
        logging.getLogger(__name__).setLevel(logging.DEBUG)

    # Set proxy environment variable if provided
    if args.proxy:
        os.environ["HTTPS_PROXY"] = args.proxy
        os.environ["HTTP_PROXY"] = args.proxy

    # Parse offsets if provided
    strike_offsets = None
    if args.offsets:
        strike_offsets = [int(x.strip()) for x in args.offsets.split(",")]

    monitor = BinanceOptionsMonitor(
        csv_path=args.csv,
        check_interval_sec=args.interval,
        strike_offsets=strike_offsets,
        base_url=args.base_url,
        timeout_sec=args.timeout,
        max_retries=args.max_retries,
        proxy=args.proxy
    )

    if args.once:
        await monitor.run_single()
    else:
        await monitor.run_loop()


if __name__ == "__main__":
    asyncio.run(main())
