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

### 4. Configure as Variáveis de Ambiente

Crie um arquivo `.env` na raiz do projeto ou defina as variáveis de ambiente:

```bash
export BINANCE_API_KEY="sua_chave_api_aqui"
export BINANCE_API_SECRET="seu_secret_api_aqui"
export CRYPTOPANIC_TOKEN="seu_token_cryptopanic_aqui"  # Opcional para sentiment
export OPENAI_API_KEY="sua_chave_openai_aqui"  # Opcional para análise de notícias
export OPENAI_MODEL="gpt-4o-mini"  # Opcional, default: gpt-4o-mini
```

**Variáveis de Ambiente Disponíveis:**

| Variável | Descrição | Obrigatória |
|----------|-----------|-------------|
| `BINANCE_API_KEY` | Chave de API da Binance | Sim (para modo trade) |
| `BINANCE_API_SECRET` | Secret da API da Binance | Sim (para modo trade) |
| `CRYPTOPANIC_TOKEN` | Token do CryptoPanic para análise de sentiment | Não |
| `OPENAI_API_KEY` | Chave de API da OpenAI para análise de notícias | Não |
| `OPENAI_MODEL` | Modelo OpenAI a usar (default: gpt-4o-mini) | Não |

**Nota de Segurança:** Nunca compartilhe ou versione suas chaves de API. O arquivo `.env` já está configurado no `.gitignore`.

### 5. Ajuste a Configuração

Edite o arquivo `config.yaml` conforme suas necessidades. Principais parâmetros:

- `bot.mode`: Define se o bot opera em modo `paper` (simulação) ou `trade` (real)  
- `bot.loop_seconds` e `bot.decision_every_minutes`: Frequência do loop principal  
- `universe.symbols`: Lista de pares (ex: BTCUSDT, ETHUSDT)  
- `risk.*` e `positioning.*`: Regras de risco (max positions, weight, cash buffer)  
- `momentum.*`: Janelas e descontos de idade do Momentum 2.0  
- `news.*` e `microstructure.*`: Parâmetros de choques de notícias e OFI/VWAP  

## Modos de Execução

## Configuração de API Keys

O bot suporta duas formas de configuração de API keys, com fallback automático:

### Opção 1: Arquivo config.yaml (Recomendado para desenvolvimento)

Edite `config.yaml` e preencha a seção `api_keys`:

```yaml
api_keys:
  binance:
    api_key: "sua_chave_aqui"
    api_secret: "seu_secret_aqui"
  cryptopanic:
    token: "seu_token_aqui"
  openai:
    api_key: "sua_chave_aqui"
    model: "gpt-4o-mini"
```

⚠️ **IMPORTANTE**: Nunca commite o `config.yaml` com keys reais! Adicione ao `.gitignore` se necessário ou use um `config.local.yaml` para desenvolvimento.

### Opção 2: Variáveis de Ambiente (Recomendado para produção)

```bash
export BINANCE_API_KEY="sua_chave_aqui"
export BINANCE_API_SECRET="seu_secret_aqui"
export CRYPTOPANIC_TOKEN="seu_token_aqui"
export OPENAI_API_KEY="sua_chave_aqui"
export OPENAI_MODEL="gpt-4o-mini"
```

**O bot usa fallback automático**: config.yaml → variáveis de ambiente

Se uma chave estiver vazia no `config.yaml`, o bot tentará ler da variável de ambiente correspondente. Isso permite:
- **Desenvolvimento**: usar `config.yaml` localmente
- **Produção**: usar variáveis de ambiente no servidor

### Papel da OpenAI

A OpenAI (ChatGPT) é usada para **analisar notícias** e retornar valores numéricos que alimentam o sistema de decisão:

- `sentiment`: sentimento da notícia (-1 a 1)
- `confidence`: confiança da análise (0 a 1)
- `impact_horizon_minutes`: duração estimada do impacto
- `category`: categoria da notícia (regulation, adoption, technical, etc.)
- `action_bias`: viés de ação (bullish, bearish, neutral)

Esses valores são usados pelo `NewsEngine` para calcular `sent_llm` e avaliar shock de mercado (hard/soft/ok), que por sua vez multiplica o risco nas decisões de trading do bot.

**A análise da OpenAI é opcional** - se não configurada, o bot opera sem análise de sentimento de notícias.

## Modos de Execução

### Modo Paper (Simulação)

O modo paper simula trades sem executar ordens reais na exchange.

1. Certifique-se de que `config.yaml` está com `execution.mode: "paper"`  
2. Configure o saldo inicial em `execution.paper.initial_balance_usdt`
3. Execute o bot:

```bash
python3 tools/bootstrap_history.py --config config.yaml --all
```

O bot rodará em loop, aplicando a configuração definida e registrando trades simulados em `logs/trades.jsonl`.

### Modo Trade (Real - CUIDADO!)

> **ATENÇÃO:** Modo real envolve fundos reais. Use com cautela e apenas após testes extensivos.

#### Passo 1: Dry Run (Recomendado)

Configure em `config.yaml`:

```yaml
execution:
  mode: "trade"
  trade:
    dry_run: true  # Simula mas não envia ordens reais
    max_order_value_usdt: 1000
```

Execute e valide que todas as ordens estão sendo geradas corretamente:

```bash
python bot.py
```

Verifique os logs em `logs/trades.jsonl` - todas as ordens terão `"mode": "trade_dry_run"`.

#### Passo 2: Modo Live (Após validação com Dry Run)

Quando estiver confiante, mude para modo live:

```yaml
execution:
  mode: "trade"
  trade:
    dry_run: false  # ATENÇÃO: Ordens reais serão enviadas!
    max_order_value_usdt: 1000  # Limite de segurança por ordem
```

1. Defina as variáveis de ambiente com suas credenciais da Binance  
2. Revise todos os parâmetros de risco e buffers no `config.yaml`
3. Execute o bot:

```bash
python3 -m bot.core
```

**Configurações importantes para modo trade:**

- `execution.trade.max_order_value_usdt`: Limita o valor máximo por ordem
- `exchange.orders.min_notional_usdt`: Valor mínimo por ordem (default: 10 USDT)
- `exchange.orders.default_type`: Tipo de ordem (LIMIT ou MARKET)
- `exchange.orders.price_offset_bps`: Offset de preço para limit orders
- `risk.weight_per_position`: Peso máximo por posição
- `risk.max_positions`: Número máximo de posições simultâneas

### Execução via Engine (Paper Quickstart)

## Contratos principais
- Backfill: 12 meses 1d e 6 meses 1h (Binance), cache em SQLite (`data/market.sqlite`) com validação de gaps.
- News: fetch CryptoPanic a cada 12h, dedupe/cache 72h; OpenAI **sempre** analisa cada notícia nova em JSON estrito.
- Momentum 2.0: M6, M12, ΔM, idade do momentum e bootstrap gate.
- Anti-duplicação: `engine.step()` roda 1x por `decision_every_minutes` via `SlotScheduler`.

## Licença
Uso educacional/pesquisa. Risco de mercado permanece do usuário.
