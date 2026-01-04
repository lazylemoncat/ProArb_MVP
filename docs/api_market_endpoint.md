# `/api/market` Endpoint Documentation

## Overview

The `/api/market` endpoint provides access to market snapshot data from the raw CSV files. Each snapshot includes orderbook data from both Polymarket (YES/NO tokens) and Deribit (K1/K2 options).

## Signal ID Format

Each market snapshot is identified by a unique `signal_id` with the following format:

```
SNAP_{YYYYMMDD}_{HHMMSS}_{asset}_{strike}_{hash}
```

**Components**:
- `SNAP`: Fixed prefix for market snapshots
- `YYYYMMDD`: Date (extracted from timestamp)
- `HHMMSS`: Time (extracted from timestamp)
- `asset`: Asset type (`BTC` or `ETH`)
- `strike`: Simplified strike price (e.g., `100k`, `95.5k`, `3.5k`)
- `hash`: 4-character MD5 hash for uniqueness (based on timestamp + market_id)

**Examples**:
- `SNAP_20251221_120010_BTC_100k_a3f9`
- `SNAP_20251221_120010_BTC_95.5k_b366`
- `SNAP_20251221_143045_ETH_3.5k_e563`

## Endpoints

### 1. Get Market Snapshots (List)

```http
GET /api/market?limit=10&offset=0&market_title=Bitcoin%20above%2090000%20on%20December%2022
```

**Query Parameters**:
- `limit` (optional): Number of snapshots to return (default: 10, max: 1000)
- `offset` (optional): Number of records to skip for pagination (default: 0)
- `market_title` (optional): Filter by market title

**Response**: Array of `MarketResponse` objects (see schema below)

**Example**:
```bash
curl "http://localhost:8000/api/market?limit=5"
```

### 2. Get Single Market Snapshot

```http
GET /api/market/{signal_id}
```

**Path Parameters**:
- `signal_id`: Unique signal identifier (e.g., `SNAP_20251221_120010_BTC_100k_a3f9`)

**Response**: Single `MarketResponse` object

**Example**:
```bash
curl "http://localhost:8000/api/market/SNAP_20251221_120010_BTC_100k_a3f9"
```

## Response Schema

### MarketResponse

```typescript
{
  // --- A. Basic Metadata ---
  "signal_id": "SNAP_20251221_120010_BTC_100k_a3f9",
  "timestamp": "2025-12-21T12:00:10Z",  // ISO 8601 format
  "market_title": "Bitcoin above 90000 on December 22",

  // --- B. PolyMarket Data (YES/NO orderbooks) ---
  "pm_data": {
    "yes": {
      "bids": [
        {"price": 0.55, "size": 1000.0},  // Level 1
        {"price": 0.54, "size": 2000.0},  // Level 2
        {"price": 0.53, "size": 500.0}    // Level 3
      ],
      "asks": [
        {"price": 0.56, "size": 500.0},
        {"price": 0.57, "size": 1000.0},
        {"price": 0.58, "size": 500.0}
      ]
    },
    "no": {
      "bids": [
        {"price": 0.44, "size": 1000.0},
        {"price": 0.43, "size": 2000.0},
        {"price": 0.42, "size": 500.0}
      ],
      "asks": [
        {"price": 0.45, "size": 500.0},
        {"price": 0.46, "size": 1000.0},
        {"price": 0.47, "size": 500.0}
      ]
    }
  },

  // --- C. Deribit Data (K1/K2 options + index) ---
  "dr_data": {
    "valid": true,
    "index_price": 98150.20,  // Current spot price
    "k1": {
      "name": "BTC-27DEC24-100000-C",
      "mark_iv": 55.5,
      "mark_price": 0.0468,
      "bids": [
        {"price": 0.105, "size": 5.0},
        {"price": 0.100, "size": 10.0},
        {"price": 0.095, "size": 20.0}
      ],
      "asks": [
        {"price": 0.110, "size": 5.0},
        {"price": 0.115, "size": 10.0},
        {"price": 0.120, "size": 20.0}
      ]
    },
    "k2": {
      "name": "BTC-27DEC24-110000-C",
      "mark_iv": 60.0,
      "mark_price": 0.0268,
      "bids": [
        {"price": 0.025, "size": 5.0},
        {"price": 0.020, "size": 10.0},
        {"price": 0.015, "size": 20.0}
      ],
      "asks": [
        {"price": 0.030, "size": 5.0},
        {"price": 0.035, "size": 10.0},
        {"price": 0.040, "size": 20.0}
      ]
    }
  }
}
```

### Data Types

```typescript
interface MarketResponse {
  signal_id: string;
  timestamp: string;  // ISO 8601
  market_title: string;
  pm_data: PMData;
  dr_data: DRData;
}

interface PMData {
  yes: TokenOrderbook;
  no: TokenOrderbook;
}

interface TokenOrderbook {
  bids: OrderLevel[];  // 3 levels
  asks: OrderLevel[];  // 3 levels
}

interface OrderLevel {
  price: number;
  size: number;
}

interface DRData {
  valid: boolean;
  index_price: number;  // Spot price
  k1: OptionLeg;
  k2: OptionLeg;
}

interface OptionLeg {
  name: string;         // Instrument name
  mark_iv: number;      // Mark implied volatility
  mark_price: number;   // Mark price
  bids: OrderLevel[];   // 3 levels
  asks: OrderLevel[];   // 3 levels
}
```

