import argparse

from bot.core import BotCore
from data.backfill import run_backfill


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap market history.")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML")
    parser.add_argument("--all", action="store_true", help="Backfill all assets")
    args = parser.parse_args()

    bot = BotCore(args.config)
    if args.all:
        run_backfill(bot.config, bot.history_store)
    else:
        bot.bootstrap()


if __name__ == "__main__":
    main()
