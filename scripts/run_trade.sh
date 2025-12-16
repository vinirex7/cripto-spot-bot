#!/bin/bash
# Run bot in LIVE trading mode
# ⚠️  WARNING: This will execute real trades with real money!

set -e

echo "⚠️  WARNING: Starting Vini QuantBot v3.0.1 in LIVE mode"
echo "⚠️  This will execute REAL trades with REAL money!"
echo ""
read -p "Are you sure you want to continue? (type 'YES' to confirm): " confirm

if [ "$confirm" != "YES" ]; then
    echo "Aborted."
    exit 1
fi

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "Error: Virtual environment not found. Please run setup first."
    exit 1
fi

# Activate virtual environment
source .venv/bin/activate

# Check if config exists
if [ ! -f "config.yaml" ]; then
    echo "Error: config.yaml not found"
    exit 1
fi

# Check environment variables
if [ -z "$BINANCE_API_KEY" ] || [ -z "$BINANCE_API_SECRET" ]; then
    echo "Error: BINANCE_API_KEY and BINANCE_API_SECRET must be set"
    exit 1
fi

# Ensure mode is set to live in config
python3 -c "
import yaml
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)
config['mode'] = 'live'
with open('config.yaml', 'w') as f:
    yaml.dump(config, f)
print('Mode set to LIVE')
"

echo ""
echo "Starting bot in LIVE mode..."
echo ""

# Run bot
python -m bot.main --config config.yaml

deactivate
