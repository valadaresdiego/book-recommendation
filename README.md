# Recomendador de Livros

Registro pessoal das minhas Leituras, com Nota, e Sugestões do que ler a seguir, cada uma com o seu Motivo. A v1 roda local: Streamlit, PostgreSQL com pgvector no Docker e cálculos na GPU.

- **O quê e por quê:** [docs/PRD.md](docs/PRD.md)
- **Como:** [docs/SPEC.md](docs/SPEC.md)
- **Termos:** [GLOSSARY.md](GLOSSARY.md)
- **Decisões:** [docs/adr/](docs/adr/)
- **Pesquisas:** [docs/research/](docs/research/)

## Pré-requisitos

- Windows com Docker Desktop configurado para **iniciar com o Windows**
- [uv](https://docs.astral.sh/uv/) (instala o Python 3.13 sozinho)
- GPU NVIDIA com driver recente (só a partir da fase 2)

## Primeiros passos

```bash
cp .env.example .env            # e preencha GOOGLE_BOOKS_API_KEY e o contato do User-Agent
uv sync                         # dependências base + dev
docker compose up -d --wait db  # Postgres 17 + pgvector em 127.0.0.1:5433
uv run python -m recomendador db-subir        # migrações, Leitor e Gêneros
uv run python -m recomendador carregar-base   # baixa e carrega o goodbooks-10k (~30 MB, segundos)
uv run python -m recomendador enriquecer-ol --baixar  # dumps da Open Library (~17 GB; ~1 h com o download)
uv run python -m recomendador mapear-generos  # liga as Obras aos Gêneros (catalogo/generos.yaml)
uv run pytest
uv run streamlit run app/main.py --server.address 127.0.0.1
```

Para a fase 2 em diante (embeddings na GPU): `uv sync --extra ml`.

Para subir tudo no logon do Windows: `powershell -ExecutionPolicy Bypass -File scripts/registrar-tarefa.ps1`.

## Estrutura

```
recomendador/   catalogo/ · estante/ · recomendacao/ · pipeline/ · db/ · config.py
app/            páginas Streamlit (só chamam o pacote)
migrations/     Alembic
scripts/        iniciar.ps1, registrar-tarefa.ps1
docker/         scripts de criação do banco
data/           goodbooks-10k, dumps da Open Library, modelos (fora do git)
reports/        relatórios de avaliação offline
tests/
```

## Atribuição

As Notas de leitores vêm do [goodbooks-10k](https://github.com/zygmuntz/goodbooks-10k) (CC BY-SA 4.0). Os metadados vêm da [Open Library](https://openlibrary.org) e do [Google Books](https://developers.google.com/books).
