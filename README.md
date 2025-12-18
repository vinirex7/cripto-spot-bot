# Cripto Spot Bot — Vini QuantBot v3

Este repositório implementa o contrato técnico solicitado: histórico obrigatório (12m/1d e 6m/1h), notícias a cada 12h com análise OpenAI sempre, anti-duplicação por slot e logs JSONL auditáveis.

## Estrutura

```
cripto-spot-bot/
├── bot/                 # core, engine e scheduler
├── data/                # backfill e store SQLite
├── news/                # CryptoPanic + OpenAI + scheduler 12h
├── signals/             # Momentum 2.0
├── risk/                # Guards e news shock
├── execution/           # Abstrações de execução (paper)
├── tools/               # CLI para backfill
├── config.yaml          # Config principal (atualizada)
└── requirements.txt
```

## Variáveis de ambiente

```
BINANCE_API_KEY=xxx
BINANCE_API_SECRET=xxx
CRYPTOPANIC_TOKEN=xxx
OPENAI_API_KEY=xxx
OPENAI_MODEL=gpt-5.2-thinking  # opcional, default interno se ausente
```

## Uso rápido

1) Instale dependências:
```bash
pip install -r requirements.txt
```

2) Rode o backfill inicial:
```bash
python3 tools/bootstrap_history.py --config config.yaml --all
```

3) Inicie o bot (paper mode por padrão):
```bash
python3 -m bot.core
```

## Logs obrigatórios (JSONL)
- `logs/decisions.jsonl` — cada decisão por símbolo/slot
- `logs/news.jsonl` — cada notícia analisada pelo OpenAI
- `logs/system.jsonl` — eventos (backfill, janela de news, etc.)
- `logs/trades.jsonl` — ordens (paper/live)

## Contratos principais
- Backfill: 12 meses 1d e 6 meses 1h (Binance), cache em SQLite (`data/market.sqlite`) com validação de gaps.
- News: fetch CryptoPanic a cada 12h, dedupe/cache 72h; OpenAI **sempre** analisa cada notícia nova em JSON estrito.
- Momentum 2.0: M6, M12, ΔM, idade do momentum e bootstrap gate.
- Anti-duplicação: `engine.step()` roda 1x por `decision_every_minutes` via `SlotScheduler`.

## Licença
Uso educacional/pesquisa. Risco de mercado permanece do usuário.
