# 🤖 Vini QuantBot v3.0.1

**Quantitative Spot Trading Bot for Binance**

A sophisticated cryptocurrency trading bot implementing Momentum 2.0 strategy with age-based decay, bootstrap validation, microstructure analysis, regime detection, and integrated AI for news analysis.

---

## ⚠️ DISCLAIMER

**THIS SOFTWARE TRADES REAL MONEY. USE AT YOUR OWN RISK.**

- This bot can result in significant financial losses
- Cryptocurrency trading is highly risky
- Past performance does not guarantee future results
- Always test in paper mode first
- Never invest more than you can afford to lose
- The authors are not responsible for any losses

---

## 🎯 Features

### Core Quantitative Strategy
- **Momentum 2.0**: Multi-timeframe momentum with age-based decay (0-12m → 1.00, 18m+ → 0.25)
- **Bootstrap Validation**: Block bootstrap (n=400) with minimum P(M>0) ≥ 0.60 gate
- **Volatility Targeting**: Dynamic position sizing targeting 1.2% daily volatility
- **Microstructure Guards**: Spread, OFI, VWAP deviation, Amihud illiquidity checks
- **Regime Detection**: BTC vs alts correlation and volatility regime analysis

### News & Sentiment Analysis
- **CryptoPanic Integration**: Real-time crypto news aggregation
- **Quantitative Sentiment**: Vote-based sentiment with exponential decay (12h half-life)
- **AI-Enhanced Analysis**: OpenAI GPT for news classification (optional, rate-limited)
- **NewsShock v3**: Combined sentiment and price shock analysis with pause triggers

### Risk Management
- **Multi-Layer Guards**: Microstructure, drawdown, holding period, news-based pauses
- **Position Limits**: Max 2 positions, 30% per position, 40% minimum cash buffer
- **Dynamic Parameters**: LLM-suggested risk-reducing adjustments with strict guardrails and TTL
- **Force Exit**: MARKET orders on risk violations

### Execution & Safety
- **Paper & Live Modes**: Test safely before trading real money
- **Anti-Duplication Scheduler**: Prevents multiple executions per time slot
- **JSONL Logging**: Complete audit trail (no secrets logged)
- **SQLite Storage**: Position tracking and bot state persistence

---

## 🏗️ Architecture

```
cripto-spot-bot/
├── config.yaml          # Main configuration
├── requirements.txt     # Python dependencies
├── .env.example        # Environment variables template
├── bot/                # Core bot engine
│   ├── main.py         # Entry point with scheduler
│   └── core.py         # Pipeline orchestration
├── data/               # Market data handling
│   ├── binance_rest.py # REST API client
│   ├── binance_ws.py   # WebSocket client
│   ├── history_store.py # SQLite OHLCV storage
│   └── bootstrap_history.py # Historical data bootstrap
├── signals/            # Signal generation
│   ├── momentum.py     # Momentum 2.0 + bootstrap
│   ├── microstructure.py # Spread, OFI, VWAP, Amihud
│   └── regime.py       # Correlation & volatility
├── news/               # News & sentiment
│   ├── cryptopanic.py  # CryptoPanic API
│   └── sentiment_quant.py # Quantitative sentiment
├── ai/                 # AI integration (optional)
│   ├── openai_client.py # Rate-limited OpenAI client
│   ├── news_analyzer.py # News classification ONLY
│   └── explainer.py    # Decision explanations
├── risk/               # Risk management
│   ├── guards.py       # Multi-layer risk guards
│   ├── news_shock.py   # NewsShock v3
│   ├── position_sizing.py # Vol targeting
│   └── dynamic_params.py # Dynamic risk adjustments
├── execution/          # Trade execution
│   └── orders.py       # Binance order execution
├── storage/            # Persistence
│   ├── db.py          # SQLite position tracking
│   └── log_writer.py  # JSONL logging
└── scripts/            # Helper scripts
    ├── run_paper.sh   # Run in paper mode
    └── run_trade.sh   # Run in live mode
```

---

## 📋 Requirements

- **Python 3.10+**
- **Ubuntu 22.04** (recommended for VPS deployment)
- **Binance API credentials** (with spot trading enabled)
- **CryptoPanic API token** (free tier available)
- **OpenAI API key** (optional, for enhanced news analysis)

---

## 🚀 Quick Start

### 1. Clone Repository

```bash
git clone https://github.com/vinirex7/cripto-spot-bot.git
cd cripto-spot-bot
```

### 2. Create Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

