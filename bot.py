#!/usr/bin/env python3
"""Main bot entry point."""
import time
from datetime import datetime, timezone

from bot.utils import load_config
from bot.storage import HistoryStore
from bot.engine import BotEngine
from news.engine import NewsEngine
from risk.guards import RiskGuards


def main():
    """Run the bot main loop."""
    # Load configuration
    config = load_config("config.yaml")
    
    # Initialize components
    history_store = HistoryStore(config)
    news_engine = NewsEngine(config)
    risk_guards = RiskGuards(config)
    
    # Initialize bot engine
    bot = BotEngine(
        config=config,
        history_store=history_store,
        news_engine=news_engine,
        risk_guards=risk_guards,
    )
    
    # Get execution parameters
    exec_cfg = config.get("execution", {})
    loop_seconds = exec_cfg.get("loop_seconds", 60)
    decision_every_minutes = exec_cfg.get("decision_every_minutes", 15)
    mode = exec_cfg.get("mode", "paper")
    
    print(f"🤖 Vini Cripto Spot Bot starting in {mode} mode...")
    print(f"⏱️  Decision interval: {decision_every_minutes} minutes")
    print(f"🔄 Loop interval: {loop_seconds} seconds")
    print()
    
    last_decision_time = None
    
    try:
        while True:
            now = datetime.now(timezone.utc)
            
            # Check if it's time to make a decision
            should_decide = False
            if last_decision_time is None:
                should_decide = True
            else:
                elapsed_minutes = (now - last_decision_time).total_seconds() / 60
                should_decide = elapsed_minutes >= decision_every_minutes
            
            if should_decide:
                print(f"📊 [{now.strftime('%Y-%m-%d %H:%M:%S')} UTC] Running decision cycle...")
                
                # Fetch and analyze news
                news_items = news_engine.fetch_and_analyze(now)
                print(f"📰 Fetched {len(news_items)} news items")
                
                # Execute bot step
                slot = now.strftime("%Y-%m-%d_%H:%M")
                decisions = bot.step(slot, now)
                
                # Print decisions
                for decision in decisions:
                    symbol = decision["symbol"]
                    action = decision["action"]
                    reason = decision["reason"]
                    print(f"   {symbol}: {action} - {reason}")
                
                last_decision_time = now
                print()
            
            # Sleep until next loop
            time.sleep(loop_seconds)
            
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        print(f"\n❌ Bot error: {e}")
        raise


if __name__ == "__main__":
    main()
