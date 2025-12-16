#!/bin/bash
# Run bot in paper trading mode

set -e

echo "Starting Vini QuantBot v3.0.1 in PAPER mode..."

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

# Ensure mode is set to paper in config
python3 -c "
import yaml
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)
if config.get('mode') != 'paper':
    print('Warning: config.yaml mode is not set to paper')
    print('Setting mode to paper...')
    config['mode'] = 'paper'
    with open('config.yaml', 'w') as f:
        yaml.dump(config, f)
"

# Run bot
python -m bot.main --config config.yaml

deactivate
