"""
Performance metrics calculation for backtesting.
"""
import numpy as np
import pandas as pd
from typing import Dict, List


def calculate_returns(equity_curve: pd.Series) -> pd.Series:
    """Calculate returns from equity curve."""
    return equity_curve.pct_change().dropna()


def calculate_cumulative_return(equity_curve: pd.Series) -> float:
    """Calculate cumulative return."""
    if len(equity_curve) < 2:
        return 0.0
    return (equity_curve.iloc[-1] / equity_curve.iloc[0]) - 1.0


def calculate_max_drawdown(equity_curve: pd.Series) -> float:
    """
    Calculate maximum drawdown from equity curve.
    
    Returns:
        Maximum drawdown as a positive percentage (e.g., 0.15 for 15% DD)
    """
    if len(equity_curve) < 2:
        return 0.0
    
    cummax = equity_curve.cummax()
    drawdown = (equity_curve - cummax) / cummax
    max_dd = drawdown.min()
    
    return abs(max_dd)


def calculate_sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    """
    Calculate Sharpe ratio.
    
    Args:
        returns: Series of returns
        risk_free_rate: Annual risk-free rate (default 0.0)
    
    Returns:
        Annualized Sharpe ratio
    """
    if len(returns) < 2:
        return 0.0
    
    excess_returns = returns - (risk_free_rate / 252)  # Daily risk-free rate
    
    if excess_returns.std() == 0:
        return 0.0
    
    sharpe = excess_returns.mean() / excess_returns.std()
    
    # Annualize (assuming daily returns)
    sharpe_annual = sharpe * np.sqrt(252)
    
    return sharpe_annual


def calculate_sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    """
    Calculate Sortino ratio (uses downside deviation).
    
    Returns:
        Annualized Sortino ratio
    """
    if len(returns) < 2:
        return 0.0
    
    excess_returns = returns - (risk_free_rate / 252)
    
    # Downside deviation (only negative returns)
    downside_returns = returns[returns < 0]
    
    if len(downside_returns) == 0 or downside_returns.std() == 0:
        return 0.0
    
    sortino = excess_returns.mean() / downside_returns.std()
    
    # Annualize
    sortino_annual = sortino * np.sqrt(252)
    
    return sortino_annual


def calculate_hit_rate(trades: List[Dict]) -> float:
    """
    Calculate hit rate (percentage of winning trades).
    
    Args:
        trades: List of trade dictionaries with 'pnl' field
    
    Returns:
        Hit rate as percentage (0 to 100)
    """
    if not trades:
        return 0.0
    
    winning_trades = sum(1 for t in trades if t.get('pnl', 0) > 0)
    total_trades = len(trades)
    
    return (winning_trades / total_trades) * 100


def calculate_profit_factor(trades: List[Dict]) -> float:
    """
    Calculate profit factor (gross profit / gross loss).
    
    Returns:
        Profit factor (>1 means profitable)
    """
    if not trades:
        return 0.0
    
    gross_profit = sum(t.get('pnl', 0) for t in trades if t.get('pnl', 0) > 0)
    gross_loss = abs(sum(t.get('pnl', 0) for t in trades if t.get('pnl', 0) < 0))
    
    if gross_loss == 0:
        return float('inf') if gross_profit > 0 else 0.0
    
    return gross_profit / gross_loss


def calculate_average_trade(trades: List[Dict]) -> float:
    """Calculate average P&L per trade."""
    if not trades:
        return 0.0
    
    total_pnl = sum(t.get('pnl', 0) for t in trades)
    return total_pnl / len(trades)


def calculate_turnover(trades: List[Dict], initial_capital: float) -> float:
    """
    Calculate turnover (total value traded / capital).
    
    Returns:
        Annualized turnover ratio
    """
    if not trades:
        return 0.0
    
    total_value_traded = sum(
        t.get('entry_price', 0) * t.get('quantity', 0) 
        for t in trades
    )
    
    return total_value_traded / initial_capital