```bash
# Copy template
cp .env.example .env

# Edit .env with your credentials
nano .env
```

**Required variables:**
```bash
BINANCE_API_KEY=your_binance_api_key_here
BINANCE_API_SECRET=your_binance_api_secret_here
CRYPTOPANIC_TOKEN=your_cryptopanic_token_here
OPENAI_API_KEY=your_openai_api_key_here  # Optional
```

**Load variables:**
```bash
source .env
# OR
export $(cat .env | xargs)
```

### 5. Bootstrap Historical Data

**IMPORTANT: Run this before starting the bot!**

```bash
python -m data.bootstrap_history --config config.yaml
```

This will fetch:
- ≥ 420 days of daily OHLCV data (≥ 12 months)
- ≥ 120 days of hourly OHLCV data

Expected time: ~5-10 minutes

### 6. Run Bot in Paper Mode

```bash
# Using script
bash scripts/run_paper.sh

# OR manually
python -m bot.main --config config.yaml
```

### 7. Run Bot in Live Mode (⚠️ REAL MONEY)

```bash
# Using script (includes confirmation prompt)
bash scripts/run_trade.sh

# OR manually (set mode='live' in config.yaml first)
python -m bot.main --config config.yaml
```

---

## ⚙️ Configuration

Edit `config.yaml` to customize bot behavior.

### Key Parameters

**Universe (Fixed - Do not auto-list):**
```yaml
universe:
  - BTCUSDT
  - ETHUSDT
  - BNBUSDT
  - SOLUSDT
  - LINKUSDT
  - AVAXUSDT
  - ADAUSDT
```

**Momentum 2.0:**
```yaml
momentum:
  short_window: 60    # days
  mid_window: 90      # days
  long_window: 120    # days
  sma_window: 50      # days
```

**Bootstrap Gate:**
```yaml
bootstrap:
  enabled: true
  block_size_days: 7  # Range: 5-10
  n_resamples: 400
  min_pwin: 0.60      # Minimum P(M > 0)
```

**Risk Management:**
```yaml
risk:
  target_vol_1d: 0.012         # 1.2%
  max_positions: 2
  weight_per_position_max: 0.30  # 30%
  cash_buffer_min: 0.40         # 40%
  daily_drawdown_pause_pct: 2.5 # 2.5%
  max_holding_hours: 72
```

**OpenAI (Optional):**
```yaml
openai:
  enabled: true
  model: gpt-4o-mini
  mode: low_cost  # off | low_cost | full
  max_calls_per_hour: 30
  cache_ttl_seconds: 1800
```

---

## 🔒 Security Best Practices

### Never Commit Secrets
- ✅ Use `.env` file for credentials
- ✅ `.gitignore` includes `.env`
- ❌ Never hardcode API keys
- ❌ Never commit `.env` to git

### API Key Permissions
- Enable **Spot Trading** only
- Enable **Read** permissions
- **Disable** withdrawals
- Use IP whitelist if possible

### System Security
- ❌ **DO NOT RUN AS ROOT**
- ✅ Use dedicated non-root user
- ✅ Keep system updated
- ✅ Use firewall (UFW recommended)
- ✅ Enable fail2ban

---

## 📊 Monitoring

### Logs

**Console logs:**
```bash
tail -f logs/bot_console.log
```

**Structured JSONL logs:**
```bash
tail -f logs/bot.jsonl | jq
```

**Filter by event type:**
```bash
grep '"event_type":"trade"' logs/bot.jsonl | jq
grep '"event_type":"signal"' logs/bot.jsonl | jq
grep '"event_type":"risk"' logs/bot.jsonl | jq
```

### Database

**Open positions:**
```bash
sqlite3 state/positions.sqlite "SELECT * FROM positions WHERE status='OPEN';"
```

**Closed positions:**
```bash
sqlite3 state/positions.sqlite "SELECT * FROM positions WHERE status='CLOSED' ORDER BY exit_time DESC LIMIT 10;"
```

**Performance:**
```bash
sqlite3 state/positions.sqlite "SELECT 
  COUNT(*) as trades,
  AVG(pnl) as avg_pnl,
  SUM(pnl) as total_pnl,
  AVG(pnl_pct) as avg_pnl_pct
FROM positions WHERE status='CLOSED';"
```

---

## 🧪 Testing

### Bootstrap Test
```bash
python -m data.bootstrap_history --config config.yaml
```

### Single Run Test (No scheduler)
```bash
python -m bot.main --config config.yaml --once
```

