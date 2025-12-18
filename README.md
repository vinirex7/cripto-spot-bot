# Strategy Mother v1 — Cripto Spot Quant Bot

This repository implements the layered Strategy Mother v1 for a spot crypto trading bot. The design favors safety, paper-first operation, and explicit guards across every layer.

## Estrutura do Projeto

```
cripto-spot-bot/
│
├── bot.py                  # Script principal (modo simples)
├── bot/                    # Engine Strategy Mother v1 (core)
├── execution/              # Módulo de execução de ordens
├── news/                   # Cliente CryptoPanic e sentiment
├── risk/                   # Guardas de risco e news shock
├── signals/                # Momentum e microestrutura
├── config.yaml             # Config principal
├── config.yam              # Config legada (fallback compatível)
├── requirements.txt        # Dependências Python
├── .gitignore              # Arquivos e diretórios ignorados pelo Git
└── README.md               # Documentação do projeto
│
├── .venv/                  # Ambiente virtual (criado após setup)
├── bot_state.db / bot.db   # Bancos SQLite (gerados em tempo de execução)
└── logs/                   # Diretório de logs JSONL
```

## Requisitos do Sistema

- **Python**: 3.10 ou superior  
- **Sistema Operacional**: Linux (recomendado) ou qualquer sistema compatível com Python  
- **Memória**: Mínimo 512 MB RAM  
- **Conexão**: Internet estável para comunicação com a API da Binance  

## Instalação

### 1. Clone o Repositório

```bash
git clone https://github.com/vinirex7/cripto-spot-bot.git
cd cripto-spot-bot
```

### 2. Crie e Ative o Ambiente Virtual

```bash
python3 -m venv .venv
source .venv/bin/activate  # No Windows: .venv\Scripts\activate
```

### 3. Instale as Dependências

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
python bot.py
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
python bot.py
```

**Configurações importantes para modo trade:**

- `execution.trade.max_order_value_usdt`: Limita o valor máximo por ordem
- `exchange.orders.min_notional_usdt`: Valor mínimo por ordem (default: 10 USDT)
- `exchange.orders.default_type`: Tipo de ordem (LIMIT ou MARKET)
- `exchange.orders.price_offset_bps`: Offset de preço para limit orders
- `risk.weight_per_position`: Peso máximo por posição
- `risk.max_positions`: Número máximo de posições simultâneas

### Execução via Engine (Paper Quickstart)

Para testar rapidamente o engine Strategy Mother v1 em modo paper:

```bash
pip install -r requirements.txt
python - <<'PY'
from bot.core import StrategyMotherEngine
engine = StrategyMotherEngine("config.yaml")
print(engine.step())
PY
```

## Arquitetura (Camadas)

1. **Data** – coleta preços, book ticker e notícias (CryptoPanic).  
2. **Directional Core (Momentum 2.0)** – momentum M6/M12 (log-return), aceleração ΔM e desconto por idade.  
3. **Microstructure** – OFI z-score com baseline 24h + confirmação VWAP 1h; checa liquidez e corta tamanho se ilíquido.  
4. **Regime / Contagion (News Shock Engine)** – combina SentZ, PriceShockZ\_1h e VolSpike; hard risk-off fecha posições e impõe cooldown; soft risk-off reduz risco.  
5. **Risk Management** – sizing spot-safe: `weight = min(max_w, target_vol / vol_1d)` obedecendo `max_positions`, `weight_per_position`, `cash_buffer`, `daily_drawdown_pause`, `max_holding_hours`.  
6. **Execution** – prefere ordens limit, deduplica client IDs, suporta modos paper e live (variáveis de ambiente).  

Trades só ocorrem se **todas as camadas concordarem** (viés de momentum, confirmação microstructure, guardas de risco e sem cooldown ativo).

## Limiar e Defaults (config.yaml)

- **News shocks**: `sentz_hard=-3.0`, `priceshockz_hard=-3.0`, `ns_hard=-2.5`, `ns_soft=-1.5`, `volspike_soft=1.5`, `volspike_hard=1.8`, `cooldown_hours_hard=6`.  
- **Microstructure**: `ofi_z_entry=2.0`, `ofi_z_risk_on=1.5` (reduzido em risk-on).  
- **Risk**: `target_vol_1d=0.012`, `max_positions=2`, `weight_per_position=0.30`, `cash_buffer=0.40`, `daily_drawdown_pause=0.025`, `max_holding_hours=72`.  
- **Momentum**: `n_days_short=182`, `n_days_long=365`, descontos de idade (100% → 25%).  
- **Universe**: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, LINKUSDT, AVAXUSDT, MATICUSDT, ADAUSDT.  

## Filosofia de Segurança

- Paper mode é o default.  
- Chaves nunca são versionadas; apenas via variáveis de ambiente (`BINANCE_API_KEY`, `BINANCE_API_SECRET`, `CRYPTOPANIC_TOKEN`).  
- Choques de notícia podem zerar posições e impor cooldown.  
- Guard de drawdown diário pausa operações até o próximo dia UTC.  
- Logs JSONL registram cada decisão para auditoria.  

## Logs e Monitoramento

- **SQLite**: estado persistido em `bot_state.db` / `bot.db` (dependendo da execução).  
- **Logs JSONL**: `./logs/YYYY-MM-DD-signals.jsonl` (paper-safe, sem credenciais).  
- **Console**: mensagens de execução no terminal.  

## Troubleshooting

### Erro de Importação de Módulos

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### Erro de Conexão com API

- Verifique suas credenciais da Binance  
- Confirme permissões corretas na API key (spot trading)  
- Teste sua conexão de internet  

### Banco de Dados Corrompido

```bash
rm bot_state.db
python bot.py
```

## Contribuindo

1. Fork o repositório  
2. Crie uma branch para sua feature (`git checkout -b feature/nova-funcionalidade`)  
3. Commit suas mudanças (`git commit -m 'Adiciona nova funcionalidade'`)  
4. Push para a branch (`git push origin feature/nova-funcionalidade`)  
5. Abra um Pull Request  

## Avisos Legais

- **Risco Financeiro**: Trading de criptomoedas envolve risco substancial de perda  
- **Sem Garantias**: Este software é fornecido "como está", sem garantias  
- **Responsabilidade**: O uso deste bot é por sua conta e risco  
- **Regulamentação**: Certifique-se de estar em conformidade com as leis locais  

## Licença

Este projeto é fornecido para fins educacionais e de pesquisa.
