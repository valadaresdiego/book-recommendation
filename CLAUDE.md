# Recomendador de Livros

- Use os termos de `GLOSSARY.md` (Obra, Edição, Leitura, Nota, Estante, Catálogo, Vizinho, Sugestão, Motivo...) no código, nos testes e nas mensagens. Não use "livro" quando a diferença entre Obra e Edição importar.
- O desenho está em `docs/SPEC.md`. Antes de contrariar uma decisão, leia o ADR correspondente em `docs/adr/`.
- Camadas: `app/` (Streamlit) só chama funções públicas de `recomendador.catalogo`, `recomendador.estante` e `recomendador.recomendacao`. HTTP externo só em `recomendador/catalogo/fontes/`. Cálculo em lote só em `recomendador/pipeline/`.
- Testes rodam contra o Postgres real (`docker compose up -d --wait db`, porta 5433), sem mocks de banco. Rode `uv run pytest` e `uv run ruff check .` antes de dizer que algo está pronto.
