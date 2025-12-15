# Vini Advanced Quant Engine

## Descrição
Um bot quantitativo avançado para trading no mercado cripto, otimizado para a Binance Spot. Com funcionalidades de decisão automatizada e configurações totalmente ajustáveis via `config.yaml`.

## Instalação
Certifique-se de que está utilizando Python 3.10+ em uma máquina Linux (ou em uma VPS).

1. Instale as dependências:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Configure as variáveis de ambiente necessárias:

```bash
export BINANCE_API_KEY="SUA_CHAVE"
export BINANCE_API_SECRET="SEU_SECRET"
export CRYPTOPANIC_TOKEN="SEU_TOKEN"
```

3. Ajuste o arquivo `config.yaml` conforme necessário.

## Modo Paper
Execute o bot em modo de simulação (paper):

```bash
python bot.py
```

## Modo Trade Real
Para ativar o modo `trade`, ajuste o campo `bot.mode` em `config.yaml` para `trade`:

```yaml
bot:
  mode: "trade"
```

E execute novamente:

```bash
python bot.py
```