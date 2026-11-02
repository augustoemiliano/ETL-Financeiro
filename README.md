# ETL Financeiro

[![CI](https://github.com/augustoemiliano/ETL-Financeiro/actions/workflows/ci.yml/badge.svg)](https://github.com/augustoemiliano/ETL-Financeiro/actions/workflows/ci.yml)

Pipeline ETL em Python que **lê dados financeiros de várias fontes** (API de câmbio, planilhas CSV e
XLSX), **padroniza e valida** cada linha, **carrega no PostgreSQL** de forma idempotente e **gera
relatórios CSV/JSON**. Tem logs em arquivo, tratamento de erro por fonte, retry automático, testes
automatizados, Docker e CI.

## O que o projeto faz

| Etapa | Como |
|-------|------|
| **Extract** | API pública [Frankfurter](https://www.frankfurter.app/) (câmbio, sem chave), todos os `*.csv` de cotações e todos os `*.xlsx` de carteira encontrados nos diretórios configurados |
| **Transform** | pandas: converte cada fonte para um schema canônico único (`symbol`, `metric_date`, `metric_type`, `currency`, `amount`, ...), normaliza datas/moedas e deduplica |
| **Validação** | regras por linha: símbolo e data obrigatórios, moeda ISO 4217, valor numérico finito, preço/cotação > 0. Linhas inválidas **não são carregadas nem "corrigidas"**: vão para `reports/rejected_rows_*.csv` com o motivo |
| **Load** | SQLAlchemy 2 + `INSERT ... ON CONFLICT DO NOTHING` na chave natural, em uma transação por lote (rollback total se algo falhar). Rodar duas vezes não duplica dados |
| **Relatórios** | `financial_metrics_*.csv`, `source_summary_*.csv`, `portfolio_ranking_*.csv` e `financial_summary_*.json` em `reports/` |
| **Resiliência** | retry exponencial (tenacity) só para falhas transitórias de rede (timeout, conexão, 429, 5xx); uma fonte com erro é registrada e as outras seguem; o job agendado tenta de novo e não derruba o scheduler |
| **Observabilidade** | logs no console + `logs/app_info.log` e `logs/app_error.log` (rotação diária) |
| **Operação** | CLI (`run-etl`, `scheduler`, `api`), API FastAPI com Swagger e um painel HTML simples |

## Arquitetura

```mermaid
flowchart LR
  subgraph extract [Extract]
    A["API Frankfurter<br/>(requests + retry)"]
    B["data/*.csv<br/>cotações"]
    C["data/*.xlsx<br/>carteira"]
  end

  subgraph transform [Transform + Validação]
    P[builders por fonte<br/>schema canônico]
    V{validate_records}
    Q[(rejected_rows_*.csv)]
  end

  subgraph load [Load]
    R[(PostgreSQL<br/>financial_metrics)]
  end

  subgraph deliver [Entrega]
    S[relatórios CSV/JSON]
    F[FastAPI + painel]
  end

  A --> P
  B --> P
  C --> P
  P --> V
  V -- válidas --> R
  V -- inválidas --> Q
  R --> S
  R --> F
```

Camadas (cada pasta tem uma responsabilidade):

| Pasta | Responsabilidade |
|-------|------------------|
| `app/core/` | configuração por variáveis de ambiente (`pydantic-settings`), logging, scheduler |
| `app/etl/extract/` | leitores de API/CSV/XLSX com erros próprios (`SourceUnavailableError`, `FileSourceError`) |
| `app/etl/transform/` | conversão para o schema canônico, normalização e validação (`schema.py`) |
| `app/etl/load/`, `app/repositories/`, `app/models/` | ORM, inserção idempotente (`ON CONFLICT DO NOTHING`) e consultas |
| `app/services/` | orquestração do pipeline (`etl_service.py`) e relatórios (`report_service.py`) |
| `app/api/` | FastAPI: dispara o pipeline e expõe snapshots |
| `alembic/` | migrações versionadas do banco |
| `app/tests/` | `unit/` (sem infraestrutura) e `integration/` (SQLite temporário e PostgreSQL real) |

Modelo de dados: uma tabela fato `financial_metrics` com chave natural
`(symbol, metric_date, metric_type, source_system)`. Tipos de métrica: `FX_SPOT` (câmbio),
`EQUITY_LAST` (fechamento de ação) e `POSITION_MARK` (posição da carteira).

## Stack

Python 3.12 · pandas · requests · tenacity · SQLAlchemy 2 · Alembic · PostgreSQL 16 · FastAPI/Uvicorn ·
schedule · openpyxl · pytest · ruff · black · Docker/Compose · GitHub Actions

## Como rodar

### Opção 1 — Docker (recomendado, sobe PostgreSQL junto)

Pré-requisito: Docker com Compose v2.

```bash
git clone https://github.com/augustoemiliano/ETL-Financeiro.git
cd ETL-Financeiro

docker compose up -d --build postgres backend   # migrações rodam automaticamente
curl http://localhost:8000/health
curl -X POST http://localhost:8000/etl/run      # executa o ETL e gera relatórios em ./reports
```

- Painel web: <http://localhost:8000/> · Swagger: <http://localhost:8000/docs>
- Execução avulsa do ETL pela CLI: `docker compose run --rm backend run-etl`
- Scheduler diário (`SCHEDULER_RUN_TIME`): `docker compose --profile cron up -d scheduler`
- PostgreSQL fica exposto no host em `localhost:5435`.
- Para trocar as credenciais de demonstração, crie um `.env` com `POSTGRES_USER`,
  `POSTGRES_PASSWORD` e `POSTGRES_DB` (o Compose lê esse arquivo automaticamente).

> Linux: o container roda como usuário não-root com UID 1000. Se o seu usuário tiver outro UID,
> use `docker compose build --build-arg APP_UID=$(id -u) --build-arg APP_GID=$(id -g)` para que
> o container consiga gravar em `./logs` e `./reports`.

### Opção 2 — Local com Python

Pré-requisito: Python 3.12+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows (PowerShell): .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

cp .env.example .env               # Windows: copy .env.example .env
```

Escolha o banco no `.env`:

- **PostgreSQL** (padrão do `.env.example`): suba só o banco com `docker compose up -d postgres`
  ou aponte `DATABASE_URL` para um Postgres seu.
- **Sem Postgres**, para experimentar rapidamente: `DATABASE_URL=sqlite:///etl_local.db`
  (SQLite é suportado apenas para desenvolvimento e testes).

```bash
alembic upgrade head               # cria a tabela
python main.py run-etl             # executa o pipeline uma vez
python main.py api                 # API em http://127.0.0.1:8000
python main.py scheduler           # loop diário com retry
```

Sem internet? Use `FX_ENABLED=false` para rodar só com os arquivos locais.

## Variáveis de ambiente

Todas estão documentadas em [`.env.example`](.env.example). As principais:

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `DATABASE_URL` | — (obrigatória) | URL SQLAlchemy. Ex.: `postgresql+psycopg2://user:senha@host:5432/db` |
| `CSV_INPUT_DIR` / `XLSX_INPUT_DIR` | `data/samples` | diretórios lidos; todos os `*.csv` / `*.xlsx` são processados |
| `FX_ENABLED` | `true` | liga/desliga a fonte HTTP de câmbio |
| `FX_API_BASE_URL` | `https://api.frankfurter.app` | endpoint da API de câmbio |
| `FX_BASE_CURRENCY` / `FX_TARGET_CURRENCIES` | `USD` / `BRL,EUR,GBP` | pares consultados |
| `FX_CONNECT_TIMEOUT` / `FX_READ_TIMEOUT` | `5` / `30` | timeouts HTTP (s) |
| `HTTP_RETRY_ATTEMPTS` | `4` | tentativas para falhas transitórias |
| `HTTP_RETRY_MIN_WAIT` / `HTTP_RETRY_MAX_WAIT` | `2` / `20` | backoff exponencial (s) |
| `REPORTS_DIR` / `LOG_DIR` | `reports` / `logs` | saídas geradas (ignoradas pelo git) |
| `REPORT_HISTORY_DAYS` | vazio | janela dos relatórios em dias; vazio = histórico completo |
| `SCHEDULER_ENABLED` / `SCHEDULER_RUN_TIME` | `true` / `02:00` | agendamento diário |
| `SCHEDULER_RETRY_ATTEMPTS` | `4` | novas tentativas do job agendado |
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8000` | bind da API local (no container é `0.0.0.0`) |
| `LOG_LEVEL` | `INFO` | nível de log |

## Exemplo de saída

`python main.py run-etl` com os dados de `data/samples` (o arquivo `sample_quotes_2024_02.csv` traz
de propósito 3 linhas inválidas para demonstrar a validação):

```text
INFO | app.services.etl_service | Fonte fx_api: 3 linha(s) válida(s)
INFO | app.services.etl_service | Fonte csv::sample_quotes.csv: 3 linha(s) válida(s)
WARNING | app.services.etl_service | Fonte csv::sample_quotes_2024_02.csv: 3 linha(s) rejeitada(s) pela validação
INFO | app.services.etl_service | Fonte csv::sample_quotes_2024_02.csv: 3 linha(s) válida(s)
INFO | app.services.etl_service | Fonte xlsx::sample_portfolio.xlsx: 3 linha(s) válida(s)
INFO | app.services.etl_service | ETL batch 3f6c... finalizado — fontes ok=4 falhas=0 linhas válidas=12 rejeitadas=3 inserts=12 duplicidades=0 em 1.6s
INFO | __main__ | Relatório gerado (csv_metrics_path): reports/financial_metrics_20261102T140430Z_3f6c1a2b.csv
...
```

Rodando de novo: `inserts=0 duplicidades=12` (carga idempotente).

`reports/portfolio_ranking_*.csv`:

```csv
group,currency,total,share_pct,rank
FIM_MULTISECTOR,BRL,128400.75,52.3015,1
CDB_LC,BRL,82100.5,33.442,2
RF_PLUS,BRL,35000.0,14.2565,3
```

`reports/source_summary_*.csv`:

```csv
source_system,metric_type,records,symbols,first_date,last_date,avg_amount
frankfurter_api,FX_SPOT,3,3,2026-10-30,2026-10-30,2.357973
local_csv_markets,EQUITY_LAST,6,4,2024-01-02,2024-02-01,39.538333
local_xlsx_portfolio,POSITION_MARK,3,3,2024-06-03,2024-06-04,81833.75
```

`reports/rejected_rows_*.csv` (quarentena):

```csv
symbol,metric_date,...,rejection_reason,source_job
ABEV3,2024-02-01,...,moeda fora do padrão ISO 4217; preço/cotação deve ser positivo,csv::sample_quotes_2024_02.csv
ITUB4,,...,data inválida ou ausente,csv::sample_quotes_2024_02.csv
WEGE3,2024-02-01,...,valor não numérico ou infinito,csv::sample_quotes_2024_02.csv
```

Resposta de `POST /etl/run`:

```json
{
  "batch_id": "3f6c1a2b-...",
  "inserts": 12,
  "duplicates": 0,
  "rows_transformed": 12,
  "rows_rejected": 3,
  "sources_ok": ["fx_api", "csv::sample_quotes.csv", "csv::sample_quotes_2024_02.csv", "xlsx::sample_portfolio.xlsx"],
  "sources_failed": [],
  "rejected_report_path": "reports/rejected_rows_3f6c1a2b.csv",
  "artifacts": { "csv_metrics_path": "reports/financial_metrics_....csv", "...": "..." }
}
```

Se uma fonte falhar (ex.: API fora do ar após as tentativas), ela aparece em `sources_failed` e as
demais são carregadas normalmente. Se **todas** falharem, a API responde `502`.

### Formato esperado dos arquivos de entrada

- **CSV de cotações**: `symbol, trade_date, currency, close` (obrigatórias) e `open, high, low, volume` (opcionais).
- **XLSX de carteira**: `fund` (ou `fund_symbol`), `position_value` (ou `value`), `base_currency` e
  `ref_date`/`snapshot_date` (opcional; sem data usa o dia atual). Outras colunas vão para `extras`.

## Testes e qualidade

```bash
pytest                                  # tudo (integração Postgres é pulada sem servidor)
pytest -m "not integration" --cov      # unitários + integração com SQLite temporário
pytest -m integration                  # exige PostgreSQL na DATABASE_URL (ex.: docker compose up -d postgres)

ruff check .
black --check app main.py scripts
```

Cobertura atual: **87%** do pacote `app` (66 testes passando sem Postgres; +2 de integração com
Postgres no CI). Os testes cobrem extração (arquivos válidos, ausentes, vazios e corrompidos; API
com cliente dublê), transformação, regras de validação, load (idempotência e rollback),
retry HTTP e do scheduler, relatórios, API e a migração Alembic.

O workflow [`ci.yml`](.github/workflows/ci.yml) roda a cada push/PR:

1. **lint** — ruff + black;
2. **tests** — pytest com cobertura;
3. **integration** — PostgreSQL 16 como service container: `alembic upgrade/downgrade/upgrade`,
   testes `-m integration` e uma execução real de `python main.py run-etl`;
4. **docker** — `docker compose up --build` + smoke test de `/health`, `/etl/run` e `/reports/snapshot`.

## Decisões técnicas

1. **Uma tabela fato com chave natural composta** unifica fontes diferentes e torna a carga
   idempotente via `ON CONFLICT DO NOTHING`.
2. **Sem imputação de valores financeiros**: preencher preço ou saldo ausente com a mediana gera
   dado falso. Linhas inválidas vão para quarentena auditável.
3. **Retry só no que é transitório**: erro 4xx não é repetido; timeouts, quedas de conexão, 429 e
   5xx usam backoff exponencial configurável.
4. **Falha isolada por fonte**: uma API fora do ar não impede a carga das planilhas.
5. **`schedule` em vez de Celery**: para um batch diário, evita broker e infraestrutura extra. O
   trade-off é não ter escala horizontal nem filas.
6. **FastAPI apenas como porta de operação**: o mesmo serviço de domínio é usado pela CLI e pela API.
7. **PostgreSQL é o destino oficial**; SQLite é aceito só para desenvolvimento e testes rápidos.

## Limitações conhecidas

- A API não tem autenticação: é uma ferramenta de operação para uso local/demonstração. Não exponha
  `POST /etl/run` publicamente sem colocar autenticação na frente.
- As credenciais do `docker-compose.yml` são defaults de demonstração; sobrescreva-as via `.env`.
- O ranking da carteira compara posições na mesma moeda; não há conversão cambial entre moedas.
