# ProArb MVP - AI Assistant Guide

## Project Overview

**ProArb** is a cryptocurrency arbitrage bot that identifies and executes profitable trading opportunities between **Polymarket** (prediction markets) and **Deribit** (options exchange). The system monitors BTC/ETH markets in real-time, calculates expected value using Black-Scholes pricing models, and executes hedged positions when favorable opportunities arise.

### Core Functionality
- **Real-time Market Monitoring**: Continuously fetches price data from Polymarket and Deribit
- **Arbitrage Detection**: Identifies price discrepancies using Black-Scholes probability calculations
- **Trade Execution**: Automatically executes hedged positions (PM + Deribit vertical spreads)
- **Risk Management**: Multi-layer filtering system to validate trade signals
- **Position Management**: Tracks open positions with early exit monitoring
- **Notifications**: Telegram alerts for opportunities and trade executions

## Technology Stack

- **Language**: Python 3.12
- **Web Framework**: FastAPI (async REST API)
- **Async Runtime**: asyncio, aiohttp
- **Data Processing**: pandas, numpy
- **Package Manager**: uv (with uv.lock)
- **Containerization**: Docker with supervisor (multi-process)
- **Testing**: pytest with pytest-asyncio
- **External APIs**: Polymarket (py-clob-client), Deribit, Telegram

## Repository Structure

```
ProArb_MVP/
├── src/
│   ├── main.py                          # Main monitoring loop + early exit logic
│   ├── api_server.py                    # FastAPI REST API server
│   │
│   ├── api/                             # API route handlers
│   │   ├── health.py                    # Health check endpoint
│   │   ├── ev.py                        # EV calculation endpoints
│   │   ├── position.py                  # Position management
│   │   ├── lifespan.py                  # App lifecycle management
│   │   └── models.py                    # Pydantic response models
│   │
│   ├── build_event/                     # Market event construction
│   │   ├── build_event.py               # Event building logic
│   │   ├── build_event_for_data.py      # Data-based event building
│   │   └── init_markets.py              # Market initialization
│   │
│   ├── fetch_data/                      # External data fetching
│   │   ├── polymarket/
│   │   │   ├── polymarket_api.py        # Polymarket HTTP API client
│   │   │   ├── polymarket_client.py     # Main PM client with context building
│   │   │   ├── polymarket_ws.py         # WebSocket streaming
│   │   │   └── get_polymarket_slippage.py  # Slippage calculation
│   │   └── deribit/
│   │       ├── deribit_api.py           # Deribit HTTP API client
│   │       └── deribit_client.py        # Main Deribit client with context building
│   │
│   ├── strategy/
│   │   └── strategy2.py                 # Black-Scholes pricing & PME margin calculation
│   │
│   ├── filters/                         # Signal filtering system
│   │   ├── filters.py                   # Main filter coordinator
│   │   ├── record_signal_filter.py      # Alert/recording conditions
│   │   └── trade_filter.py              # Trade execution validation
│   │
│   ├── trading/                         # Trade execution clients
│   │   ├── polymarket_trade_client.py   # PM order execution
│   │   ├── polymarket_trade.py          # PM trading logic
│   │   ├── deribit_trade_client.py      # Deribit order execution
│   │   └── deribit_trade.py             # Deribit trading logic
│   │
│   ├── services/
│   │   └── execute_trade.py             # Orchestrates PM + Deribit trades
│   │
│   ├── telegram/
│   │   ├── telegramNotifier.py          # Notification sender
│   │   └── TG_bot.py                    # Telegram bot wrapper
│   │
│   ├── maintain_data/
│   │   ├── maintain_data.py             # Data cleanup tasks
│   │   └── ev.py                        # EV data management
│   │
│   ├── sql/                             # Database schemas
│   │   └── 1.sql                        # MySQL schema for raw data table
│   │
│   └── utils/
│       ├── CsvHandler.py                # CSV read/write utilities with auto-column handling
│       ├── save_result2.py              # Result logging to CSV
│       ├── save_result_mysql.py         # MySQL result logging (optional)
│       ├── save_position.py             # Position tracking
│       ├── get_bot.py                   # Bot retrieval helper
│       └── dataloader/                  # Configuration loaders
│           ├── env_loader.py            # .env file parsing
│           ├── config_loader.py         # config.yaml parsing
│           ├── trading_config_loader.py # trading_config.yaml parsing
│           └── dataloader.py            # Unified config loader
│
├── tests/                               # Unit and integration tests
│   ├── api/                             # API endpoint tests
│   ├── maintain_data/                   # Data management tests
│   ├── strategy/                        # Strategy calculation tests
│   ├── telegram/                        # Telegram bot tests
│   └── utils/                           # Utility function tests
│
├── data/                                # Runtime data (CSV logs, positions)
├── docs/                                # Documentation
├── .github/workflows/                   # CI/CD pipelines
│   └── docker-build-push.yml            # Docker build automation
├── config.yaml                          # Market configuration
├── trading_config.yaml                  # Risk & filter configuration
├── .env.example                         # Environment variable template
├── pyproject.toml                       # Python dependencies
├── Dockerfile                           # Container image definition
├── supervisord.conf                     # Process manager config (API + monitor)
└── README.md                            # Deployment commands
```