### Paper Mode (10 minutes)
```bash
timeout 600 python -m bot.main --config config.yaml
```

---

## 🛠️ Troubleshooting

### Bot won't start
- Check Python version: `python3 --version` (need 3.10+)
- Check dependencies: `pip install -r requirements.txt`
- Check environment variables: `echo $BINANCE_API_KEY`
- Check logs: `cat logs/bot_console.log`

### No trades being executed
- Check if in paper mode: `grep mode config.yaml`
- Check bootstrap gate: Look for "Failed bootstrap gate" in logs
- Check risk guards: Look for "Failed risk guards" in logs
- Check news pause: Look for "Trading paused" in logs

### OpenAI errors
- Check API key: `echo $OPENAI_API_KEY`
- Check rate limit: Bot has 30 calls/hour limit
- OpenAI can be disabled: Set `openai.enabled: false` in config

### Database locked
```bash
# Stop bot first, then:
rm state/positions.sqlite-journal
```

---

## 🎓 How It Works

### Decision Flow

1. **Data Collection**: Fetch OHLCV, order book, news
2. **Momentum Calculation**: M = sum(log_returns) / sigma with age decay
3. **Bootstrap Validation**: Block bootstrap with P(M>0) ≥ 0.60 gate
4. **Microstructure Checks**: Spread, OFI, VWAP, Amihud
5. **Regime Detection**: BTC/alts correlation and volatility
6. **News Analysis**: Quant sentiment + optional LLM classification
7. **NewsShock v3**: Combined sentiment & price shock → pause triggers
8. **Risk Guards**: Drawdown, holding period, position limits
9. **Position Sizing**: Volatility targeting (1.2% target)
10. **Execution**: LIMIT orders (MARKET only on risk exits)
11. **Logging**: JSONL + SQLite for complete audit trail

### Critical Rules

**🚨 LLM CANNOT:**
- Make buy/sell decisions
- Set prices or position sizes
- Override risk controls

**✅ LLM CAN ONLY:**
- Classify news (sentiment, category, confidence)
- Suggest risk-reducing parameter adjustments (with TTL & guardrails)
- Generate explanations

### Bootstrap Gate

Applied ONLY to 1d data:
- Block size: 7 days
- Resamples: 400
- Metric: P(M > 0) ≥ 0.60
- Blocks entry if unstable momentum

### NewsShock v3 Pauses

**HARD PAUSE (6h):**
- Critical category (regulation, hack, bankruptcy, delisting)
- Confidence ≥ 0.65
- SentLLM ≤ -0.5

**SOFT PAUSE (1-3h):**
- NS_v3 ≤ -1.2

---

## 📈 Performance Expectations

**This is NOT a get-rich-quick scheme.**

- Target: 1.2% daily volatility
- Expected: ~20-40% annualized return (if strategy works)
- Reality: Results will vary, losses are possible
- Backtest: Not included (implement your own)
- Paper trading: Strongly recommended before live

---

## 🔄 Updates & Maintenance

### Update Dependencies
```bash
source .venv/bin/activate
pip install --upgrade -r requirements.txt
```

### Update Historical Data
```bash
python -m data.bootstrap_history --config config.yaml
```

### Backup Database
```bash
cp state/positions.sqlite state/positions.backup.$(date +%Y%m%d).sqlite
```

---

## 🤝 Contributing

This is a personal project. If you fork it:
- Test thoroughly in paper mode
- Never commit API keys
- Document any changes
- Share improvements (optional)

---

## 📄 License

**Use at your own risk. No warranties provided.**

This software is provided "as-is" without any express or implied warranty. In no event shall the authors be held liable for any damages arising from the use of this software.

---

## 📞 Support

**No official support provided.**

This is a personal project. You are responsible for:
- Understanding the code
- Testing thoroughly
- Managing your own risk
- Complying with regulations

---

## 🎯 Roadmap

Future improvements (no timeline):
- [ ] Backtesting framework
- [ ] Web dashboard
- [ ] More exchanges
- [ ] Advanced order types
- [ ] Portfolio rebalancing
- [ ] Machine learning signals

---

## 📚 References

- [Binance API Documentation](https://binance-docs.github.io/apidocs/spot/en/)
- [CryptoPanic API](https://cryptopanic.com/developers/api/)
- [OpenAI API](https://platform.openai.com/docs/api-reference)

---

**Built with ❤️ for quantitative crypto trading**

**Version:** 3.0.1  
**Last Updated:** 2024-12-16
