# bot/engine.py
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bot.utils import write_jsonl
from bot.storage import HistoryStore
from bot.position import PositionStore
from news.engine import NewsEngine
from risk.guards import RiskGuards
from signals.momentum import compute_momentum_features
from execution.orders import create_executor


class BotEngine:
    def __init__(
        self,
        config: Dict[str, Any],
        history_store: HistoryStore,
        news_engine: NewsEngine,
        risk_guards: RiskGuards,
    ) -> None:
        self.config = config
        self.history_store = history_store
        self.news_engine = news_engine
        self.risk_guards = risk_guards
        self.logs_cfg = config.get("logging", {})

        self.pos_store = PositionStore(
            self.logs_cfg.get("files", {}).get("positions", "logs/positions.json")
        )
        self.executor = create_executor(config)

    def step(self, slot: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        now = now or datetime.now(timezone.utc)
        symbols = self.config.get("universe", [])
        results: List[Dict[str, Any]] = []

        # --- EXIT PARAMS (configuráveis) ---
        exit_cfg = (self.config.get("exit", {}) or {})
        takeprofit_mult = float(exit_cfg.get("takeprofit_mult", 1.8))  # 1.8x

        # trailing_dd: fração do topo (0.12 = 12%)
        trail_dd_raw = float(exit_cfg.get("trailing_dd", 0.12))
        trail_dd = max(0.0, min(0.95, trail_dd_raw))  # clamp defensivo

        # Position min notional: used to ignore dust when deciding "in position"
        orders_cfg = (self.config.get("exchange", {}) or {}).get("orders", {}) or {}
        default_pos_min_notional = float(orders_cfg.get("position_min_notional_usdt", 5.0))
        per_symbol_pos_min = orders_cfg.get("position_min_notional_overrides", {}) or {}

        for symbol in symbols:
            recent = self.history_store.fetch_ohlcv("1h", symbol, limit=1)
            current_price = recent[-1][4] if recent else 0.0

            # ------------------------------------------------------------
            # SYNC STATE ON EVERY WAKE
            # - snapshot balances (qty) + open orders from executor
            # - persist with timestamps so a restart doesn't lose context
            # ------------------------------------------------------------
            pos_min_notional = float(per_symbol_pos_min.get(symbol, default_pos_min_notional))

            try:
                snap = None
                if hasattr(self.executor, "snapshot_symbol_state"):
                    snap = self.executor.snapshot_symbol_state(symbol, current_price)  # type: ignore[attr-defined]
                if isinstance(snap, dict):
                    qty = float(snap.get("qty", 0.0))
                    open_orders_summary = snap.get("open_orders")
                    self.pos_store.sync_snapshot(
                        symbol,
                        qty=qty,
                        current_price=float(current_price),
                        position_min_notional_usdt=pos_min_notional,
                        ts=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        source=str(snap.get("source", "exchange")),
                        open_order_summary=open_orders_summary if isinstance(open_orders_summary, dict) else None,
                    )
            except Exception:
                # Never break the whole engine if the sync fails.
                pass

            features = compute_momentum_features(
                self.history_store,
                symbol,
                self.config.get("momentum", {}),
            )

            news_status = self.news_engine.current_status()
            risk_ctx = self.risk_guards.evaluate(symbol, features, news_status)

            pos = self.pos_store.get(symbol)
            in_position = bool(pos.get("in_position", False))
            entry_price = float(pos.get("entry_price", 0.0))
            peak_price = float(pos.get("peak_price", 0.0))

            # Atualiza topo
            if in_position and current_price > 0.0:
                self.pos_store.on_tick(symbol, current_price)
                peak_price = float(self.pos_store.get(symbol).get("peak_price", peak_price))

            target_weight = 0.0
            action = "HOLD"
            regime = "blocked"
            reason = "Momentum insufficient or risk constraints"

            # -------------------------
            # SELL rules (prioridade)
            # -------------------------
            sell_reason = None

            if in_position and current_price > 0.0:
                m6 = float((features or {}).get("m_6", 0.0))

                # 1) SELL se Momentum < 0
                if m6 < 0.0:
                    sell_reason = f"SELL | m6<0 | m6={m6:.2f}"

                # 2) SELL se preço >= 1.8x entry
                elif entry_price > 0.0 and current_price >= takeprofit_mult * entry_price:
                    sell_reason = (
                        f"SELL | takeprofit {takeprofit_mult:.2f}x | "
                        f"px={current_price:.6f} entry={entry_price:.6f}"
                    )

                # 3) SELL exatamente a -trail_dd do topo:
                #    Regra: current_price <= peak_price * (1 - trail_dd)
                elif peak_price > 0.0:
                    floor_price = peak_price * (1.0 - trail_dd)

                    if current_price <= floor_price:
                        # dd em % real (ex.: -12.0), só pra log humano
                        dd_pct = (current_price / peak_price - 1.0) * 100.0

                        sell_reason = (
                            f"SELL | trailing stop | "
                            f"rule: px <= peak*(1-{trail_dd:.0%}) | "
                            f"px={current_price:.6f} peak={peak_price:.6f} "
                            f"floor={floor_price:.6f} dd={dd_pct:.1f}%"
                        )

            if sell_reason:
                action = "SELL"
                regime = "exit"
                target_weight = 0.0
                reason = sell_reason

            # -------------------------
            # BUY logic
            # -------------------------
            if action == "HOLD":
                if in_position:
                    regime = "in_position"
                    reason = "Already in position; holding unless SELL triggers"
                else:
                    if features and float(risk_ctx.get("risk_multiplier", 0.0)) > 0.0:
                        m6 = float(features.get("m_6", 0.0))
                        m12 = float(features.get("m_12", 0.0))
                        delta_m = float(features.get("delta_m", 0.0))
                        m_age = float(features.get("m_age", 0.0))

                        weight_per_position = float(
                            (self.config.get("risk", {}) or {}).get("weight_per_position", 0.0)
                        )

                        REV_M6_MIN = 1.0
                        REV_AGE_MIN = 270.0
                        REV_WEIGHT_FACTOR = 0.35
                        EPS = 1e-9

                        trend_ok = (m12 > 0.0) and (m6 > 0.0) and (delta_m > 0.0)
                        delta_norm = delta_m / (abs(m12) + EPS)

                        strong_reversal_ok = (
                            (m12 <= 0.0)
                            and (m6 >= REV_M6_MIN)
                            and (delta_norm >= 1.0)
                            and (m_age >= REV_AGE_MIN)
                        )

                        if trend_ok:
                            regime = "trend"
                            base_weight = weight_per_position
                            reason = (
                                f"Momentum ok (trend) | m6={m6:.2f}, m12={m12:.2f}, "
                                f"Δm={delta_m:.2f}, age={m_age:.0f}"
                            )
                        elif strong_reversal_ok:
                            regime = "early_reversal"
                            base_weight = weight_per_position * REV_WEIGHT_FACTOR
                            reason = (
                                f"Momentum ok (early reversal) | m6={m6:.2f}, m12={m12:.2f}, "
                                f"Δm={delta_m:.2f}, Δm_norm={delta_norm:.2f}, age={m_age:.0f}"
                            )
                        else:
                            base_weight = 0.0
                            reason = (
                                f"Momentum blocked | m6={m6:.2f}, m12={m12:.2f}, "
                                f"Δm={delta_m:.2f}, Δm_norm={delta_norm:.2f}, age={m_age:.0f}"
                            )

                        target_weight = base_weight * float(risk_ctx.get("risk_multiplier", 1.0))
                        if target_weight > 0.0:
                            action = "BUY"

            # ---- Execution ----
            execution_result = None
            if action != "HOLD" and current_price > 0.0:
                execution_result = self.executor.execute(symbol, action, target_weight, current_price)

                status = (
                    str((execution_result or {}).get("status", "")).lower()
                    if isinstance(execution_result, dict)
                    else ""
                )
                filled = status == "filled"

                if filled:
                    if action == "BUY":
                        fill_price = float((execution_result or {}).get("avg_fill_price", 0.0)) or float(
                            (execution_result or {}).get("price", 0.0)
                        ) or float(current_price)
                        fill_qty = (execution_result or {}).get("quantity") or (execution_result or {}).get("origQty")
                        try:
                            fill_qty_f = float(fill_qty) if fill_qty is not None else None
                        except Exception:
                            fill_qty_f = None
                        self.pos_store.on_buy_filled(symbol, fill_price, qty=fill_qty_f)
                    elif action == "SELL":
                        self.pos_store.on_sell_filled(symbol)

                # Persist orders regardless of fill (so the bot remembers after restart)
                if isinstance(execution_result, dict):
                    o_id = execution_result.get("order_id") or execution_result.get("orderId")
                    o_side = execution_result.get("side") or action
                    o_type = execution_result.get("type") or execution_result.get("order_type") or execution_result.get("orderType")
                    o_qty = execution_result.get("quantity") or execution_result.get("origQty")
                    o_price = execution_result.get("price") or current_price
                    o_status = str(execution_result.get("status") or "").lower()

                    if o_id is not None and str(o_id) != "":
                        pending = o_status in ("open", "new")
                        self.pos_store.record_order(
                            symbol,
                            order_id=o_id,
                            side=o_side,
                            order_type=o_type or "",
                            qty=o_qty,
                            price=o_price,
                            status=o_status,
                            ts=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            pending=pending,
                        )
                        if not pending:
                            self.pos_store.clear_pending(symbol, ts=now.strftime("%Y-%m-%dT%H:%M:%SZ"))

            decision = {
                "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "slot": slot,
                "symbol": symbol,
                "action": action,
                "regime": regime,
                "target_weight": target_weight,
                "current_price": current_price,
                "position": self.pos_store.get(symbol),
                "features": features or {},
                "risk": risk_ctx,
                "reason": reason,
                "execution": execution_result,
            }

            write_jsonl(self._decisions_path(), decision, flush=self.logs_cfg.get("flush_every_write", True))
            results.append(decision)

        return results

    def _decisions_path(self) -> str:
        return self.logs_cfg.get("files", {}).get("decisions", "logs/decisions.jsonl")
