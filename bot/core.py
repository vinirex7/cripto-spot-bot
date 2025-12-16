# bot/core.py
"""
Core bot pipeline orchestration.
Integrates all components into a single decision-making engine.
"""

import yaml
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime
import logging

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
    """Core bot engine that orchestrates all components."""

    def __init__(self, config_path: str):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        self.universe = self.config.get('universe', [])
        self.mode = self.config.get('mode', 'paper')

        # Data
        self.history_store = HistoryStore(self.config['history']['db_path'])
        self.binance_client = BinanceRESTClient()

        # Signals
        self.momentum_signal = MomentumSignal(self.config.get('momentum', {}))
        self.microstructure = MicrostructureSignals(self.config.get('microstructure', {}))
        self.regime_detector = RegimeDetector(self.config.get('regime', {}))

        # News
        self.news_client = CryptoPanicClient()
        self.quant_sentiment = QuantitativeSentiment(self.config.get('news', {}))

        # AI
        openai_cfg = self.config.get('openai', {})
        self.openai_client = OpenAIClient(openai_cfg)
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
        self.db = Database(self.config['storage']['positions_db_path'])
        self.log_writer = LogWriter(self.config['storage']['log_path'])

        logger.info(f"Bot initialized in {self.mode} mode")
        self.log_writer.log_bot_start(self.config)

    def run_cycle(self):
        now = datetime.utcnow()
        open_positions = {p['symbol']: p for p in self.db.get_open_positions()}
        news_by_symbol = self._fetch_news()

        for symbol in self.universe:
            try:
                self._analyze_symbol(symbol, open_positions, news_by_symbol, now)
            except Exception as e:
                logger.exception(f"Error analyzing {symbol}")
                self.log_writer.log_error("analysis_error", str(e), {"symbol": symbol})

        self._log_heartbeat(open_positions.values())

    def _fetch_news(self) -> Dict[str, List[Dict]]:
        try:
            return self.news_client.get_news_for_symbols(self.universe)
        except Exception:
            return {s: [] for s in self.universe}

    def _analyze_symbol(self, symbol, open_positions, news_by_symbol, now):
        df_1d = self.history_store.get_klines(symbol, '1d')
        df_1h = self.history_store.get_klines(symbol, '1h')

        if df_1d.empty or df_1h.empty:
            return

        current_price = df_1d['close'].iloc[-1]

        # 1️⃣ Momentum (já inclui bootstrap)
        momentum_metrics = self.momentum_signal.calculate_signals(df_1d)

        # 2️⃣ Order book + microstructure
        book = self.binance_client.get_order_book(symbol, limit=10)
        if not book:
            return

        bid = float(book['bids'][0][0])
        ask = float(book['asks'][0][0])

        micro_metrics = self.microstructure.get_microstructure_metrics(
            current_price, bid, ask, df_1h
        )

        # 3️⃣ Regime
        btc_df = self.history_store.get_klines('BTCUSDT', '1d')
        alt_dfs = {s: self.history_store.get_klines(s, '1d') for s in self.universe if s != 'BTCUSDT'}
        regime_metrics = self.regime_detector.detect_regime(btc_df, alt_dfs)

        if regime_metrics.get('block_trading', False):
            if symbol in open_positions:
                self._force_exit_position(
                    symbol, open_positions[symbol], current_price,
                    "High correlation regime exit"
                )
            return

        # 4️⃣ News + shock
        news_metrics = self._analyze_news(symbol, news_by_symbol.get(symbol, []), df_1h, now)

        if news_metrics.get('is_paused', False):
            if symbol in open_positions:
                self._force_exit_position(
                    symbol, open_positions[symbol], current_price,
                    news_metrics.get('pause_reason', 'News pause')
                )
            return

        # 5️⃣ Guards
        position_data = open_positions.get(symbol)
        guards = self.guards.check_all_guards(micro_metrics, position_data)

        if not guards['guards_pass']:
            if position_data and self.guards.should_force_exit(position_data, micro_metrics, 0.0):
                self._force_exit_position(symbol, position_data, current_price, "Risk guard")
            return

        # 6️⃣ Decision
        self._make_decision(
            symbol, momentum_metrics, micro_metrics,
            regime_metrics, news_metrics,
            position_data, current_price, now
        )

    def _make_decision(
        self, symbol, momentum, micro, regime, news,
        position_data, price, now
    ):
        signal = momentum.get("signal", 0)

        if position_data:
            if signal == -1:
                self._exit_position(symbol, position_data, price, "Momentum exit")
        else:
            if signal == 1:
                self._enter_position(symbol, momentum, micro, regime, news, price, now)

    def _enter_position(self, symbol, momentum, micro, regime, news, price, now):
        account_value = 10000.0 if self.mode == 'paper' else 10000.0

        df_1d = self.history_store.get_klines(symbol, '1d')
        vol = self.position_sizer.calculate_realized_vol(df_1d)

        sizing = self.position_sizer.calculate_position_size(
            account_value, price, vol, len(self.db.get_open_positions())
        )

        if not sizing['can_trade']:
            return

        qty = sizing['size_units']

        result = self.executor.execute_buy(
            symbol, qty, price, 'LIMIT',
            reason=f"Momentum 2.0 (ΔM={momentum['delta_M']:.2f}, p_win={momentum['bootstrap']['p_win_mom']:.2f})"
        )

        if result['success']:
            self.db.open_position(
                symbol, 'BUY', price, qty,
                entry_reason='Momentum 2.0',
                metadata={'momentum': momentum, 'sizing': sizing}
            )
            self.log_writer.log_trade(symbol, 'BUY', qty, price, 'LIMIT', 'Momentum entry', True)

    def _exit_position(self, symbol, pos, price, reason):
        qty = pos['quantity']
        result = self.executor.execute_sell(symbol, qty, price, 'LIMIT', reason, False)
        if result['success']:
            self.db.close_position(pos['id'], price, reason)
            self.log_writer.log_trade(symbol, 'SELL', qty, price, 'LIMIT', reason, True)

    def _force_exit_position(self, symbol, pos, price, reason):
        qty = pos['quantity']
        result = self.executor.execute_sell(symbol, qty, None, 'MARKET', reason, True)
        if result['success']:
            self.db.close_position(pos['id'], price, reason)
            self.log_writer.log_trade(symbol, 'SELL', qty, price, 'MARKET', reason, True)

    def _log_heartbeat(self, open_positions):
        self.log_writer.log_heartbeat({
            'num_positions': len(list(open_positions)),
            'mode': self.mode,
            'openai_enabled': self.openai_client.is_enabled()
        })
