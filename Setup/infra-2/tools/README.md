# Bootstrap History Tool

This directory contains tools for bootstrapping historical OHLCV (candlestick) data into the bot's SQLite database.

## bootstrap_history.py

A script that fetches historical kline/candlestick data from Binance and stores it in the bot's SQLite database for backtesting and analysis.

### Features

- Fetches historical 1d and 1h kline data from Binance
- Supports incremental updates (only fetches new data after the last stored candle)
- Configurable lookback periods for different intervals
- Uses the existing BinanceSpotClient from the execution module
- Reads configuration from the bot's config.yaml

### Usage

```bash
cd /home/runner/work/cripto-spot-bot/cripto-spot-bot
PYTHONPATH=. python3 Setup/infra-2/tools/bootstrap_history.py config.yaml
```

### Configuration

The script reads the following configuration from your `config.yaml`:

```yaml
# API keys (required for fetching data)
api_keys:
  binance:
    api_key: "your_api_key"
    api_secret: "your_api_secret"

# Or use environment variables (fallback):
# export BINANCE_API_KEY="your_api_key"
# export BINANCE_API_SECRET="your_api_secret"

# Exchange configuration (optional)
binance:
  base_url: "https://api.binance.com"
  recv_window: 5000
  timeout_seconds: 30

# Storage configuration (optional, default: ./bot.db)
storage:
  sqlite_path: "./bot.db"

# History configuration (optional)
history:
  lookback_1d_days: 420  # ~12 months of daily data (default)
  lookback_1h_days: 180  # ~6 months of hourly data (default)

# Universe of symbols to fetch (optional)
universe:
  - BTCUSDT
  - ETHUSDT
  - BNBUSDT
  # ... add more symbols as needed
```

### What it does

1. Connects to your bot's SQLite database
2. Creates the `ohlcv` table if it doesn't exist
3. For each symbol in your universe:
   - Fetches 1d (daily) candles for the configured lookback period
   - Fetches 1h (hourly) candles for the configured lookback period
   - Inserts/updates the data in the database
   - Prints progress for each symbol

### Database Schema

The script creates an `ohlcv` table with the following structure:

```sql
CREATE TABLE ohlcv (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    open_time_ms INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    PRIMARY KEY (symbol, interval, open_time_ms)
);
```

### Incremental Updates

The script is smart about incremental updates:
- On first run, it fetches all historical data
- On subsequent runs, it only fetches new candles since the last stored timestamp
- This makes it safe to run periodically to keep your data up to date

### Example Output

```
DB: ./bot.db
Universe: ['BTCUSDT', 'ETHUSDT']
Backfill: 1d=420 days | 1h=180 days

== BTCUSDT ==
  1d upserts: 420
  1h upserts: 4320

== ETHUSDT ==
  1d upserts: 420
  1h upserts: 4320

Done. Total upserts: 9480
```

### Requirements

- Python 3.10+
- All dependencies from `requirements.txt` (PyYAML, requests)
- Valid Binance API credentials

### Notes

- The script includes rate limiting (0.2s sleep between API calls) to avoid hitting Binance rate limits
- API calls are not signed (public market data), so API keys are loaded but used for client initialization
- The script uses WAL mode for SQLite for better concurrency
