# 📚 Recomendador de Livros

> Registro pessoal de Leituras, com Nota, e Sugestões do que ler a seguir. Cada Sugestão vem com o seu Motivo.

![Python 3.13](https://img.shields.io/badge/python-3.13-3776AB?logo=python&logoColor=white)
![PostgreSQL 17 + pgvector](https://img.shields.io/badge/PostgreSQL_17-pgvector-4169E1?logo=postgresql&logoColor=white)
![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B?logo=streamlit&logoColor=white)
![PyTorch CUDA](https://img.shields.io/badge/embeddings-PyTorch_CUDA-EE4C2C?logo=pytorch&logoColor=white)
![uv](https://img.shields.io/badge/deps-uv-DE5FE9)
![Ruff](https://img.shields.io/badge/lint-ruff-D7FF64)
[![Licença MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-green)](LICENSE)

As listas de "mais vendidos" e os algoritmos das lojas não conhecem o histórico de quem lê. Os serviços que conhecem misturam rede social, controle de leitura e anúncios. Este projeto é um lugar simples para registrar o que já li, dar Nota e receber Sugestões que fazem sentido para o meu gosto, cada uma com o Motivo ("Porque você deu 5 a *Duna*").

**Não é um app de leitura:** não abre livro, não marca página e não controla progresso.

A v1 roda **só no computador do Leitor**, sem login: interface em Streamlit, PostgreSQL com pgvector no Docker e embeddings calculados na GPU local ([ADR 0005](docs/adr/0005-local-first.md)).

---

## Sumário

- [Funcionalidades](#funcionalidades)
- [Como as Sugestões funcionam](#como-as-sugestões-funcionam)
- [Avaliação offline](#avaliação-offline)
- [Arquitetura](#arquitetura)
- [Primeiros passos](#primeiros-passos)
- [Uso no dia a dia](#uso-no-dia-a-dia)
- [CLI do pipeline](#cli-do-pipeline)
- [Desenvolvimento](#desenvolvimento)
- [Documentação](#documentação)
- [Licença](#licença)

---

## Funcionalidades

| Página | O que faz |
|---|---|
| **Para você** | Até 20 Sugestões com capa, Motivo e "Por quê?" (os 3 maiores Contribuintes e a participação de cada um). Filtros de Gênero e de Edição em português. Uma aba **Tecnologia** separada para Obras técnicas. |
| **Obra** | "Parecidos com este" (Similaridade de conteúdo, com o Ponto em comum) e "Quem leu este também gostou" (Coleitura). |
| **Adicionar** | Busca por título, autor ou ISBN (Google Books e Open Library), Resolução da Edição para a Obra com "É uma destas?" quando é preciso, e cadastro manual. |
| **Estante** | As Leituras ordenadas por Nota ou por data; mudar a Nota ou remover reflete nas Sugestões na hora. |
| **Quero ler** / **Estou lendo** | Listas separadas da Estante. "Estou lendo" só diz que a Obra foi começada: sem página, percentual nem prazo ([ADR 0008](docs/adr/0008-estou-lendo-sem-progresso.md)). |
| **Importar** | Histórico de um CSV exportado do Goodreads: prévia, relatório e revisão das linhas sem correspondência ([ADR 0011](docs/adr/0011-importacao-do-goodreads.md)). |
| **Montagem da Estante** | O primeiro passo com a Estante vazia: escolher Gêneros e dar Nota a Obras populares até ter Notas suficientes. |

Uma Sugestão dispensada ("Não tenho interesse") não volta a "Para você", e a Dispensa pode ser desfeita na página da Obra.

## Como as Sugestões funcionam

Tudo é registrado e recomendado por **Obra**, não por Edição ([ADR 0001](docs/adr/0001-obra-como-unidade.md)): *Duna* (Aleph) e *Dune* (Ace) são a mesma Obra, então uma nunca é sugerida a quem leu a outra.

Duas fontes de semelhança, calculadas em lote e gravadas como **Vizinhos** de cada Obra ([ADR 0004](docs/adr/0004-vizinhos-pre-calculados.md)):

| Critério | Pergunta | Como é calculado |
|---|---|---|
| **Similaridade de conteúdo** | "É parecido com este?" | Embeddings de título, autor, assuntos e descrição com `Qwen/Qwen3-Embedding-4B`, truncado para 1024 dimensões ([ADR 0006](docs/adr/0006-modelo-de-embedding.md)) |
| **Coleitura** | "Quem gostou deste também gostou de quê?" | Cosseno ajustado item-item com encolhimento sobre ~6 M de Notas do goodbooks-10k ([ADR 0003](docs/adr/0003-goodbooks-10k.md)) |

A pontuação de "Para você" é uma consulta SQL sobre os Vizinhos das execuções ativas:

```
peso(Nota):  5 → +1,0 · 4 → +0,6 · 3 → 0 · 2 → −0,5 · 1 → −1,0

parcela(c, r) = peso(Nota de r) × [ α · conteúdo(r→c) / escala_conteúdo
                                   + (1 − α) · coleitura(r→c) / escala_coleitura ]

pontuação(c)  = Σ_r parcela(c, r) × (1 + popularidade(c))^β
Motivo(c)     = a Leitura r com a maior parcela positiva
```

- Notas baixas **afastam** Sugestões parecidas, porque o peso delas é negativo.
- Cada critério é dividido pela média das suas similaridades antes da mistura. Sem isso, o conteúdo engoliria a Coleitura ([ADR 0007](docs/adr/0007-calibracao-da-mistura.md)).
- Valores em uso: **α = 0,25**, **β = 0,25**, Coleitura com **K = 20** e **λ = 10**. Todos ficam em `config`.
- O Catálogo é fechado: só Obras da Base de coleitura, Obras técnicas da Open Library e Obras das Estantes podem ser sugeridas ([ADR 0002](docs/adr/0002-catalogo-fechado.md), [ADR 0009](docs/adr/0009-obras-tecnicas-da-open-library.md)).
- Com menos de 3 Leituras com Nota, o app pede mais Notas em vez de mostrar uma lista vazia.

## Avaliação offline

Protocolo da [SPEC §9](docs/SPEC.md#9-avaliação-offline): 5.000 leitores do goodbooks-10k, 20 % das Notas de cada um para teste, semente 42 e IC de 95 % por bootstrap. Resultado de [`reports/avaliacao-2026-11-26.md`](reports/avaliacao-2026-11-26.md), com β = 0,25:

| Configuração | NDCG@20 | Recall@20 | Cobertura do Catálogo |
|---|---:|---:|---:|
| Popularidade (baseline) | 0,0828 | 0,0802 | 0,7 % |
| Só Similaridade de conteúdo | 0,1143 | 0,1103 | 27,1 % |
| Só Coleitura | 0,2925 | 0,2587 | 40,4 % |
| **Conteúdo + Coleitura (α = 0,25)** | **0,2967** | **0,2620** | **40,3 %** |

A mistura supera o melhor critério isolado (Δ NDCG@20 +0,0041, IC [0,0031; 0,0051]). A varredura de α × β × K × λ (296 configurações) e os experimentos descartados, como ALS e K = 100 no conteúdo, estão em [`reports/`](reports/).

## Arquitetura

```
        scripts/abrir.cmd ──► iniciar.ps1: sobe o banco, roda `atualizar`, abre o app
                                         │
┌──────────── app/ (Streamlit, 127.0.0.1:8501) ────────────┐
│ Para você · Estou lendo · Quero ler · Estante · Adicionar │   só chama funções públicas ↓
│ Importar · Montagem da Estante · Obra                     │
└───────────────────────────────────────────────────────────┘
┌──────────────────────── recomendador/ ────────────────────────────────┐
│ catalogo/      busca, Resolução Edição → Obra, Gêneros                 │
│   └ fontes/    único lugar com HTTP externo (Google Books, Open Library)│
│ estante/       Leituras, Notas, listas, Montagem, Importação, Eventos  │
│ recomendacao/  embeddings, pontuação, Motivo, Ponto em comum           │
│ pipeline/      cálculo em lote: carga, enriquecimento, Vizinhos, avaliação │
│ db/            modelos SQLAlchemy, sessão, migrações                   │
└──────────────┬───────────────────────────────────┬────────────────────┘
               │ SQLAlchemy 2                      │ PyTorch CUDA
   PostgreSQL 17 + pgvector (Docker)        data/ (goodbooks-10k, dumps da OL, embeddings)
```

Regras de dependência:

- `app/` não contém SQL nem regra de negócio.
- `estante` não conhece `recomendacao`.
- O cálculo pesado roda só em `pipeline/`. No fluxo interativo, a GPU gera no máximo um embedding por Obra adicionada.

Stack: Python 3.13 · SQLAlchemy 2 + Alembic · psycopg 3 · pgvector · sentence-transformers · NumPy/SciPy/pandas · RapidFuzz · httpx · Typer · Streamlit · pytest · Ruff · uv.

## Primeiros passos

### Pré-requisitos

- Windows com [Docker Desktop](https://www.docker.com/products/docker-desktop/). Ele não precisa iniciar com o Windows: o app o abre se precisar.
- [uv](https://docs.astral.sh/uv/), que instala o Python 3.13 sozinho.
- GPU NVIDIA com driver recente, para calcular os embeddings. O código também roda em CPU, só mais devagar.
- Uma chave da [Google Books API](https://developers.google.com/books/docs/v1/using#APIKey).
- ~15 GB livres em disco para os dumps da Open Library.

### 1. Configuração

```powershell
Copy-Item .env.example .env
```

Preencha no `.env`:

| Variável | Para quê |
|---|---|
| `GOOGLE_BOOKS_API_KEY` | Busca de Edições |
| `OPEN_LIBRARY_USER_AGENT` | Contato exigido pela Open Library para clientes automáticos |
| `DATABASE_URL`, `DATABASE_URL_TEST` | Já apontam para o Postgres do `docker-compose.yml` (porta 5433) |
| `DATA_DIR` | Pasta dos dados baixados e calculados (padrão `./data`) |

### 2. Dependências e banco

```powershell
uv sync --extra ml
```

```powershell
docker compose up -d --wait db
```

O `--extra ml` instala PyTorch (CUDA 12.8) e sentence-transformers. Sem ele, o app roda, mas não gera embeddings. O banco escuta só em `127.0.0.1:5433`, porque a 5432 costuma ser do Postgres nativo do Windows.

### 3. Carga do Catálogo e cálculo dos Vizinhos

Feito uma vez, nesta ordem:

```powershell
uv run python -m recomendador db-subir
```

```powershell
uv run python -m recomendador carregar-base
```

```powershell
uv run python -m recomendador enriquecer-ol --baixar
```

```powershell
uv run python -m recomendador mapear-generos
```

```powershell
uv run python -m recomendador carregar-tecnicas
```

```powershell
uv run python -m recomendador recalcular --modelo Qwen/Qwen3-Embedding-4B
```

```powershell
uv run python -m recomendador calcular-tecnico
```

| Passo | O que faz |
|---|---|
| `db-subir` | Aplica as migrações e cria o Leitor e os Gêneros |
| `carregar-base` | Baixa (~30 MB) e carrega o goodbooks-10k |
| `enriquecer-ol --baixar` | Baixa os dumps da Open Library (~13 GB) e enriquece as Obras com assuntos e descrição. Leva cerca de 1 h com o download. |
| `mapear-generos` | Liga as Obras aos Gêneros de [`catalogo/generos.yaml`](recomendador/catalogo/generos.yaml) |
| `carregar-tecnicas` | Traz as Obras técnicas dos dumps da Open Library |
| `recalcular` | Embeddings e Vizinhos de conteúdo, Coleitura, avaliação offline e ativação das execuções que passarem no critério |
| `calcular-tecnico` | Vizinhos técnicos, para a aba "Tecnologia" |

## Uso no dia a dia

Abra o app com **[`scripts/abrir.cmd`](scripts/abrir.cmd)**, ou com um atalho dele na Área de Trabalho. Ele:

1. abre o Docker Desktop, se estiver fechado, e sobe o banco;
2. roda `atualizar`: migrações pendentes, enriquecimento das Obras novas do Leitor pela Open Library e os embeddings delas, em no máximo 10 min;
3. abre `http://127.0.0.1:8501` no navegador.

Nada roda com o Windows. Fechar a janela encerra o app. O log de cada abertura fica em `logs/atualizar-AAAA-MM-DD.log`.

Para abrir o app à mão:

```powershell
uv run streamlit run app/main.py --server.address 127.0.0.1
```

## CLI do pipeline

`uv run python -m recomendador <comando> --help` mostra as opções de cada comando.

| Comando | Descrição |
|---|---|
| `db-subir` | Migrações, Leitor e Gêneros |
| `carregar-base` | Carga do goodbooks-10k |
| `enriquecer-ol` | Enriquecimento pelos dumps da Open Library |
| `mapear-generos` | Gêneros das Obras pelas tags |
| `generos-do-leitor` | Gêneros das Obras do Leitor pelas categorias do Google Books |
| `carregar-tecnicas` | Obras técnicas da Open Library |
| `calcular-conteudo` | Embeddings e Vizinhos de conteúdo, numa execução inativa |
| `calcular-coleitura` | Vizinhos de Coleitura, numa execução inativa |
| `calcular-tecnico` | Vizinhos técnicos, numa execução que já entra ativa |
| `bakeoff` | Compara modelos de embedding candidatos ([SPEC §8.4](docs/SPEC.md#84-bake-off-do-modelo-de-embedding)) |
| `avaliar` | Avaliação offline (Recall@20, NDCG@20, cobertura) e varredura da calibração |
| `ativar` | Torna uma execução a ativa do seu tipo, se o NDCG@20 não piorar |
| `recalcular` | `calcular-conteudo` + `calcular-coleitura` + `avaliar` + `ativar` |
| `atualizar` | Rotina de abertura do app |

Cada cálculo grava uma **execução de modelo** versionada. Só uma execução por tipo fica ativa, e trocar de modelo exige uma avaliação com a mesma divisão e o mesmo β.

## Desenvolvimento

```
recomendador/   catalogo/ · estante/ · recomendacao/ · pipeline/ · db/ · config.py
app/            páginas Streamlit
migrations/     Alembic
scripts/        abrir.cmd, iniciar.ps1
docker/         scripts de criação do banco
data/           dados baixados e calculados (fora do git)
reports/        relatórios da avaliação offline
tests/          testes e dados gravados
```

### Testes e lint

Os testes rodam contra o **Postgres real**, num banco `recomendador_test` do mesmo container, sem mocks de banco. Cada teste roda numa transação revertida no fim. As respostas do Google Books e da Open Library vêm de JSONs gravados em [`tests/dados/http/`](tests/dados/http/).

```powershell
docker compose up -d --wait db
```

```powershell
uv run pytest
```

```powershell
uv run ruff check .
```

Os testes que chamam APIs reais (`externo`) ou precisam de GPU (`gpu`) ficam fora da execução padrão:

```powershell
uv run pytest -m "externo or gpu"
```

### Convenções

- Código, testes e mensagens usam os termos do [GLOSSARY.md](GLOSSARY.md): Obra, Edição, Leitura, Nota, Estante, Catálogo, Vizinho, Sugestão, Motivo…
- Antes de contrariar uma decisão de desenho, leia o ADR correspondente em [`docs/adr/`](docs/adr/).
- Mudanças de esquema entram como migração Alembic em [`migrations/versions/`](migrations/versions/).

## Documentação

| Documento | Conteúdo |
|---|---|
| [docs/PRD.md](docs/PRD.md) | O quê e por quê: problema, objetivos, histórias e requisitos |
| [docs/SPEC.md](docs/SPEC.md) | Como: arquitetura, modelo de dados, algoritmos, avaliação e fases |
| [GLOSSARY.md](GLOSSARY.md) | A linguagem do domínio |
| [docs/adr/](docs/adr/) | 11 decisões de arquitetura, com contexto e números |
| [docs/research/](docs/research/) | Pesquisas sobre fontes de dados, modelos de embedding e formatos de exportação |
| [reports/](reports/) | Relatórios da avaliação offline e das varreduras |

## Licença

O código está sob a [licença MIT](LICENSE).

A licença MIT não vale para os dados de terceiros. Eles seguem as licenças e os termos de origem:

| Dados | Origem | Licença ou termos |
|---|---|---|
| Notas de leitores, tags e metadados da Base de coleitura, inclusive a amostra em [`tests/dados/goodbooks-mini/`](tests/dados/goodbooks-mini/) | [goodbooks-10k](https://github.com/zygmuntz/goodbooks-10k) | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
| Metadados de Obras e Edições, inclusive as respostas gravadas em [`tests/dados/http/ol/`](tests/dados/http/ol/) | [Open Library](https://openlibrary.org) | [CC0 1.0](https://openlibrary.org/developers/licensing) |
| Resultados de busca, inclusive as respostas gravadas em [`tests/dados/http/gb/`](tests/dados/http/gb/) | [Google Books API](https://developers.google.com/books) | [Termos de serviço das APIs do Google](https://developers.google.com/terms) |
| Modelo de embedding | [`Qwen/Qwen3-Embedding-4B`](https://huggingface.co/Qwen/Qwen3-Embedding-4B) | Apache 2.0 |

Os dados baixados e calculados ficam em `data/`, fora do git.
