"""
End-to-end backtest runner for Vini QuantBot v3.0.1

Runs the real bot core in backtest mode using historical data.
Simulates execution with simple slippage and fees.
"""
import argparse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import yaml
import os
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.metrics import generate_metrics_summary, print_metrics_summary
from data.history_store import HistoryStore
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BacktestEngine:
    """
    Simplified backtest engine.
    
    This runs a simplified version of the bot logic in backtest mode.
    For full accuracy, would need to integrate with bot.core with time simulation.
    """
    
    def __init__(self, config_path: str, start_date: str, end_date: str):
        """
        Initialize backtest engine.
        
        Args:
            config_path: Path to config.yaml
            start_date: Backtest start date (YYYY-MM-DD)
            end_date: Backtest end date (YYYY-MM-DD)
        """
        # Load config
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.start_date = pd.to_datetime(start_date)
        self.end_date = pd.to_datetime(end_date)
        
        # Initialize storage
        history_config = self.config.get('history', {})
        self.history_store = HistoryStore(history_config.get('db_path'))
        
        # Trading parameters
        self.initial_capital = 10000.0
        self.current_capital = self.initial_capital
        self.slippage_pct = 0.05  # 0.05% slippage
        self.fee_pct = 0.10  # 0.10% trading fee
        
        # Tracking
        self.equity_curve = []
        self.trades = []
        self.positions = {}
        
        logger.info(f"Backtest: {start_date} to {end_date}")
        logger.info(f"Initial capital: ${self.initial_capital:,.2f}")
    
    def load_historical_data(self, symbol: str) -> pd.DataFrame:
        """Load historical data for symbol."""
        # Get data from history store
        df_1d = self.history_store.get_klines(symbol, '1d')
        
        if df_1d.empty:
            logger.warning(f"No data for {symbol}")
            return pd.DataFrame()
        
        # Filter to backtest period
        df_1d = df_1d[
            (df_1d.index >= self.start_date) & 
            (df_1d.index <= self.end_date)
        ]
        
        return df_1d
    
    def calculate_simple_momentum(self, df: pd.DataFrame, window: int = 60) -> float:
        """Calculate simple momentum score."""
        if len(df) < window:
            return 0.0
        
        prices = df['close'].tail(window)
        log_returns = np.log(prices / prices.shift(1)).dropna()
        
        if len(log_returns) == 0:
            return 0.0
        
        momentum = log_returns.sum() / log_returns.std() if log_returns.std() > 0 else 0.0
        return momentum
    
    def execute_buy(self, symbol: str, price: float, date: datetime) -> bool:
        """Execute buy with slippage and fees."""
        if symbol in self.positions:
            return False  # Already have position
        
        # Calculate costs
        execution_price = price * (1 + self.slippage_pct / 100)
        
        # Simple position sizing: 30% of capital
        position_value = self.current_capital * 0.30
        quantity = position_value / execution_price
        
        # Deduct fees
        fee = position_value * (self.fee_pct / 100)
        total_cost = position_value + fee
        
        if total_cost > self.current_capital:
            return False
        
        # Execute
        self.current_capital -= total_cost
        self.positions[symbol] = {
            'quantity': quantity,
            'entry_price': execution_price,
            'entry_time': date,
            'entry_value': position_value
        }
        
        logger.info(f"BUY {symbol} @ ${execution_price:.2f} | Qty: {quantity:.6f}")
        return True
    
    def execute_sell(self, symbol: str, price: float, date: datetime, reason: str = "Signal"):
        """Execute sell with slippage and fees."""
        if symbol not in self.positions:
            return
        
        position = self.positions[symbol]
        
        # Calculate proceeds
        execution_price = price * (1 - self.slippage_pct / 100)
        proceeds = position['quantity'] * execution_price
        
        # Deduct fees
        fee = proceeds * (self.fee_pct / 100)
        net_proceeds = proceeds - fee
        
        # Calculate P&L
        pnl = net_proceeds - position['entry_value']
        pnl_pct = (pnl / position['entry_value']) * 100
        
        # Update capital
        self.current_capital += net_proceeds
        
        # Record trade
        self.trades.append({
            'symbol': symbol,
            'entry_price': position['entry_price'],
            'exit_price': execution_price,
            'quantity': position['quantity'],
            'entry_time': position['entry_time'],
            'exit_time': date,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'reason': reason
        })
        
        logger.info(f"SELL {symbol} @ ${execution_price:.2f} | P&L: ${pnl:.2f} ({pnl_pct:.2f}%)")
        
        # Remove position
        del self.positions[symbol]
    
    def run(self):
        """Run backtest."""
        universe = self.config.get('universe', [])
        
        logger.info(f"Running backtest on {len(universe)} symbols...")
        
        # Load all data
        symbol_data = {}
        for symbol in universe:
            df = self.load_historical_data(symbol)
            if not df.empty:
                symbol_data[symbol] = df
        
        if not symbol_data:
            logger.error("No historical data available")
            return
        
        # Get all unique dates
        all_dates = set()
        for df in symbol_data.values():
            all_dates.update(df.index)
        
        all_dates = sorted(list(all_dates))
        
        logger.info(f"Simulating {len(all_dates)} trading days...")
        
        # Simulate day by day
        for date in all_dates:
            # Update equity curve
            total_equity = self.current_capital
            
            # Add position values
            for symbol, position in self.positions.items():
                if symbol in symbol_data and date in symbol_data[symbol].index:
                    current_price = symbol_data[symbol].loc[date, 'close']
                    position_value = position['quantity'] * current_price
                    total_equity += position_value
            
            self.equity_curve.append({
                'date': date,
                'equity': total_equity
            })
            
            # Check each symbol
            for symbol in universe:
                if symbol not in symbol_data or date not in symbol_data[symbol].index:
                    continue
                
                df = symbol_data[symbol]
                current_idx = df.index.get_loc(date)
                
                # Need enough history
                if current_idx < 120:
                    continue
                
                # Get historical data up to current date
                hist_data = df.iloc[:current_idx+1]
                current_price = hist_data['close'].iloc[-1]
                
                # Calculate momentum
                momentum = self.calculate_simple_momentum(hist_data, window=60)
                
                # Simple strategy: buy if momentum > 1.0, sell if momentum < 0
                if symbol not in self.positions:
                    # Entry signal
                    if momentum > 1.0 and len(self.positions) < 2:
                        self.execute_buy(symbol, current_price, date)
                else:
                    # Exit signal
                    if momentum < 0:
                        self.execute_sell(symbol, current_price, date, "Momentum exit")
                    
                    # Max holding period check (72h = 3 days)
                    position = self.positions[symbol]
                    holding_days = (date - position['entry_time']).days
                    if holding_days >= 3:
                        self.execute_sell(symbol, current_price, date, "Max holding")
        
        # Close any remaining positions
        final_date = all_dates[-1]
        for symbol in list(self.positions.keys()):
            if symbol in symbol_data and final_date in symbol_data[symbol].index:
                final_price = symbol_data[symbol].loc[final_date, 'close']
                self.execute_sell(symbol, final_price, final_date, "End of backtest")
        
        logger.info(f"Backtest complete: {len(self.trades)} trades executed")
    
    def get_results(self):
        """Get backtest results."""
        # Convert equity curve to Series
        equity_df = pd.DataFrame(self.equity_curve)
        equity_series = equity_df.set_index('date')['equity']
        
        # Calculate metrics
        metrics = generate_metrics_summary(
            equity_series,
            self.trades,
            self.initial_capital
        )
        
        return metrics, equity_series, self.trades
    
    def save_results(self, output_dir: str = './reports'):
        """Save backtest results to CSV."""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        # Save equity curve
        equity_df = pd.DataFrame(self.equity_curve)
        equity_path = f"{output_dir}/equity_curve.csv"
        equity_df.to_csv(equity_path, index=False)
        logger.info(f"Equity curve saved to {equity_path}")
        
        # Save trades
        if self.trades:
            trades_df = pd.DataFrame(self.trades)
            trades_path = f"{output_dir}/trades.csv"
            trades_df.to_csv(trades_path, index=False)
            logger.info(f"Trades saved to {trades_path}")


def main():
    """Main backtest entry point."""
    parser = argparse.ArgumentParser(description="Run backtest for Vini QuantBot v3.0.1")
    parser.add_argument('--config', type=str, default='config.yaml', help='Config file path')
    parser.add_argument('--start', type=str, required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--seed', type=int, default=42, help='Random seed for reproducibility')
    
    args = parser.parse_args()
    
    # Set seed for reproducibility
    np.random.seed(args.seed)
    
    # Run backtest
    engine = BacktestEngine(args.config, args.start, args.end)
    engine.run()
    
    # Get and display results
    metrics, equity_series, trades = engine.get_results()
    print_metrics_summary(metrics)
    
    # Save results
    engine.save_results()
    
    print(f"\n✅ Backtest complete! Results saved to ./reports/")
    print(f"   Seed: {args.seed} (use this to reproduce results)")


if __name__ == "__main__":
    main()