## Key Components Explained

### 1. Main Monitor Loop (`src/main.py`)

**Purpose**: The core event loop that orchestrates the entire arbitrage monitoring and trading flow.

**Flow**:
1. Load configurations (env, config.yaml, trading_config.yaml)
2. Initialize clients (Polymarket, Deribit, Telegram)
3. Build market events based on target date
4. Every 10 seconds:
   - Fetch PM orderbook snapshots
   - Fetch Deribit option prices
   - Calculate strategy EV using Black-Scholes
   - Apply signal filters (record + trade)
   - Send Telegram alerts if conditions met
   - Execute trades if trade_signal == True
   - Run early exit monitor
   - Maintain/cleanup data

**Key Function**: `main_monitor()` at line 289

**Important**:
- Runs indefinitely with 10-second intervals
- Handles date rollover automatically (T+1 markets)
- Catches and logs exceptions to avoid crashes

### 2. Strategy Calculation (`src/strategy/strategy2.py`)

**Purpose**: Implements Black-Scholes option pricing and Portfolio Margin Estimator (PME) for Deribit.

**Key Components**:
- **Black-Scholes Probability**: Calculate implied probabilities for BTC price ranges
- **Vertical Spread Pricing**: Price K1-K2 call spreads on Deribit
- **PME Margin Calculation**: Simulate worst-case PnL across price/volatility shocks to determine required margin
- **Settlement Adjustment**: Account for 8-9 hour time difference between Deribit and Polymarket settlement

**Key Function**: `cal_strategy_result()` at line 346

**StrategyOutput Fields**:
- `gross_ev`: Unadjusted gross EV (before theta adjustment)
- `adjusted_gross_ev`: Theta-adjusted gross EV (after settlement time correction)
- `contract_amount`: Number of BTC contracts for Deribit vertical spread
- `roi_pct`: Return on investment percentage
- `im_value_usd`: Initial margin required on Deribit (calculated via PME)

**Formula Overview**:
```
Unadjusted Gross EV = PM_Expected_EV + Deribit_Expected_EV
Settlement Adjustment = Theta correction for 8-9 hour time difference
Adjusted Gross EV = Unadjusted Gross EV + Settlement_Adjustment
Net EV = Adjusted Gross EV - Fees - Slippage
ROI% = Net_EV / (PM_Investment + Deribit_Margin) * 100
```

**Important**: The strategy now returns both `gross_ev` (unadjusted) and `adjusted_gross_ev` (theta-adjusted). Use `adjusted_gross_ev` for net EV calculations and decision-making, while `gross_ev` shows the raw expected value before settlement time corrections.

### 3. Signal Filtering System (`src/filters/`)

**Two-Stage Filter**:

#### Stage 1: Record Signal Filter (`record_signal_filter.py`)
Controls when to **alert/record** opportunities. Must satisfy:
- Time window elapsed (default 300s between alerts for same market)
- Positive net EV
- AND any of:
  - EV change (ROI >1.5% relative change, net_ev >1.5% absolute change)
  - Sign change (strategy flip or sentiment reversal)
  - Market change (PM price >2% change OR Deribit price >3% change)

#### Stage 2: Trade Filter (`trade_filter.py`)
Validates whether to **execute trades**. Checks:
- Investment limit (≤ configured max)
- Daily trade limit (default: 3 trades/day)
- Open positions limit (default: 3 concurrent positions)
- No repeat positions on same market (unless allowed)
- Contract amount ≥ minimum (0.1 BTC)
- Contract amount within rounding band (±30% of theoretical)
- PM price bounds (0.01 ≤ price ≤ 0.99)
- Minimum net EV (≥ 0.0)
- Minimum ROI (≥ 1.0%)
- Minimum probability edge (≥ 0.01)

