"""
Core bot pipeline orchestration.
Integrates all components into a single decision-making engine.
"""
import yaml
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import logging

# Import all components
from data.history_store import HistoryStore
from data.binance_rest import BinanceRESTClient
from signals.momentum import MomentumSignal
from signals.microstructure import MicrostructureSignals
from signals.regime import RegimeDetector
from news.cryptopanic import CryptoPanicClient
from news.sentiment_quant import QuantitativeSentiment
from ai.openai_client import OpenAIClient
from ai.news_analyzer import NewsAnalyzer
from ai.explainer import Explainer
from risk.guards import Guards
from risk.news_shock import NewsShockV3
from risk.position_sizing import PositionSizer
from risk.dynamic_params import DynamicParams
from execution.orders import OrderExecutor
from storage.db import Database
from storage.log_writer import LogWriter

logger = logging.getLogger(__name__)


class BotCore:
    """
    Core bot engine that orchestrates all components.
    
    This is where everything comes together:
    1. Fetch market data
    2. Generate signals (momentum, microstructure, regime)
    3. Fetch and analyze news
    4. Apply risk checks
    5. Size positions
    6. Execute trades
    7. Log everything
    """
    
    def __init__(self, config_path: str):
        """Initialize bot with configuration."""
        # Load config
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.universe = self.config.get('universe', [])
        self.mode = self.config.get('mode', 'paper')
        
        # Initialize components
        logger.info("Initializing bot components...")
        
        # Data
        history_config = self.config.get('history', {})
        self.history_store = HistoryStore(history_config.get('db_path'))
        self.binance_client = BinanceRESTClient()
        
        # Signals
        self.momentum_signal = MomentumSignal(self.config.get('momentum', {}))
        self.microstructure = MicrostructureSignals(self.config.get('microstructure', {}))
        self.regime_detector = RegimeDetector(self.config.get('regime', {}))
        
        # News
        self.news_client = CryptoPanicClient()
        self.quant_sentiment = QuantitativeSentiment(self.config.get('news', {}))
        
        # AI
        openai_config = self.config.get('openai', {})
        self.openai_client = OpenAIClient(openai_config)
        self.news_analyzer = NewsAnalyzer(self.openai_client)
        self.explainer = Explainer(self.openai_client)
        
        # Risk
        self.guards = Guards(self.config)
        self.news_shock = NewsShockV3(self.config)
        self.position_sizer = PositionSizer(self.config)
        self.dynamic_params = DynamicParams(self.config)
        
        # Execution
        self.executor = OrderExecutor(self.config, mode=self.mode)
        
        # Storage
        storage_config = self.config.get('storage', {})
        self.db = Database(storage_config.get('positions_db_path'))
        self.log_writer = LogWriter(storage_config.get('log_path'))
        
        # Bootstrap config
        self.bootstrap_config = self.config.get('bootstrap', {})
        
        logger.info(f"Bot initialized in {self.mode} mode")
        self.log_writer.log_bot_start(self.config)
    
    def run_cycle(self):
        """
        Run one complete bot cycle.
        
        This is the main loop that:
        1. Analyzes each symbol
        2. Makes decisions
        3. Executes trades
        """
        current_time = datetime.utcnow()
        logger.info(f"Starting bot cycle at {current_time}")
        
        # Get open positions
        open_positions = self.db.get_open_positions()
        open_positions_dict = {p['symbol']: p for p in open_positions}
        
        # Fetch news for all symbols
        news_by_symbol = self._fetch_news()
        
        # Analyze each symbol
        for symbol in self.universe:
            try:
                self._analyze_symbol(symbol, open_positions_dict, news_by_symbol, current_time)
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}")
                self.log_writer.log_error('analysis_error', str(e), {'symbol': symbol})
        
        # Log heartbeat
        self._log_heartbeat(open_positions)
        
        logger.info("Bot cycle completed")
    
    def _fetch_news(self) -> Dict[str, List[Dict]]:
        """Fetch news for all symbols."""
        try:
            return self.news_client.get_news_for_symbols(self.universe)
        except Exception as e:
            logger.error(f"Error fetching news: {e}")
            return {symbol: [] for symbol in self.universe}
    
    def _analyze_symbol(
        self,
        symbol: str,
        open_positions: Dict,
        news_by_symbol: Dict,
        current_time: datetime
    ):
        """
        Analyze a single symbol and make trading decision.
        
        This is where all the magic happens.
        """
        logger.info(f"Analyzing {symbol}...")
        
        # 1. Get market data
        df_1d = self.history_store.get_klines(symbol, '1d')
        df_1h = self.history_store.get_klines(symbol, '1h')
        
        if df_1d.empty or df_1h.empty:
            logger.warning(f"Insufficient data for {symbol}")
            return
        
        current_price = df_1d['close'].iloc[-1]
        
        # 2. Calculate momentum signals
        momentum_metrics = self.momentum_signal.calculate_signals(df_1d)
        
        # 3. Bootstrap validation (only on 1d data)
        bootstrap_metrics = None
        if self.bootstrap_config.get('enabled', True):
            bootstrap_metrics = self.momentum_signal.block_bootstrap(
                df_1d,
                block_size=self.bootstrap_config.get('block_size_days', 7),
                n_resamples=self.bootstrap_config.get('n_resamples', 400)
            )
            
            passes_bootstrap = self.momentum_signal.check_bootstrap_gate(
                bootstrap_metrics,
                min_pwin=self.bootstrap_config.get('min_pwin', 0.60)
            )
            
            if not passes_bootstrap:
                logger.info(f"{symbol}: Failed bootstrap gate (p_win={bootstrap_metrics['p_win_mom']:.2f})")
                self.log_writer.log_decision(
                    symbol, 'hold', 'Failed bootstrap gate', {'bootstrap': bootstrap_metrics}
                )
                return
        
        # 4. Get order book for microstructure
        order_book = self.binance_client.get_order_book(symbol, limit=10)
        if not order_book or 'bids' not in order_book or 'asks' not in order_book:
            logger.warning(f"No order book data for {symbol}")
            return
        
        bid_price = float(order_book['bids'][0][0])
        ask_price = float(order_book['asks'][0][0])
        
        # 5. Microstructure checks
        micro_metrics = self.microstructure.get_microstructure_metrics(
            current_price, bid_price, ask_price, df_1h
        )
        
        # 6. Regime detection (need BTC data)
        df_btc_1d = self.history_store.get_klines('BTCUSDT', '1d')
        alt_dfs = {}
        for alt_symbol in self.universe:
            if alt_symbol != 'BTCUSDT':
                alt_dfs[alt_symbol] = self.history_store.get_klines(alt_symbol, '1d')
        
        regime_metrics = self.regime_detector.detect_regime(df_btc_1d, alt_dfs)
        
        # Check if regime blocks trading (effective risk reduction)
        if regime_metrics.get('block_trading', False):
            logger.warning(f"{symbol}: High correlation regime detected - blocking trades")
            
            # Force exit existing position if any
            if symbol in open_positions:
                self._force_exit_position(
                    symbol, open_positions[symbol], current_price, 
                    'High correlation regime exit'
                )
            
            self.log_writer.log_decision(
                symbol, 'blocked', 'High correlation regime', {'regime': regime_metrics}
            )
            return  # Block new entries
        
        # 7. News analysis
        news_items = news_by_symbol.get(symbol, [])
        news_metrics = self._analyze_news(symbol, news_items, df_1h, current_time)
        
        # 8. Check if paused
        if news_metrics.get('is_paused', False):
            logger.info(f"{symbol}: Trading paused - {news_metrics.get('pause_reason', 'Unknown')}")
            
            # Check if should force exit existing position
            if symbol in open_positions:
                self._force_exit_position(symbol, open_positions[symbol], current_price, 'News pause')
            
            return
        
        # 9. Risk guards
        position_data = open_positions.get(symbol)
        guard_results = self.guards.check_all_guards(micro_metrics, position_data)
        
        if not guard_results['guards_pass']:
            logger.info(f"{symbol}: Failed risk guards - {guard_results['reasons']}")
            
            # Force exit if necessary
            if position_data and self.guards.should_force_exit(position_data, micro_metrics, 0.0):
                self._force_exit_position(symbol, position_data, current_price, 'Risk guard failure')
            
            return
        
        # 10. Make decision
        self._make_decision(
            symbol, momentum_metrics, micro_metrics, regime_metrics,
            news_metrics, position_data, current_price, current_time
        )
    
    def _analyze_news(
        self,
        symbol: str,
        news_items: List[Dict],
        df_1h: pd.DataFrame,
        current_time: datetime
    ) -> Dict:
        """Analyze news with quant + LLM."""
        # Quantitative sentiment
        quant_metrics = self.quant_sentiment.process_news_for_symbol(
            symbol, news_items, current_time
        )
        
        # LLM analysis (if enabled)
        llm_sentiment = 0.0
        llm_confidence = 0.0
        llm_category = 'general'
        
        if self.openai_client.is_enabled() and news_items:
            # Analyze top news item
            top_news = news_items[0]
            llm_result = self.news_analyzer.analyze_news_item(
                top_news.get('title', ''),
                top_news.get('source', ''),
                symbol
            )
            llm_sentiment = llm_result.get('sentiment', 0.0)
            llm_confidence = llm_result.get('confidence', 0.0)
            llm_category = llm_result.get('category', 'general')
        
        # NewsShock v3 analysis
        news_shock_metrics = self.news_shock.analyze_news_shock(
            symbol,
            quant_metrics['sentiment_z'],
            llm_sentiment,
            llm_confidence,
            llm_category,
            df_1h,
            current_time
        )
        
        return {
            'quant': quant_metrics,
            'llm_sentiment': llm_sentiment,
            'llm_confidence': llm_confidence,
            'llm_category': llm_category,
            'news_shock': news_shock_metrics,
            'is_paused': news_shock_metrics.get('is_paused', False),
            'pause_reason': news_shock_metrics.get('pause_info', {}).get('reason', '')
        }
    
    def _make_decision(
        self,
        symbol: str,
        momentum_metrics: Dict,
        micro_metrics: Dict,
        regime_metrics: Dict,
        news_metrics: Dict,
        position_data: Optional[Dict],
        current_price: float,
        current_time: datetime
    ):
        """Make trading decision based on all signals."""
        signal = momentum_metrics.get('signal', 0)
        
        # If we have an open position
        if position_data:
            # Check exit conditions
            if signal == -1:
                self._exit_position(symbol, position_data, current_price, 'Momentum exit signal')
            else:
                logger.info(f"{symbol}: Holding position")
        else:
            # Check entry conditions
            if signal == 1:
                self._enter_position(
                    symbol, momentum_metrics, micro_metrics,
                    regime_metrics, news_metrics, current_price, current_time
                )
            else:
                logger.info(f"{symbol}: No entry signal")
    
    def _enter_position(
        self,
        symbol: str,
        momentum_metrics: Dict,
        micro_metrics: Dict,
        regime_metrics: Dict,
        news_metrics: Dict,
        current_price: float,
        current_time: datetime
    ):
        """Enter a new position."""
        # Get account info (paper mode uses dummy value)
        if self.mode == 'paper':
            account_value = 10000.0  # $10k paper account
        else:
            account_info = self.binance_client.get_account_info()
            if not account_info:
                logger.error("Failed to get account info")
                return
            # Calculate account value from balances
            account_value = 10000.0  # Placeholder
        
        # Calculate position size
        df_1d = self.history_store.get_klines(symbol, '1d')
        realized_vol = self.position_sizer.calculate_realized_vol(df_1d)
        
        existing_positions = len(self.db.get_open_positions())
        
        sizing = self.position_sizer.calculate_position_size(
            account_value, current_price, realized_vol, existing_positions
        )
        
        # Adjust for regime
        sizing = self.position_sizer.adjust_for_regime(sizing, regime_metrics)
        
        if not sizing['can_trade']:
            logger.info(f"{symbol}: Cannot trade - {sizing['reason']}")
            return
        
        # Execute buy
        quantity = sizing['size_units']
        
        result = self.executor.execute_buy(
            symbol, quantity, current_price, 'LIMIT',
            reason=f"Momentum signal (M={momentum_metrics['M_short']:.2f})"
        )
        
        if result['success']:
            # Record position in DB
            self.db.open_position(
                symbol, 'BUY', current_price, quantity,
                entry_reason='Momentum signal',
                metadata={
                    'momentum': momentum_metrics,
                    'sizing': sizing
                }
            )
            
            # Log
            self.log_writer.log_trade(
                symbol, 'BUY', quantity, current_price, 'LIMIT',
                'Momentum signal', True
            )
            
            logger.info(f"{symbol}: Position opened - qty={quantity:.6f} @ ${current_price:.2f}")
    
    def _exit_position(
        self,
        symbol: str,
        position_data: Dict,
        current_price: float,
        reason: str
    ):
        """Exit an existing position."""
        quantity = position_data['quantity']
        
        result = self.executor.execute_sell(
            symbol, quantity, current_price, 'LIMIT',
            reason=reason, is_risk_exit=False
        )
        
        if result['success']:
            # Close position in DB
            self.db.close_position(position_data['id'], current_price, reason)
            
            # Log
            self.log_writer.log_trade(
                symbol, 'SELL', quantity, current_price, 'LIMIT',
                reason, True
            )
            
            logger.info(f"{symbol}: Position closed - {reason}")
    
    def _force_exit_position(
        self,
        symbol: str,
        position_data: Dict,
        current_price: float,
        reason: str
    ):
        """Force exit using MARKET order."""
        quantity = position_data['quantity']
        
        result = self.executor.execute_sell(
            symbol, quantity, None, 'MARKET',
            reason=reason, is_risk_exit=True
        )
        
        if result['success']:
            self.db.close_position(position_data['id'], current_price, reason)
            self.log_writer.log_trade(
                symbol, 'SELL', quantity, current_price, 'MARKET',
                reason, True
            )
            logger.warning(f"{symbol}: Position force-closed - {reason}")
    
    def _log_heartbeat(self, open_positions: List[Dict]):
        """Log periodic heartbeat."""
        self.log_writer.log_heartbeat({
            'num_positions': len(open_positions),
            'mode': self.mode,
            'openai_enabled': self.openai_client.is_enabled(),
            'openai_stats': self.openai_client.get_usage_stats()
        })
    
    def shutdown(self):
        """Gracefully shutdown bot."""
        logger.info("Shutting down bot...")
        self.log_writer.log_bot_stop('Normal shutdown')
