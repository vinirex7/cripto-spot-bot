# Vini Advanced Quant Engine

## Descrição
Um bot quantitativo avançado para trading no mercado cripto, otimizado para a Binance Spot. Com funcionalidades de decisão automatizada e configurações totalmente ajustáveis via `config.yaml`.

## Estrutura do Projeto

```
cripto-spot-bot/
│
├── bot.py                 # Script principal do bot
├── config.yaml            # Arquivo de configuração (ajustes de parâmetros)
├── requirements.txt       # Dependências Python
├── .gitignore            # Arquivos e diretórios ignorados pelo Git
├── README.md             # Documentação do projeto
│
├── .venv/                # Ambiente virtual Python (criado após setup)
├── bot_state.db          # Banco de dados SQLite (gerado em tempo de execução)
└── logs/                 # Diretório de logs (se habilitado)
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
```

**Variáveis de Ambiente Disponíveis:**

| Variável | Descrição | Obrigatória |
|----------|-----------|-------------|
| `BINANCE_API_KEY` | Chave de API da Binance | Sim (para modo trade) |
| `BINANCE_API_SECRET` | Secret da API da Binance | Sim (para modo trade) |
| `CRYPTOPANIC_TOKEN` | Token do CryptoPanic para análise de sentiment | Não |

**Nota de Segurança:** Nunca compartilhe ou versione suas chaves de API. O arquivo `.env` já está configurado no `.gitignore`.

### 5. Ajuste a Configuração

Edite o arquivo `config.yaml` conforme suas necessidades. Os principais parâmetros incluem:

- `bot.mode`: Define se o bot opera em modo `paper` (simulação) ou `trade` (real)
- `bot.loop_seconds`: Intervalo entre loops de execução
- `universe.symbols`: Lista de pares de trading (ex: BTCUSDT, ETHUSDT)
- `risk.*`: Parâmetros de gestão de risco
- `positioning.*`: Regras de posicionamento

## Fluxo de Execução

### Modo Paper (Simulação)

O modo paper trading permite testar estratégias sem risco financeiro:

1. Certifique-se de que `config.yaml` está configurado com `bot.mode: "paper"`
2. Execute o bot:

```bash
python bot.py
```

3. O bot simulará operações usando o saldo inicial configurado em `paper.equity_usdt`

### Modo Trade (Real)

**ATENÇÃO:** Modo real envolve fundos reais. Use com cautela e apenas após testes extensivos.

1. Configure as variáveis de ambiente com suas credenciais da Binance
2. Altere `config.yaml` para `bot.mode: "trade"`
3. Verifique novamente todos os parâmetros de risco
4. Execute o bot:

```bash
python bot.py
```

### Ciclo de Execução do Bot

1. **Inicialização**: Carrega configurações do `config.yaml`
2. **Loop Principal**:
   - Coleta dados de mercado (preços, volume, etc.)
   - Aplica sinais e filtros quantitativos
   - Calcula scores e toma decisões
   - Executa ordens (se modo trade)
   - Persiste estado no banco de dados
   - Aguarda próximo ciclo (`bot.loop_seconds`)
3. **Monitoramento Contínuo**: Repete o loop indefinidamente

## Logs e Monitoramento

- **SQLite Database**: O estado do bot é persistido em `bot_state.db`
- **Logs de Console**: Mensagens de execução são exibidas no terminal
- **Logs de Arquivo**: (Futuro) Configurável através de parâmetros adicionais

## Parando o Bot

Para parar o bot de forma segura:

- Pressione `Ctrl+C` no terminal
- O bot finalizará o loop atual e encerrará

## Troubleshooting

### Erro de Importação de Módulos

```bash
# Certifique-se de estar no ambiente virtual
source .venv/bin/activate
pip install -r requirements.txt
```

### Erro de Conexão com API

- Verifique suas credenciais da Binance
- Confirme que sua API key tem permissões adequadas (spot trading)
- Teste sua conexão de internet

### Banco de Dados Corrompido

```bash
# Remova o arquivo de banco e reinicie o bot
rm bot_state.db
python bot.py
```

## Contribuindo

Contribuições são bem-vindas! Por favor:

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