**Key Function**: `check_should_trade_signal()` in `filters.py:81`

### 4. Trade Execution (`src/services/execute_trade.py`)

**Purpose**: Orchestrates atomic execution of hedged positions across Polymarket and Deribit.

**Flow**:
1. Validate pre-conditions (dry_run mode, filters passed)
2. **Execute Polymarket leg**:
   - Buy NO tokens (or YES depending on strategy)
   - Calculate slippage
   - Submit limit order via py-clob-client
3. **Execute Deribit leg**:
   - Long K1 call (ask price)
   - Short K2 call (bid price)
   - Creates vertical spread
4. **Record position** to `positions.csv`
5. **Send Telegram notification** with trade details
6. **Handle errors**: Roll back if either leg fails

**Important**: Uses `asyncio.gather()` to execute both legs concurrently where possible.

### 5. Early Exit Monitor (`early_exit_monitor()` in `src/main.py`)

**Purpose**: Automatically close positions early if they meet exit criteria. Implemented as an async function within the main monitoring loop.

**Location**: `src/main.py:400-412` (function) and `src/main.py:385-398` (row processing logic)

**Exit Conditions**:
- Position has reached expiry
- Loss exceeds threshold (configurable via `trading_config.yaml`)
- Time window check (08:00-16:00 UTC, if enabled)
- Sufficient liquidity available (price between 0.001 and 0.999)

**Flow**:
1. Read `data/positions.csv` using CsvHandler (auto-ensures all required columns exist)
2. For each OPEN position:
   - Check if expiry reached
   - Fetch current PM price via PolymarketClient
   - Determine which token to sell (YES or NO based on strategy)
   - If price within bounds (0.001-0.999) → execute early exit via Polymarket_trade_client
   - Update status to "close"
3. Save updated positions back to CSV
4. Telegram notification sent by trade client

**Integration**: Called within the main monitoring loop (typically every 10-60 seconds, runs as part of main loop cycle)

### 6. FastAPI Server (`src/api_server.py`)

**Purpose**: Provides REST API for monitoring and manual trade execution.

**Key Endpoints**:
- `GET /api/health` - Health check (used by Docker healthcheck)
- `GET /api/no/ev` - Get current EV calculations for all monitored markets (includes k1/k2 bid/ask prices, accurate slippage, and separated gross/theta-adjusted EV)
- `GET /api/pm` - Polymarket market data (orderbook snapshots)
- `GET /api/db` - Deribit market data (option prices, IV)
- `POST /trade/sim` - Simulate trade (dry-run, no execution)
- `POST /api/trade/execute` - Execute trade manually (bypasses some filters)
- `GET /api/position` - Fetch all positions (OPEN and CLOSE) with nested structure
- `GET /api/close` - Fetch closed positions only (status == "CLOSE")
- `GET /api/pnl` - Get PnL summary (total P&L, win rate, etc.)
- `GET /api/files/{filename}` - Download CSV logs/data (with path traversal protection)

**Runs on**: Port 8000 (uvicorn)

**Managed by**: supervisord (runs alongside main monitor in same container)

**EV Endpoint Response (`/api/no/ev`)**:
Returns detailed EV calculation data with the following key fields:
- `k1_ask`, `k1_bid`: K1 strike bid/ask prices in BTC
- `k2_ask`, `k2_bid`: K2 strike bid/ask prices in BTC
- `pm_slippage_usd`: Actual slippage cost (calculated as `actual_cost - target_cost`)
- `pm_shares`: Actual shares received from PM trade (accounting for slippage)
- `target_usd`: Target investment amount (what you intended to spend)
- `ev_gross_usd`: Unadjusted gross expected value (before theta adjustment)
- `ev_theta_adj_usd`: Theta-adjusted expected value (accounts for 8-9 hour settlement time difference)
- `ev_model_usd`: Final net EV after fees and slippage