def calculate_average_holding_period(trades: List[Dict]) -> float:
    """
    Calculate average holding period in hours.
    
    Args:
        trades: List of trade dictionaries with 'entry_time' and 'exit_time'
    
    Returns:
        Average holding period in hours
    """
    if not trades:
        return 0.0
    
    holding_periods = []
    
    for trade in trades:
        if 'entry_time' in trade and 'exit_time' in trade:
            try:
                entry = pd.to_datetime(trade['entry_time'])
                exit = pd.to_datetime(trade['exit_time'])
                hours = (exit - entry).total_seconds() / 3600
                holding_periods.append(hours)
            except:
                continue
    
    if not holding_periods:
        return 0.0
    
    return np.mean(holding_periods)


def generate_metrics_summary(
    equity_curve: pd.Series,
    trades: List[Dict],
    initial_capital: float = 10000.0
) -> Dict:
    """
    Generate comprehensive metrics summary.
    
    Args:
        equity_curve: Equity curve Series indexed by datetime
        trades: List of completed trades
        initial_capital: Initial capital amount
    
    Returns:
        Dictionary of performance metrics
    """
    returns = calculate_returns(equity_curve)
    
    metrics = {
        # Returns
        'total_return_pct': calculate_cumulative_return(equity_curve) * 100,
        'final_equity': equity_curve.iloc[-1] if len(equity_curve) > 0 else initial_capital,
        'total_pnl': equity_curve.iloc[-1] - initial_capital if len(equity_curve) > 0 else 0.0,
        
        # Risk
        'max_drawdown_pct': calculate_max_drawdown(equity_curve) * 100,
        'sharpe_ratio': calculate_sharpe_ratio(returns),
        'sortino_ratio': calculate_sortino_ratio(returns),
        
        # Trading
        'total_trades': len(trades),
        'hit_rate_pct': calculate_hit_rate(trades),
        'profit_factor': calculate_profit_factor(trades),
        'avg_trade_pnl': calculate_average_trade(trades),
        'avg_holding_hours': calculate_average_holding_period(trades),
        
        # Activity
        'turnover_ratio': calculate_turnover(trades, initial_capital),
        
        # Period
        'start_date': equity_curve.index[0].strftime('%Y-%m-%d') if len(equity_curve) > 0 else 'N/A',
        'end_date': equity_curve.index[-1].strftime('%Y-%m-%d') if len(equity_curve) > 0 else 'N/A',
        'trading_days': len(equity_curve) if len(equity_curve) > 0 else 0
    }
    
    return metrics


def print_metrics_summary(metrics: Dict):
    """Print metrics in a formatted table."""
    print("\n" + "="*60)
    print(" BACKTEST PERFORMANCE METRICS")
    print("="*60)
    
    print(f"\n📈 Returns")
    print(f"   Total Return:        {metrics['total_return_pct']:>10.2f}%")
    print(f"   Final Equity:        ${metrics['final_equity']:>10,.2f}")
    print(f"   Total P&L:           ${metrics['total_pnl']:>10,.2f}")
    
    print(f"\n📉 Risk")
    print(f"   Max Drawdown:        {metrics['max_drawdown_pct']:>10.2f}%")
    print(f"   Sharpe Ratio:        {metrics['sharpe_ratio']:>10.2f}")
    print(f"   Sortino Ratio:       {metrics['sortino_ratio']:>10.2f}")
    
    print(f"\n💰 Trading")
    print(f"   Total Trades:        {metrics['total_trades']:>10}")
    print(f"   Hit Rate:            {metrics['hit_rate_pct']:>10.2f}%")
    print(f"   Profit Factor:       {metrics['profit_factor']:>10.2f}")
    print(f"   Avg Trade P&L:       ${metrics['avg_trade_pnl']:>10,.2f}")
    print(f"   Avg Holding:         {metrics['avg_holding_hours']:>10.1f}h")
    
    print(f"\n📊 Activity")
    print(f"   Turnover Ratio:      {metrics['turnover_ratio']:>10.2f}x")
    
    print(f"\n📅 Period")
    print(f"   Start Date:          {metrics['start_date']:>12}")
    print(f"   End Date:            {metrics['end_date']:>12}")
    print(f"   Trading Days:        {metrics['trading_days']:>10}")
    
    print("\n" + "="*60 + "\n")
