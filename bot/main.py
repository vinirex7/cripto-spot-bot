"""
Main entry point for Vini QuantBot v3.0.1
Includes anti-duplication scheduler to prevent multiple executions per slot.
"""
import argparse
import logging
import time
import signal
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.core import BotCore

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/bot_console.log')
    ]
)
logger = logging.getLogger(__name__)


class Scheduler:
    """
    Anti-duplication scheduler.
    
    Ensures only 1 execution per time slot (e.g., every 15 minutes).
    Uses last_slot tracking to prevent duplicates.
    """
    
    def __init__(self, interval_minutes: int = 15):
        self.interval_minutes = interval_minutes
        self.last_slot = None
        self.running = False
    
    def get_current_slot(self) -> str:
        """
        Get current time slot identifier.
        
        Returns:
            Slot identifier (e.g., "2024-01-15T14:15")
        """
        now = datetime.utcnow()
        
        # Round down to nearest interval
        minutes = (now.minute // self.interval_minutes) * self.interval_minutes
        slot_time = now.replace(minute=minutes, second=0, microsecond=0)
        
        return slot_time.strftime("%Y-%m-%dT%H:%M")
    
    def should_run(self) -> bool:
        """
        Check if bot should run in current slot.
        
        Returns:
            True if should run, False if already ran in this slot
        """
        current_slot = self.get_current_slot()
        
        if current_slot != self.last_slot:
            self.last_slot = current_slot
            return True
        
        return False
    
    def wait_for_next_slot(self):
        """Wait until the next time slot."""
        now = datetime.utcnow()
        
        # Calculate next slot time
        minutes_to_next = self.interval_minutes - (now.minute % self.interval_minutes)
        seconds_to_next = (minutes_to_next * 60) - now.second
        
        if seconds_to_next > 0:
            logger.info(f"Waiting {seconds_to_next}s for next slot...")
            time.sleep(seconds_to_next)


class BotRunner:
    """Main bot runner with graceful shutdown."""
    
    def __init__(self, config_path: str, interval_minutes: int = 15):
        self.config_path = config_path
        self.bot = BotCore(config_path)
        self.scheduler = Scheduler(interval_minutes)
        self.running = False
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.stop()
    
    def run(self):
        """Main run loop."""
        self.running = True
        logger.info("Bot started")
        
        while self.running:
            try:
                # Check if should run in this slot
                if self.scheduler.should_run():
                    current_slot = self.scheduler.last_slot
                    logger.info(f"=== Running cycle for slot {current_slot} ===")
                    
                    # Run bot cycle
                    self.bot.run_cycle()
                    
                    logger.info(f"=== Cycle completed for slot {current_slot} ===")
                else:
                    logger.debug("Already ran in this slot, skipping...")
                
                # Wait for next slot
                if self.running:
                    self.scheduler.wait_for_next_slot()
            
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                # Wait a bit before retrying
                time.sleep(60)
        
        logger.info("Bot stopped")
    
    def stop(self):
        """Stop the bot."""
        self.running = False
        self.bot.shutdown()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Vini QuantBot v3.0.1 - Spot Trading Bot"
    )
    parser.add_argument(
        '--config',
        type=str,
        default='config.yaml',
        help='Path to configuration file'
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=15,
        help='Scheduler interval in minutes (default: 15)'
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='Run once and exit (for testing)'
    )
    
    args = parser.parse_args()
    
    # Create logs directory
    Path('logs').mkdir(exist_ok=True)
    
    # Check if config exists
    if not Path(args.config).exists():
        logger.error(f"Config file not found: {args.config}")
        sys.exit(1)
    
    # Initialize bot
    try:
        if args.once:
            # Single run mode (for testing)
            logger.info("Running in single-run mode")
            bot = BotCore(args.config)
            bot.run_cycle()
            bot.shutdown()
        else:
            # Continuous mode with scheduler
            runner = BotRunner(args.config, args.interval)
            runner.run()
    
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