## Data Source

The endpoint reads data from daily raw CSV files:
- Path: `data/raw_results_{YYYY_MM_DD}.csv`
- If today's file doesn't exist, it falls back to yesterday's file
- Data is sorted by time (newest first)

## CSV Field Mapping

### Polymarket Fields
| CSV Column | API Field | Notes |
|------------|-----------|-------|
| `market_title` | `market_title` | Market description |
| `yes_bid_price_1`, `yes_bid_price_size_1` | `pm_data.yes.bids[0]` | Level 1 bid |
| `yes_bid_price_2`, `yes_bid_price_size_2` | `pm_data.yes.bids[1]` | Level 2 bid |
| `yes_bid_price_3`, `yes_bid_price_size_3` | `pm_data.yes.bids[2]` | Level 3 bid |
| `yes_ask_price_1`, `yes_ask_price_1_size` | `pm_data.yes.asks[0]` | Level 1 ask |
| `no_bid_price_1`, `no_bid_price_size_1` | `pm_data.no.bids[0]` | NO token bids |
| ... | ... | Similar for NO asks |

### Deribit Fields
| CSV Column | API Field | Notes |
|------------|-----------|-------|
| `spot` | `dr_data.index_price` | Current index price |
| `inst_k1` | `dr_data.k1.name` | K1 instrument name |
| `k1_iv` | `dr_data.k1.mark_iv` | K1 implied volatility |
| `k1_mid_usd` | `dr_data.k1.mark_price` | K1 mark price |
| `k1_bid_1_usd` | `dr_data.k1.bids[0]` | K1 Level 1 bid (parsed from `[price, size]`) |
| `k1_ask_1_usd` | `dr_data.k1.asks[0]` | K1 Level 1 ask |
| `inst_k2` | `dr_data.k2.name` | K2 instrument name |
| ... | ... | Similar for K2 |

**Note**: Deribit orderbook fields in CSV are stored as strings like `"[0.105, 5.0]"` and are parsed into `{price, size}` objects.

## Error Responses

### 404 Not Found
```json
{
  "detail": "Raw data file not found: data/raw_results_2025_12_21.csv"
}
```

### 404 Signal Not Found
```json
{
  "detail": "Signal ID not found: SNAP_20251221_120010_BTC_100k_a3f9"
}
```

### 500 Internal Server Error
```json
{
  "detail": "Failed to read market data: <error message>"
}
```

## Usage Examples

### Python (requests)
```python
import requests

# Get latest 10 snapshots
response = requests.get("http://localhost:8000/api/market?limit=10")
snapshots = response.json()

for snapshot in snapshots:
    print(f"Signal: {snapshot['signal_id']}")
    print(f"  Time: {snapshot['timestamp']}")
    print(f"  Market: {snapshot['market_title']}")
    print(f"  PM YES bid: {snapshot['pm_data']['yes']['bids'][0]['price']}")
    print(f"  DR Index: {snapshot['dr_data']['index_price']}")
    print()

# Get specific snapshot
signal_id = snapshots[0]['signal_id']
response = requests.get(f"http://localhost:8000/api/market/{signal_id}")
snapshot = response.json()
```

### JavaScript (fetch)
```javascript
// Get filtered snapshots
const response = await fetch(
  'http://localhost:8000/api/market?limit=5&market_title=Bitcoin%20above%2090000'
);
const snapshots = await response.json();

snapshots.forEach(snap => {
  console.log(`Signal: ${snap.signal_id}`);
  console.log(`  YES bid: ${snap.pm_data.yes.bids[0].price}`);
  console.log(`  K1: ${snap.dr_data.k1.name}`);
});
```

### cURL
```bash
# Get latest 5 snapshots
curl "http://localhost:8000/api/market?limit=5" | jq '.[0] | {signal_id, timestamp, market_title}'

# Get specific snapshot
curl "http://localhost:8000/api/market/SNAP_20251221_120010_BTC_100k_a3f9" | jq '.pm_data.yes.bids'

# Filter by market title
curl -G "http://localhost:8000/api/market" \
  --data-urlencode "market_title=Bitcoin above 90000 on December 22" \
  --data-urlencode "limit=10"
```

## Performance Considerations

- CSV files are read on each request (no caching currently)
- For large CSV files (>10k rows), use pagination with `limit` and `offset`
- Consider implementing caching if the endpoint is heavily used
- Signal ID generation requires iterating through all rows for the `GET /{signal_id}` endpoint

## Future Improvements

- [ ] Add in-memory caching with TTL
- [ ] Add date range query parameters
- [ ] Support multiple date files in a single query
- [ ] Add WebSocket support for real-time updates
- [ ] Add compression for large responses
- [ ] Add field selection to reduce response size

## Related Endpoints

- `/api/ev` - Get EV calculations
- `/api/position` - Get position data
- `/api/pm` - Get Polymarket data only
- `/api/db` - Get Deribit data only

---

**Last Updated**: 2026-01-04
**API Version**: v1.0
**Maintainer**: lazylemoncat