**Recent Changes**:
- EV endpoint renamed from `/api/ev` to `/api/no/ev` (commit 4226f46)
- Added k1/k2 bid/ask prices in BTC to EV response (commit 4226f46)
- Fixed slippage calculation to use actual cost difference (commit 4226f46)
- Separated ev_gross_usd and ev_theta_adj_usd to show settlement adjustment (commit 4226f46)
- Position API restructured to nested format (PR #50)
- Added `/api/close` endpoint for filtered closed positions (commit 8fb151b)

### 7. CsvHandler Utility (`src/utils/CsvHandler.py`)

**Purpose**: Robust CSV read/write operations with automatic schema management.

**Key Features**:
- **Auto-column handling**: Automatically adds missing columns to existing CSV files (PR #51)
- **Dataclass integration**: Uses Python dataclasses to define expected schema
- **Thread-safe operations**: Atomic read-modify-write for concurrent access
- **Schema validation**: Ensures CSV files match expected structure

**Key Methods**:
- `check_csv(csv_path, expected_columns, fill_value)` - Ensures all columns exist, adds missing ones with fill_value
- `save_to_csv(csv_path, row_dict, class_obj)` - Saves row based on dataclass schema
- `delete_csv(csv_path, not_exists_ok)` - Safe file deletion

**Usage Pattern**:
```python
from src.utils.CsvHandler import CsvHandler
from src.utils.save_position import SavePosition
from dataclasses import fields

# Ensure CSV has all required columns
positions_columns = [f.name for f in fields(SavePosition)]
CsvHandler.check_csv("./data/positions.csv", positions_columns, fill_value="")

# Save row
CsvHandler.save_to_csv(csv_path, row_data, SavePosition)
```

**Why This Matters**: Prevents CSV corruption when adding new fields to dataclasses. Old CSV files automatically get new columns without manual migration.

### 8. MySQL Database Support (`src/sql/` and `src/utils/save_result_mysql.py`)

**Purpose**: Optional MySQL storage for historical data analysis.

**Database Schema** (`src/sql/1.sql`):
- **Database**: `proarb` (utf8mb4 charset)
- **Table**: Stores every market check (every 10 seconds)
  - Polymarket data: event/market IDs, orderbook (bid/ask prices, 3 levels deep)
  - Deribit data: option strikes (K1, K2), prices in BTC and USD, implied volatility
  - Strategy data: spot price, expiration, time to expiry, calculated probabilities
  - Indexed on: time, event_id + market_id, asset + time

**Usage**:
- CSV is primary storage (always used)
- MySQL is optional (configured in code, not in config files)
- Useful for historical analysis, backtesting, SQL queries
- Schema supports 3-level orderbook depth for both YES/NO tokens

**Setup**:
```bash
docker pull mysql:8.4.7
# Run MySQL container
mysql < src/sql/1.sql  # Create schema
```

**Integration**: `save_result_mysql.py` provides parallel saving alongside CSV (not currently active by default)

## Configuration Files

### `config.yaml` - Market & Event Configuration

Controls **what markets to monitor** and **basic thresholds**.

Key sections:
```yaml
thresholds:
  ev_spread_min: 0.02              # Minimum probability advantage
  notify_net_ev_min: 0.05          # Minimum net EV to notify
  check_interval_sec: 10           # Loop interval
  INVESTMENTS: [200]               # Investment amounts to test (USD)
  dry_trade: false                 # True = no real trades
  day_off: 1                       # Monitor T+1 markets

events:
  - name: "BTC above ___ template"
    asset: "BTC"
    polymarket:
      event_title: "Bitcoin above ___ on November 17?"
    deribit:
      k1_offset: -1000              # Strike 1 = PM_strike - 1000
      k2_offset: 1000               # Strike 2 = PM_strike + 1000
```

### `trading_config.yaml` - Risk & Filter Configuration

Controls **how trades are filtered and executed**.

Key sections:
```yaml
record_signal_filter:
  time_window_seconds: 300         # Alert cooldown per market
  roi_relative_pct_change: 1.5
  net_ev_absolute_pct_change: 1.5
  pm_price_pct_change: 2
  deribit_price_pct_change: 3

trade_signal_filter:
  inv_usd_limit: 200
  daily_trade_limit: 3
  open_positions_limit: 3
  allow_repeat_open_position: false
  min_contract_amount: 0.1
  min_net_ev: 0.0
  min_roi_pct: 1.0

early_exit:
  enabled: true
  check_time_window: true          # Only exit 08:00-16:00 UTC
  loss_threshold_pct: 0.00         # Exit on any loss
  dry_run: false
```

### `.env` - Secrets & Credentials

**NEVER commit this file.** Use `.env.example` as template.

Required variables:
```bash
# Deribit
deribit_client_secret=
deribit_user_id=
deribit_client_id=

# Polymarket
SIGNER_URL=
SIGNING_TOKEN=
polymarket_secret=
POLYMARKET_PROXY_ADDRESS=

# Telegram
TELEGRAM_BOT_TOKEN_ALERT=
TELEGRAM_BOT_TOKEN_TRADING=
TELEGRAM_CHAT_ID=
```

## Development Workflows

### Local Development

1. **Setup environment**:
   ```bash
   # Install uv package manager (if not installed)
   curl -LsSf https://astral.sh/uv/install.sh | sh

   # Create virtual environment
   uv venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate

   # Install dependencies
   uv pip install -e .
   ```

2. **Configure**:
   ```bash
   cp .env.example .env
   # Edit .env with your API credentials
   ```

3. **Run locally**:
   ```bash
   # Start API server
   uvicorn src.api_server:app --host 0.0.0.0 --port 8000 --reload

   # Start monitor (in separate terminal)
   python -m src.main
   ```

4. **Run tests**:
   ```bash
   pytest tests/ -v
   pytest tests/strategy/test_strategy.py  # Specific test
   ```

### Docker Deployment

The application runs as a single container with **supervisor** managing two processes:
- `api` - FastAPI server (port 8000)
- `monitor` - Main trading loop

**Build & Deploy**:
```bash
# Build image
docker build -t lazylemonkitty/proarb_build:latest .

# Push to registry
docker push lazylemonkitty/proarb_build:latest

# Run container
docker run -d \
  --name proarb \
  --env-file .env \
  -e CONFIG_PATH=/app/config.yaml \
  -e TRADING_CONFIG_PATH=/app/trading_config.yaml \
  -e EV_REFRESH_SECONDS=10 \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  -v $(pwd)/trading_config.yaml:/app/trading_config.yaml:ro \
  lazylemonkitty/proarb_build:latest

# View logs
docker logs -f -n 200 proarb
```

**File Persistence**:
- Mount `./data` volume for CSV logs (`positions.csv`, `results.csv`, `YYYYMMDD_raw.csv`, `proarb.log`)
- Mount config files as read-only
- Use `.env` file for secrets

### CI/CD

GitHub Actions workflow (`.github/workflows/docker-build-push.yml`) automatically:
- Builds Docker image on push to main
- Pushes to Docker registry
- Tags with commit SHA

### Logging Strategy

**Log Files** (in `data/` directory):
- `proarb.log` - Current day's main monitor logs (rotates daily at midnight UTC)
- `proarb_YYYY_MM_DD.log` - Historical logs (30-day retention)
- `server_proarb.log` - Current day's API server logs
- `server_proarb_YYYY_MM_DD.log` - Historical API logs
- `results_YYYY_MM_DD.csv` - Daily filtered results (signals recorded)
- `YYYYMMDD_raw.csv` - All checks (every 10s, format: 20251228_raw.csv)
- `positions.csv` - Current open/closed positions

**Log Rotation**:
- Uses `TimedRotatingFileHandler` with midnight UTC rollover
- Custom namer formats: `proarb_2025_12_28.log`
- See `src/main.py:46-70` and `src/api_server.py:24-48`

**Log Levels**:
- `INFO` - Normal operations, trade executions, signals
- `WARNING` - Failed API calls, filter rejections
- `ERROR` - Exceptions, trade failures

## Key Conventions for AI Assistants

### Code Style

1. **Type Hints**: Use type hints for all function parameters and return values
   ```python
   def cal_strategy_result(strategy_input: Strategy_input) -> StrategyOutput:
   ```

2. **Dataclasses**: Prefer `@dataclass` for structured data
   ```python
   from dataclasses import dataclass

   @dataclass
   class PolymarketContext:
       market_id: str
       yes_token_id: str
       # ...
   ```

3. **Async/Await**: All I/O operations must be async
   ```python
   async def get_pm_context(market_id: str) -> PolymarketContext:
       async with aiohttp.ClientSession() as session:
           # ...
   ```

4. **Exception Handling**:
   - Catch specific exceptions where possible
   - Always log with `logger.error(e, exc_info=True)`
   - Continue on non-fatal errors in loops (see `main.py:284-286`, `main.py:365-372`)

5. **Naming Conventions**:
   - Files: `snake_case.py`
   - Classes: `PascalCase`
   - Functions/variables: `snake_case`
   - Constants: `UPPER_SNAKE_CASE`
   - Private helpers: `_leading_underscore`

### Configuration Management

**CRITICAL**: Never hardcode values. Use configuration loaders.

```python
from src.utils.dataloader import load_all_configs

env, config, trading_config = load_all_configs()

# Access like:
env.deribit_client_id              # From .env
config.thresholds.INVESTMENTS      # From config.yaml
trading_config.trade_filter.min_roi_pct  # From trading_config.yaml
```

**Adding new config**:
1. Add field to appropriate YAML file
2. Update dataclass in `src/utils/dataloader/` (e.g., `config_loader.py:33-54`)
3. Access via loaded config object

### Adding New Features

#### Adding a New Filter Condition

1. **Define condition function** in `src/filters/trade_filter.py`:
   ```python
   def check_new_condition(
       trade_input: Trade_filter_input,
       filter_cfg: Trade_filter
   ) -> tuple[bool, str]:
       condition = trade_input.some_value >= filter_cfg.some_threshold
       detail = f"New condition: {condition} (value={trade_input.some_value})"
       return condition, detail
   ```

2. **Add to filter dataclass** (`src/filters/trade_filter.py`):
   ```python
   @dataclass
   class Trade_filter:
       # ... existing fields
       some_threshold: float
   ```

3. **Update config** (`trading_config.yaml`):
   ```yaml
   trade_signal_filter:
     some_threshold: 5.0
   ```

4. **Integrate in check function** (`src/filters/filters.py:81`):
   ```python
   new_condition, detail = check_new_condition(trade_filter_input, trade_filter)
   details.append(detail)
   ```

5. **Update condition logic**:
   ```python
   return all([
       inv_condition,
       daily_trades_condition,
       # ... existing conditions
       new_condition  # Add here
   ]), details
   ```

#### Adding a New API Endpoint

1. **Define response model** in `src/api/models.py`:
   ```python
   from pydantic import BaseModel

   class NewFeatureResponse(BaseModel):
       timestamp: str
       data: dict
   ```

2. **Create router** (or add to existing in `src/api/`):
   ```python
   from fastapi import APIRouter

   new_router = APIRouter()

   @new_router.get("/api/new-feature", response_model=NewFeatureResponse)
   async def get_new_feature():
       # Implementation
       return NewFeatureResponse(...)
   ```

3. **Register router** in `src/api_server.py:66`:
   ```python
   from .api.new_feature import new_router
   app.include_router(new_router)
   ```

#### Adding a New Market Event Type

1. **Add to `config.yaml`**:
   ```yaml
   events:
     - name: "ETH above ___ template"
       asset: "ETH"
       polymarket:
         event_title: "Ethereum above ___ on November 17?"
       deribit:
         k1_offset: -25
         k2_offset: 25
   ```

2. **Update event builder** if special handling needed (`src/build_event/build_event.py`)

### Testing Guidelines

1. **Test file naming**: `test_<module_name>.py` in parallel `tests/` directory
2. **Use pytest fixtures** for shared setup:
   ```python
   import pytest

   @pytest.fixture
   def strategy_input():
       return Strategy_input(
           inv_usd=200,
           strategy=2,
           # ...
       )

   def test_strategy_calculation(strategy_input):
       result = cal_strategy_result(strategy_input)
       assert result.gross_ev > 0
   ```

3. **Mock external APIs**:
   ```python
   from unittest.mock import AsyncMock, patch

   @pytest.mark.asyncio
   async def test_fetch_pm_data():
       with patch('src.fetch_data.polymarket.polymarket_api.fetch') as mock:
           mock.return_value = AsyncMock(return_value={'data': 'test'})
           result = await PolymarketClient.get_pm_context('market_123')
           assert result is not None
   ```

4. **Run async tests** with `pytest-asyncio`:
   ```python
   @pytest.mark.asyncio
   async def test_async_function():
       result = await some_async_function()
       assert result == expected
   ```

### Common Pitfalls to Avoid

1. **Don't block the event loop**:
   ```python
   # BAD
   time.sleep(10)  # Blocks entire event loop

   # GOOD
   await asyncio.sleep(10)  # Yields control
   ```

2. **Don't ignore filter failures**:
   - Record filter rejections in logs (`logger.info()`)
   - Include rejection reasons in Telegram alerts
   - See `main.py:246-261` for proper pattern

3. **Don't modify `positions.csv` outside `CsvHandler`**:
   ```python
   # Use CsvHandler for atomic CSV updates
   from src.utils.CsvHandler import CsvHandler
   from dataclasses import fields

   # Always ensure CSV has required columns before reading
   CsvHandler.check_csv(csv_path, expected_columns, fill_value="")

   # Then save rows using dataclass schema
   CsvHandler.save_to_csv(csv_path, row_data, YourDataclass)
   ```

   **Important**: Always call `CsvHandler.check_csv()` before reading CSV files to ensure schema compatibility. This auto-adds any missing columns from recent code updates.

4. **Don't hardcode dates/timestamps**:
   ```python
   # Use UTC timezone-aware datetimes
   from datetime import datetime, timezone

   now = datetime.now(timezone.utc)  # Correct
   # NOT: datetime.now()  # Naive, ambiguous
   ```

5. **Don't ignore exception context**:
   ```python
   # BAD
   except Exception:
       pass  # Silent failure

   # GOOD
   except EmptyOrderBookException:
       logger.info("No liquidity, skipping")
       continue
   except Exception as e:
       logger.error("Unexpected error", exc_info=True)
       continue
   ```

6. **Don't mix sync and async**:
   ```python
   # BAD - calling sync code in async context
   async def fetch_data():
       data = requests.get(url)  # Blocks event loop!

   # GOOD - use async HTTP client
   async def fetch_data():
       async with aiohttp.ClientSession() as session:
           async with session.get(url) as resp:
               data = await resp.json()
   ```

### Security Best Practices

1. **Secrets Management**:
   - NEVER commit `.env` file (already in `.gitignore`)
   - Use environment variables for all credentials
   - Rotate API keys regularly

2. **API Security**:
   - Path traversal protection in file download endpoint (`api_server.py:180-193`)
   - Consider adding rate limiting for public endpoints

3. **Trade Execution**:
   - Always validate `dry_run` mode before real trades
   - Log all trade attempts (success and failure)
   - Implement position limits (already done via `trade_filter`)

4. **Docker Security**:
   - Run as non-root user (TODO: add to Dockerfile)
   - Use read-only mounts for config files (already done)
   - Minimize attack surface (slim Python image)

### Debugging Tips

1. **Check logs first**:
   ```bash
   # Local
   tail -f data/proarb.log

   # Docker
   docker logs -f -n 200 proarb
   ```

2. **Enable debug logging**:
   ```yaml
   # trading_config.yaml
   logging:
     enable_debug: true
   ```
   Then:
   ```python
   logger.debug(f"Detailed state: {var}")
   ```

3. **Use dry_run mode**:
   ```yaml
   # config.yaml
   thresholds:
     dry_trade: true  # No real trades

   # trading_config.yaml
   early_exit:
     dry_run: true  # No real exits
   ```

4. **Inspect CSV data**:
   ```bash
   # Download from server
   scp rex@104.248.192.200:data/positions.csv ./data/

   # Or via API
   curl http://localhost:8000/api/files/positions.csv -o positions.csv
   ```

5. **Test strategy calculations**:
   ```bash
   python -m src.strategy.strategy2  # Runs test case at bottom
   ```

6. **Interactive debugging**:
   ```python
   # Add breakpoint
   import pdb; pdb.set_trace()

   # Or use ipdb for better experience
   import ipdb; ipdb.set_trace()
   ```

### Performance Considerations

1. **Rate Limits**:
   - Polymarket: ~5 req/s (undocumented, respect API)
   - Deribit: ~10 req/s public, ~20 req/s private
   - Implement backoff on 429 errors

2. **CSV I/O**:
   - CSV operations are synchronous (blocking)
   - Runs in 10-second loop, so acceptable for MVP
   - For scale: migrate to PostgreSQL/TimescaleDB

3. **Memory Management**:
   - `signal_state` dict grows indefinitely (TODO: add cleanup)
   - Log rotation prevents unbounded disk growth
   - Docker restart clears in-memory state

4. **Concurrency**:
   - Uses `asyncio.gather()` for parallel API calls
   - Max ~10 concurrent markets feasible with current design
   - Consider `asyncio.Queue` + worker pool for scaling

## Monitoring & Observability

### Health Checks

1. **Docker healthcheck**: Polls `/api/health` every 30s
2. **Manual check**: `curl http://localhost:8000/api/health`

### Telegram Alerts

**Alert Bot** (high-priority opportunities):
- New profitable signals (pass `record_signal_filter`)
- Includes rejection reasons (why not traded)

**Trading Bot** (execution notifications):
- Trade executions (success/failure)
- Position updates
- Early exit triggers

### Metrics to Monitor

- **Trade frequency**: Should align with `daily_trade_limit`
- **Win rate**: Track closed positions in `positions.csv`
- **API uptime**: Monitor Polymarket/Deribit connectivity
- **Filter pass rates**: Ratio of alerts → trades
- **Execution slippage**: Actual vs. expected prices

### Common Issues & Resolutions

| Issue | Possible Cause | Solution |
|-------|---------------|----------|
| No trades executing | Filters too strict | Lower thresholds in `trading_config.yaml` |
| Too many alerts | `time_window_seconds` too low | Increase to 300-600s |
| API errors | Rate limiting | Add retry backoff logic |
| Stale data | Network latency | Check `staleness` filters |
| Container restart loops | Invalid config | Check YAML syntax, env vars |
| Missing positions | CSV corruption | Restore from backup, add validation |

## Additional Resources

- **Polymarket API Docs**: https://docs.polymarket.com/
- **Deribit API Docs**: https://docs.deribit.com/
- **Black-Scholes Model**: Implemented in `src/strategy/strategy2.py:269-295`
- **PME Documentation**: See docstrings in `strategy2.py:169-233`

## Contributing Guidelines

When making changes:

1. **Create feature branch**: `git checkout -b feature/description`
2. **Write tests**: Add to `tests/` directory
3. **Update configs**: Document new YAML fields
4. **Update this file**: Keep CLAUDE.md in sync
5. **Test locally**: Run pytest + manual verification
6. **Test in Docker**: Build and run container
7. **Commit with clear messages**:
   ```
   fix: correct PME margin calculation for short positions
   feat: add slippage monitoring endpoint
   docs: update configuration examples
   ```

## Version Information

- **Python**: 3.12 (required)
- **uv**: Latest recommended
- **Docker**: 20.10+ recommended
- **Architecture**: linux/amd64 (ARM not tested)

---

**Last Updated**: 2026-01-17
**Maintainer**: lazylemoncat
**Repository**: lazylemoncat/ProArb_MVP

---

## Recent Changes & Changelog

### 2026-01-17
- **Fix**: Enhanced EV endpoint with accurate slippage calculation and separated theta adjustment (commit 4226f46)
  - **Breaking Change**: Renamed endpoint from `/api/ev` to `/api/no/ev`
  - Fixed `pm_slippage_usd` calculation: Now uses actual cost difference (`actual_cost - target`) instead of incorrect percentage multiplication
  - Added k1/k2 bid/ask price fields (in BTC): `k1_ask`, `k1_bid`, `k2_ask`, `k2_bid`
  - Separated `ev_gross_usd` (unadjusted) and `ev_theta_adj_usd` (theta-adjusted) to clearly show settlement time correction
  - Fixed `target_usd` (renamed from `amount_usd`) to record actual transaction cost instead of target amount
  - Fixed `pm_shares` to use actual shares from slippage calculation instead of simple division
  - Removed `delta` and `theta` fields from position response models (`DRK1Data`, `DRK2Data`)
  - Split settlement prices: `k1_settlement_price` and `k2_settlement_price` now tracked separately
  - Updated `StrategyOutput` dataclass to return both `gross_ev` and `adjusted_gross_ev`
  - All slippage, fee, and EV calculations now use theta-adjusted values for decision-making

### 2026-01-02
- **Documentation**: Updated CLAUDE.md with accurate repository structure
  - Fixed: Removed non-existent `early_exit_monitor.py` file reference
  - Added: `src/sql/` directory documentation with MySQL schema details
  - Added: Comprehensive CsvHandler documentation (auto-column feature from PR #51)
  - Added: MySQL database support section
  - Enhanced: Early exit monitor documentation (now correctly documented as function in main.py)
  - Enhanced: API endpoint documentation with recent changes
  - Enhanced: Test directory structure details

### 2026-01-01
- **Feature**: Enhanced CsvHandler to auto-add missing columns (PR #51, commit dba2cc3)
  - Prevents CSV corruption when dataclass fields are added
  - Automatically migrates old CSV files to new schema
- **Feature**: Position API restructured to nested format (PR #50, commit a55af41)
  - Better JSON structure for frontend consumption
- **Feature**: Added `/api/close` endpoint for filtered closed positions (commit 8fb151b)
- **Feature**: Added early exit functionality to main monitoring loop (commit db8e1a4)
  - Automatically closes losing positions based on configurable thresholds
  - Integrated into main.py as async function
- **Refactor**: Added daily log rotation for both API server and main monitor
  - Logs stored as `proarb_YYYY_MM_DD.log` and `server_proarb_YYYY_MM_DD.log`
  - Prevents unbounded disk growth
- **Refactor**: CSV files now split by day (`results_YYYY_MM_DD.csv`, `YYYYMMDD_raw.csv`)
  - Raw data format: `20251228_raw.csv` (date prefix)
- **Initial**: Comprehensive CLAUDE.md documentation created (commit 5c54148)
