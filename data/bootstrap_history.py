"""
Bootstrap historical data from Binance.
Run this script before starting the bot to populate historical data.
"""
import argparse
import logging
import yaml
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.binance_rest import BinanceRESTClient
from data.history_store import HistoryStore

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def bootstrap_history(config_path: str):
    """
    Bootstrap historical data for all symbols in the universe.
    
    Args:
        config_path: Path to config.yaml
    """
    # Load configuration
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    universe = config.get('universe', [])
    history_config = config.get('history', {})
    lookback_1d = history_config.get('lookback_days_1d', 420)
    lookback_1h = history_config.get('lookback_days_1h', 120)
    db_path = history_config.get('db_path', './state/marketdata.sqlite')
    
    logger.info(f"Starting bootstrap for {len(universe)} symbols")
    logger.info(f"Lookback: {lookback_1d} days (1d), {lookback_1h} days (1h)")
    
    # Initialize clients
    rest_client = BinanceRESTClient()
    store = HistoryStore(db_path)
    
    # Fetch data for each symbol
    for symbol in universe:
        logger.info(f"Processing {symbol}...")
        
        try:
            # Fetch 1d data
            logger.info(f"  Fetching 1d data ({lookback_1d} days)...")
            klines_1d = rest_client.get_all_klines(symbol, "1d", lookback_1d)
            store.store_klines(symbol, "1d", klines_1d)
            
            # Fetch 1h data
            logger.info(f"  Fetching 1h data ({lookback_1h} days)...")
            klines_1h = rest_client.get_all_klines(symbol, "1h", lookback_1h)
            store.store_klines(symbol, "1h", klines_1h)
            
            # Show coverage
            coverage_1d = store.get_data_coverage(symbol, "1d")
            coverage_1h = store.get_data_coverage(symbol, "1h")
            
            logger.info(f"  1d coverage: {coverage_1d.get('count', 0)} candles, "
                       f"{coverage_1d.get('first_date', 'N/A')} to {coverage_1d.get('last_date', 'N/A')}")
            logger.info(f"  1h coverage: {coverage_1h.get('count', 0)} candles, "
                       f"{coverage_1h.get('first_date', 'N/A')} to {coverage_1h.get('last_date', 'N/A')}")
            
        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}")
            continue
    
    logger.info("Bootstrap complete!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap historical market data")
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Path to config.yaml"
    )
    
    args = parser.parse_args()
    bootstrap_history(args.config)
