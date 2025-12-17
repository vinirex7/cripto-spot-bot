"""
Momentum 2.0 signal with age-based decay and bootstrap validation.
"""

import pandas as pd
import numpy as np
from typing import Dict
import logging

logger = logging.getLogger(__name__)


class MomentumSignal:
    """
    Momentum 2.0 signal generator with age-based decay.

    Formula: M = sum(log_returns) / sigma
    """

    def __init__(self, config: Dict):
        self.short_window = config.get('short_window', 60)
        self.mid_window = config.get('mid_window', 90)
        self.long_window = config.get('long_window', 120)
        self.sma_window = config.get('sma_window', 50)

        age_decay = config.get('age_decay', {})
        self.age_excellent = age_decay.get('excellent', 12)
        self.age_good = age_decay.get('good', 15)
        self.age_fair = age_decay.get('fair', 18)

        entry = config.get('entry', {})
        self.min_age_factor = entry.get('min_age_factor', 0.5)
        self.min_delta_m = entry.get('min_delta_m', 0.0)

        exit_cfg = config.get('exit', {})
        self.use_sma_exit = exit_cfg.get('use_sma_exit', True)

    # =========================
    # Core calculations
    # =========================

    def calculate_momentum(self, df: pd.DataFrame, window: int) -> float:
        if len(df) < window:
            return 0.0

        prices = df['close'].tail(window)
        log_returns = np.log(prices / prices.shift(1)).dropna()

        if log_returns.empty:
            return 0.0

        sigma = log_returns.std()
        if sigma <= 0 or np.isnan(sigma):
            return 0.0

        return log_returns.sum() / sigma

    def get_age_factor(self, df: pd.DataFrame) -> float:
        if df.empty:
            return 0.25

        age_months = (df.index.max() - df.index.min()).days / 30.0

        if age_months >= self.age_fair:
            return 0.25
        elif age_months >= self.age_good:
            return 0.50
        elif age_months >= self.age_excellent:
            return 0.75
        else:
            return 1.00

    # =========================
    # Public API
    # =========================

    def calculate_signals(self, df: pd.DataFrame) -> Dict:
        if len(df) < self.long_window:
            logger.warning("Insufficient data for momentum")
            return self._empty_signal(df)

        M_short = self.calculate_momentum(df, self.short_window)
        M_mid = self.calculate_momentum(df, self.mid_window)
        M_long = self.calculate_momentum(df, self.long_window)

        delta_M = M_short - M_long
        age_factor = self.get_age_factor(df)

        sma50 = df['close'].tail(self.sma_window).mean()
        current_price = df['close'].iloc[-1]

        # Bootstrap (always computed here)
        bootstrap = self.block_bootstrap(df)

        # Raw signal
        signal = self._generate_signal(age_factor, delta_M, current_price, sma50)

        # Bootstrap gate (only blocks entry)
        if signal == 1 and not self.check_bootstrap_gate(bootstrap):
            signal = 0

        return {
            'M_short': M_short,
            'M_mid': M_mid,
            'M_long': M_long,
            'delta_M': delta_M,
            'M_age_factor': age_factor,
            'sma50': sma50,
            'current_price': current_price,
            'bootstrap': bootstrap,
            'signal': signal
        }

    # =========================
    # Signal logic
    # =========================

    def _generate_signal(
        self,
        age_factor: float,
        delta_M: float,
        current_price: float,
        sma50: float
    ) -> int:
        if self.use_sma_exit and current_price < sma50:
            return -1

        if age_factor >= self.min_age_factor and delta_M >= self.min_delta_m:
            return 1

        return 0

    # =========================
    # Bootstrap
    # =========================

    def block_bootstrap(
        self,
        df: pd.DataFrame,
        block_size: int = 7,
        n_resamples: int = 400
    ) -> Dict:
        log_returns = np.log(df['close'] / df['close'].shift(1)).dropna()

        if len(log_returns) < block_size:
            return self._empty_bootstrap()

        momentums = []
        n_blocks = len(log_returns) // block_size

        for _ in range(n_resamples):
            sampled = []
            for _ in range(n_blocks):
                start = np.random.randint(0, len(log_returns) - block_size + 1)
                sampled.extend(log_returns.iloc[start:start + block_size].values)

            sampled = np.array(sampled[-self.long_window:])
            sigma = np.std(sampled)
            if sigma > 0:
                momentums.append(np.sum(sampled) / sigma)

        if not momentums:
            return self._empty_bootstrap()

        m = np.array(momentums)
        mean = m.mean()
        std = m.std()

        stability = 1 - std / abs(mean) if abs(mean) > 0 else 0.0

        return {
            'p_win_mom': float(np.mean(m > 0)),
            'M_p05': float(np.percentile(m, 5)),
            'M_mean': float(mean),
            'M_std': float(std),
            'stability': float(stability)
        }

    def check_bootstrap_gate(self, metrics: Dict, min_pwin: float = 0.60) -> bool:
        return metrics.get('p_win_mom', 0.0) >= min_pwin

    # =========================
    # Helpers
    # =========================

    def _empty_bootstrap(self) -> Dict:
        return {
            'p_win_mom': 0.0,
            'M_p05': 0.0,
            'M_mean': 0.0,
            'M_std': 0.0,
            'stability': 0.0
        }

    def _empty_signal(self, df: pd.DataFrame) -> Dict:
        price = df['close'].iloc[-1] if not df.empty else 0.0
        return {
            'M_short': 0.0,
            'M_mid': 0.0,
            'M_long': 0.0,
            'delta_M': 0.0,
            'M_age_factor': 0.0,
            'sma50': 0.0,
            'current_price': price,
            'bootstrap': self._empty_bootstrap(),
            'signal': 0
        }
