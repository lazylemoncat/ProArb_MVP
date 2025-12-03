# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ProArb_MVP is a cryptocurrency arbitrage system that identifies and executes arbitrage opportunities between **Polymarket** (prediction market) and **Deribit** (options exchange). It monitors BTC price prediction markets on Polymarket and hedges positions using bull call spreads on Deribit.

## Common Commands

### Running the Application

```bash
# Run the main monitor (MUST use -m flag for module execution)
python3 -m src.main

# Run the API server
uvicorn src.api_server:app --host 0.0.0.0 --port 8000

# Run tests
pytest tests/

# Run a single test file
pytest tests/test_save_result.py -v
```

**Important**: Never run `python3 src/main.py` directly - the codebase uses relative imports and requires module execution with `-m`.

### Docker Operations

```bash
# Build and push
docker build -t lazylemonkitty/proarb_build:latest .
docker push lazylemonkitty/proarb_build:latest

# Run container
docker run -d --name proarb \
  --env-file .env \
  -e CONFIG_PATH=/app/config.yaml \
  -e TRADING_CONFIG_PATH=/app/trading_config.yaml \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  -v $(pwd)/trading_config.yaml:/app/trading_config.yaml:ro \
  lazylemonkitty/proarb_build:latest
```

## Architecture

### Core Data Flow

```
config.yaml (event templates + thresholds)
        ↓
    main.py (run_monitor)
        ↓
    ┌───────────────────┐
    │  For each strike  │
    └───────────────────┘
        ↓
┌───────────────┐    ┌─────────────────┐
│ Polymarket    │    │ Deribit         │
│ - YES/NO price│    │ - K1/K2 options │
│ - Orderbook   │    │ - IV, bid/ask   │
└───────────────┘    └─────────────────┘
        ↓                    ↓
    investment_runner.py (evaluate_investment)
        ↓
    ┌─────────────────────────────────────┐
    │ Strategy Comparison:                │
    │ Strategy 1: Buy YES + Sell Bull Call│
    │ Strategy 2: Buy NO + Buy Bull Call  │
    │ → Select higher net EV              │
    └─────────────────────────────────────┘
        ↓
    trade_service.py (execute_trade)
        ↓
    ┌───────────────────────────────────┐
    │ Polymarket Order + Deribit Spread │
    └───────────────────────────────────┘
```

### Key Components

- **`src/main.py`**: Entry point, event discovery, monitoring loop
- **`src/strategy/investment_runner.py`**: EV calculation, strategy selection, cost breakdown
- **`src/strategy/strategy.py`**: Black-Scholes pricing, PME margin calculation, payoff functions
- **`src/services/trade_service.py`**: Trade execution, CSV position tracking
- **`src/api_server.py`**: FastAPI endpoints for /api/pm, /api/db, /api/ev, /api/trade/*
- **`src/fetch_data/`**: API clients for Polymarket and Deribit
- **`src/trading/`**: Order execution for both exchanges

### Two-Strategy System

The system compares two hedging strategies for each opportunity:

1. **Strategy 1**: Buy YES on Polymarket + Sell Bull Call Spread on Deribit
2. **Strategy 2**: Buy NO on Polymarket + Buy Bull Call Spread on Deribit

Contract sizing uses: `contracts = PM_shares / spread_width`

### Configuration Files

- **`config.yaml`**: Event templates, thresholds (INVESTMENTS, ev_spread_min, day_off)
- **`trading_config.yaml`**: Risk limits, execution settings, Telegram alerts
- **`.env`**: API credentials for Deribit, Telegram (copy from `.env.example`)

### Event Title Rotation

The system automatically rotates event titles based on `day_off` setting:
- Template: `"Bitcoin above ___ on November 17?"`
- With `day_off: 1`, rotates to tomorrow's date (e.g., `"Bitcoin above ___ on December 4?"`)

### Data Storage

- `data/results.csv`: EV calculations and trade signals
- `data/positions.csv`: Open position tracking

## Key Concepts

### EV Calculation

Net EV = Gross EV (from 4-interval probability integration) - Total Costs

Costs include:
- PM slippage (orderbook simulation)
- Deribit taker fees + slippage
- Gas fees ($0.2 total: $0.1 open + $0.1 close)
- Holding cost (margin opportunity cost)

### PME Margin

Uses Portfolio Margin Engine simulation with price scenarios from -16% to +16% and volatility shocks to calculate worst-case margin requirement.

### Contract Validation

Deribit requires minimum 0.1 BTC contracts. The system validates and adjusts contract sizes, rejecting trades with >10% adjustment from calculated values.

## API Endpoints

- `GET /api/health` - Health check
- `GET /api/pm` - Polymarket snapshot
- `GET /api/db` - Deribit snapshot
- `GET /api/ev` - EV calculations
- `POST /api/trade/sim` - Trade simulation
- `POST /api/trade/execute` - Execute trade (requires ENABLE_LIVE_TRADING=true)
