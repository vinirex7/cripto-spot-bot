# Strategy Mother v1 — Cripto Spot Quant Bot

This repository implements the layered Strategy Mother v1 for a spot crypto trading bot. The design favors safety, paper-first operation, and explicit guards across every layer.

## Architecture (Layers)

1. **Data** – pulls market data (prices, book ticker) and news (CryptoPanic).  
2. **Directional Core (Momentum 2.0)** – log-return momentum with M6 / M12 windows, acceleration ΔM, age discounts, and a fallback time-series momentum bias.  
3. **Microstructure** – order-flow imbalance (OFI) z-score over a rolling 24h baseline and 1h VWAP confirmation. Entry only when long bias, OFI\_z above threshold, and price above VWAP. Liquidity is checked via Amihud illiquidity; oversized illiquidity cuts size.  
4. **Regime / Contagion (News Shock Engine)** – combines SentZ (news), PriceShockZ\_1h, VolSpike. Hard risk-off triggers immediate flat + cooldown; soft risk-off halves risk and requires double confirmation.  
5. **Risk Management** – spot-safe VaR-like targeting: weight = min(max\_w, target\_vol / vol\_{1d}); obeys `max_positions`, `weight_per_position`, `cash_buffer`, `daily_drawdown_pause`, and `max_holding_hours`.  
6. **Execution** – prefers limit orders (marketable limit for exits), deduplicates client IDs, supports paper and live (env-keyed) modes.

Trades occur **only if all layers agree** (momentum bias, microstructure confirmation, risk guards pass, and no active cooldown).

## Thresholds & Defaults

Configured in `config.yaml`:

- **News shocks**: `sentz_hard=-3.0`, `priceshockz_hard=-3.0`, `ns_hard=-2.5`, `ns_soft=-1.5`, `volspike_soft=1.5`, `volspike_hard=1.8`, `cooldown_hours_hard=6`.  
- **Microstructure**: `ofi_z_entry=2.0`, `ofi_z_risk_on=1.5` (reduced in risk-on).  
- **Risk**: `target_vol_1d=0.012`, `max_positions=2`, `weight_per_position=0.30`, `cash_buffer=0.40`, `daily_drawdown_pause=0.025`, `max_holding_hours=72`.  
- **Momentum**: `n_days_short=182`, `n_days_long=365`, age discounts (100% to 25%).  
- **Universe**: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, LINKUSDT, AVAXUSDT, MATICUSDT, ADAUSDT.

## Safety Philosophy

- Paper mode is the default.  
- No secrets are stored; API keys are read from environment variables only (`BINANCE_API_KEY`, `BINANCE_API_SECRET`, `CRYPTOPANIC_TOKEN`).  
- News shocks can force an immediate flat and impose cooldowns.  
- Daily drawdown guard pauses trading until the next UTC day.  
- Persistent JSONL logs capture every decision for auditability.

## How to Run (Paper)

```bash
pip install -r requeriments.txt
python - <<'PY'
from bot.core import StrategyMotherEngine
engine = StrategyMotherEngine("config.yaml")
print(engine.step())
PY
```

## How to Enable Live Trading

1. Export environment variables:

```bash
export BINANCE_API_KEY="..."
export BINANCE_API_SECRET="..."
export CRYPTOPANIC_TOKEN="..."   # for news sentiment
```

2. Set `bot.mode` to `trade` in `config.yaml`.  
3. Run the engine loop under your process manager; `step()` already enforces a one-step-per-minute guard via `last_slot`.

## Logging

Daily JSONL logs are written to `./logs/YYYY-MM-DD-signals.jsonl` with fields:

- timestamp, symbol, M6, M12, ΔM, OFI\_z, SentZ, NS, regime, risk\_state, action.

These logs are paper-safe and contain no credentials.
