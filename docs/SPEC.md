# SPEC: Recomendador de Livros (v1, local)

> **Status:** rascunho · **Data:** 17/11/2026 · **Cobre:** fases 0 a 4 (o P0 e o P1 do PRD)
>
> **Leia antes:** [PRD](PRD.md) (o quê e por quê) · [GLOSSARY](../GLOSSARY.md) (termos; esta SPEC usa só eles) · [ADRs](adr/) (decisões difíceis de reverter) · pesquisas em [research/](research/)

Esta SPEC diz **como** construir o que o PRD pede. Ela não repete objetivos nem histórias. Quando uma regra vem do PRD, cita o requisito (R1, R4…).

---

## 1. Escopo

| Entra (detalhado) | Entra só como ponto de extensão | Entra só como restrição |
|---|---|---|
| Fase 0 (fundação), fase 1 (Estante + Montagem da Estante), fase 2 (Parecidos), fase 3 (Coleitura), fase 4 (Ajustes: R7 dispensar, R8 quero ler, R10 filtros, R11 Motivo detalhado, §8.6) | — | Multiusuário, hospedagem, Base de coleitura maior, LLM nos Motivos, importar histórico (§13) |

Mudanças em relação ao PRD original, registradas nos ADRs e já incorporadas no PRD:

- O app roda **local**, sem login (ADR 0005). O R6 vira "um Leitor fixo".
- A **Montagem da Estante** entra no P0. A importação (R9) vai para o P2.

---

## 2. Arquitetura

```
┌──────────────────────────── PC do Leitor ─────────────────────────────┐
│                                                                        │
│  Leitor abre scripts/abrir.cmd ──► scripts/iniciar.ps1                 │
│        │ 1. docker compose up -d db                                    │
│        │ 2. python -m recomendador atualizar                           │
│        │ 3. streamlit run app.py  (127.0.0.1:8501)                     │
│                                                                        │
│  ┌──────────── Streamlit (app/) ────────────┐                          │
│  │ Montagem · Estante · Buscar · Para você · │  só chama ↓              │
│  │ Quero ler · Obra                          │                          │
│  └───────────────────────────────────────────┘                          │
│  ┌──────────── pacote recomendador/ ────────────────────────────────┐  │
│  │ catalogo/      busca, resolução Edição→Obra, enriquecimento       │  │
│  │ estante/       Leituras, Notas, Montagem da Estante, Eventos      │  │
│  │ recomendacao/  embeddings, coleitura, Vizinhos, pontuação, Motivo │  │
│  │ pipeline/      CLI: carregar, enriquecer, calcular, avaliar        │  │
│  └────────────┬──────────────────────────────┬──────────────────────┘  │
│               │ SQLAlchemy 2                  │ PyTorch CUDA (RTX 3060) │
│  ┌────────────▼─────────────┐   ┌─────────────▼────────────┐            │
│  │ PostgreSQL 17 + pgvector │   │ data/  (goodbooks-10k,    │            │
│  │ (Docker)                 │   │ dumps OL, modelos HF)     │            │
│  └──────────────────────────┘   └──────────────────────────┘            │
└──────────────────────┬──────────────────────────────┬──────────────────┘
                       │ HTTPS (busca, R1)             │ HTTPS (1 req/s)
                 Google Books API               Open Library API
```

Regras de dependência:

- `app/` importa só as funções públicas de `catalogo`, `estante` e `recomendacao`. A UI não contém SQL nem regra de negócio.
- `recomendacao` lê `estante` (Leituras e Notas) e `catalogo` (Obras). `estante` não conhece `recomendacao`.
- As chamadas HTTP externas ficam só em `catalogo/fontes/` (`google_books.py`, `open_library.py`).
- O cálculo pesado (embeddings em lote, coleitura) roda só em `pipeline/`. No fluxo interativo, a GPU só gera **um** embedding por vez, ao adicionar uma Obra (§7.3).

---

## 3. Ambiente e ferramentas

| Item | Escolha |
|---|---|
| Python | 3.13, gerenciado com `uv` (`pyproject.toml` + `uv.lock`) |
| GPU | PyTorch com CUDA (RTX 3060, 12 GB). O código precisa funcionar em CPU também, só mais devagar. |
| Banco | `docker-compose.yml` com `pgvector/pgvector:0.8.7-pg17`, volume nomeado `pgdata`, porta 5433 só em `127.0.0.1` (a 5432 é do Postgres nativo do Windows) |
| Esquema | SQLAlchemy 2 (ORM e Core) + Alembic |
| UI | Streamlit, `--server.address 127.0.0.1` |
| Testes | `pytest`, banco `recomendador_test` no mesmo container, sem mocks de banco |
| Embeddings | `sentence-transformers`. O modelo sai do bake-off (§8.4). |
| Dependências principais | `sqlalchemy`, `alembic`, `psycopg[binary]`, `pgvector`, `httpx`, `torch`, `sentence-transformers`, `numpy`, `scipy`, `pandas`, `pyarrow`, `rapidfuzz`, `streamlit`, `typer` |

Configuração em `.env` (fora do git, com `.env.example` versionado):

```
DATABASE_URL=postgresql+psycopg://recomendador:recomendador@127.0.0.1:5433/recomendador
DATABASE_URL_TEST=postgresql+psycopg://recomendador:recomendador@127.0.0.1:5433/recomendador_test
GOOGLE_BOOKS_API_KEY=
OPEN_LIBRARY_USER_AGENT=recomendador-pessoal/0.1 (contato: <preencher>)
DATA_DIR=./data
```

Estrutura de pastas:

```
recomendador/
  catalogo/  estante/  recomendacao/  pipeline/  db/ (modelos SQLAlchemy, sessão)  config.py
app/            # páginas Streamlit
migrations/     # Alembic
scripts/        # abrir.cmd, iniciar.ps1
data/           # raw/ (goodbooks-10k), ol/ (dumps), cache/; fora do git
reports/        # relatórios de avaliação, versionados
tests/
```

---

## 4. Modelo de dados

Tudo o que é pessoal tem `leitor_id`, o que cumpre o `usuario_id` do R6 e do P2. Na v1 existe uma única linha em `leitor`, criada pela migração inicial. O app sempre usa esse id, lido de `config.LEITOR_ID`.

```
leitor          id uuid PK · nome · criado_em

obra            id bigserial PK
                titulo text              -- título canônico (geralmente o original)
                titulo_original text null
                titulo_exibicao text     -- preferencialmente o de uma Edição em português
                autores text[]
                ano_original int null
                descricao text null
                idioma_original text null
                capa_url text null
                origem enum('base','leitor')    -- 'base' = veio da Base de coleitura
                goodbooks_book_id int null UNIQUE
                ol_work_key text null UNIQUE    -- ex.: /works/OL893415W
                popularidade int default 0      -- nº de Notas na Base de coleitura
                tem_edicao_pt bool default false -- alguma Edição em português conhecida (§6.2, §7.2)
                embedding vector(1024) null     -- dimensão comum do bake-off (§8.4.1)
                embedding_execucao_id FK null
                enriquecida_em timestamptz null
                criado_em
                índices: GIN trigram em (titulo, titulo_original, titulo_exibicao);
                         GIN trigram em obra_texto_busca(títulos, autores), sem acento (§7.1);
                         HNSW (vector_cosine_ops) em embedding

obra_isbn       isbn13 char(13) PK · obra_id FK      -- todos os ISBNs conhecidos de cada Obra
                origem enum('base','open_library','leitor')   -- quem gravou (§6.1, §6.2, §7.2)

edicao          id bigserial PK · obra_id FK
                google_volume_id text null UNIQUE · ol_edition_key text null
                isbn13 null · titulo · autores text[] · editora null · ano null
                idioma null · capa_url null

genero          id smallserial PK · slug UNIQUE · nome
genero_tag      genero_id FK · tag text           -- mapeamento curado (§6.3)
obra_genero     obra_id FK · genero_id FK · forca real    -- PK (obra_id, genero_id)
obra_tag        obra_id FK · tag text · contagem int      -- top 30 tags úteis por Obra

leitura         id bigserial PK · leitor_id FK · obra_id FK · edicao_id FK null
                nota smallint null CHECK (nota BETWEEN 1 AND 5)
                origem enum('busca','montagem','sugestao','manual','catalogo')
                criado_em · atualizado_em
                UNIQUE (leitor_id, obra_id)       -- deduplicação de R1 (mesma Obra)

execucao_modelo id bigserial PK · tipo enum('conteudo','coleitura')
                modelo text · parametros jsonb · metricas jsonb null
                ativa bool · criado_em
                -- no máximo uma ativa por tipo (índice único parcial)

vizinho         execucao_id FK · obra_id FK · vizinho_id FK
                similaridade real · posicao smallint
                PK (execucao_id, obra_id, vizinho_id)
                índice (execucao_id, obra_id, posicao)

evento          id bigserial PK · leitor_id FK · tipo text · obra_id null
                dados jsonb · criado_em

dispensa        leitor_id FK · obra_id FK · criado_em            -- R7; PK (leitor_id, obra_id)
quero_ler       leitor_id FK · obra_id FK · criado_em            -- R8; PK (leitor_id, obra_id)
                posicao smallint null   -- posição em "Para você" quando foi salva (O5)
estou_lendo     leitor_id FK · obra_id FK · criado_em            -- R13; PK (leitor_id, obra_id)
                posicao smallint null   -- idem; vem de quero_ler quando a Obra passa de lá
```

Decisões do modelo:

- **As Notas brutas da Base de coleitura não vão para o Postgres.** Elas ficam em `data/raw/` como Parquet e só o `pipeline/` as lê. O banco guarda o resultado (Vizinhos), o que mantém os backups pequenos (ADR 0004).
- `vizinho` é ligado à `execucao_modelo`. Para trocar de modelo, basta inserir uma execução nova e virar `ativa` numa única transação. O app sempre lê só as execuções ativas.
- O tipo do Vizinho (conteúdo ou coleitura) vem de `execucao_modelo.tipo`.
- Uma Obra adicionada pelo Leitor recebe Vizinhos de conteúdo na execução de conteúdo **ativa**, com `obra_id` = a Obra nova. Ela nunca tem Vizinhos de coleitura.
- `dispensa` e `quero_ler` entram na fase 4 (migração 0006, §8.6). Uma Obra fica em no máximo uma das duas: salvar em Quero ler desfaz a Dispensa, e dispensar tira da lista.
- `estou_lendo` entra na fase 5 (migração 0007, §8.7). A regra passa a valer para as três: uma Obra fica em no máximo uma de `dispensa`, `quero_ler` e `estou_lendo`.

---

## 5. Fontes externas

| Fonte | Uso | Como | Limites e cuidados |
|---|---|---|---|
| goodbooks-10k | Base de coleitura e semente do Catálogo (ADR 0003) | Download único dos Releases do GitHub para `data/raw/`. Arquivos: `books.csv`, `ratings.csv`, `tags.csv`, `book_tags.csv`. | CC BY-SA 4.0: citar a fonte no rodapé do app |
| Open Library (dumps) | Enriquecer as Obras do Catálogo: descrição, assuntos, ISBNs de todas as Edições e título em português | Dumps `works`, `editions` e `authors` em `data/ol/`, processados em streaming (§6.2) | ~12 GB no total. Atualizar no máximo a cada poucos meses, por comando manual. |
| Open Library (API) | Resolver a Edição escolhida na busca e enriquecer as Obras adicionadas pelo Leitor | `/isbn/{isbn}.json`, `/works/{key}.json`, com `User-Agent` identificado | Máx. 1 req/s, garantido por um limitador no cliente. Usar só para o volume de um Leitor. |
| Google Books | Busca do R1 | `GET /books/v1/volumes?q=…&maxResults=20&printType=books&key=…` | Cache só durante a sessão (TTL de 1 h, `st.cache_data`). O que é persistido em `edicao` e `obra` vem de preferência da Open Library, e a capa entra por URL (ver research/fontes-de-dados.md). |

Os clientes ficam em `catalogo/fontes/`. Eles têm timeout (1,8 s na busca do Google Books, para a busca inteira caber em 2 s; 10 s na Open Library) e devolvem tipos próprios (`ResultadoBusca`, `EdicaoOL`, `ObraOL`), nunca o JSON cru.

---

## 6. Fase 0: fundação e carga do Catálogo

Comandos (`python -m recomendador <comando>`, via `typer`):

| Comando | Faz | Idempotente? |
|---|---|---|
| `db-subir` | `alembic upgrade head` e cria o Leitor e os Gêneros | Sim |
| `carregar-base` | Baixa (se faltar) e carrega o goodbooks-10k: 10 mil Obras (`origem='base'`), `obra_isbn`, `obra_tag` e Parquet das Notas | Sim (upsert por `goodbooks_book_id`) |
| `enriquecer-ol --dumps data/ol` | §6.2 | Sim |
| `mapear-generos` | §6.3 | Sim |
| `calcular-conteudo --modelo X` | §8.2. Cria uma execução de conteúdo **inativa**: Vizinhos em `vizinho`, embeddings em `data/embeddings/conteudo-<id>.npz`. | Cria uma execução nova |
| `bakeoff` | §8.4. `calcular-conteudo` de cada finalista, teste entre idiomas, tempo de uma Obra e `avaliar` de todos. Não ativa nada. | Cria execuções novas |
| `calcular-coleitura [--k 20 --lambda 10 --min-coleitores 5]` | §8.1. Cria uma execução de coleitura **inativa**. | Cria uma execução nova |
| `avaliar <execucao_id>… [--sem-varredura]` | §9. Grava `metricas` e escreve `reports/avaliacao-AAAA-MM-DD.md`. Com uma execução de conteúdo e uma de coleitura, avalia também as duas juntas e faz a varredura do §9.4 (grade completa em `reports/varredura-AAAA-MM-DD.csv`). | Sim |
| `ativar <execucao_id> [--forcar]` | Torna a execução ativa e desativa a anterior do mesmo tipo, se passar no critério do §9.4. Numa de conteúdo, copia os embeddings dela para `obra.embedding`. | Sim |
| `recalcular [--modelo X] [--sem-conteudo]` | `calcular-conteudo` (com o modelo da execução ativa) + `calcular-coleitura` + `avaliar` das novas junto com as ativas + `ativar` de cada nova que passar no critério do §9.4. `--sem-conteudo` pula o passo da GPU. | n/a |
| `atualizar` | Rotina de abertura do app (§10) | Sim |

### 6.1 Carga do goodbooks-10k

- Cada linha de `books.csv` vira uma Obra:
  - `titulo` = `title` sem o sufixo de série entre parênteses;
  - `titulo_original` = `original_title`;
  - `autores` = `authors` separado por vírgula;
  - `ano_original` = `original_publication_year`;
  - `capa_url` = `image_url`, a menos que seja o placeholder "nophoto";
  - `popularidade` = `work_ratings_count`.
- `isbn` e `isbn13` vão para `obra_isbn` com `origem='base'`, com ISBN-10 convertido para 13. Um desses ISBNs que o `enriquecer-ol` tenha posto em outra Obra volta para a da Base; um gravado pela Resolução (`origem='leitor'`) fica onde está. Os de origem `base` que o CSV não dá mais são apagados.
- O `isbn13` do CSV está em notação científica com 12 algarismos ("9.78006112008e+12"): perdeu o dígito verificador e, quando ele era 5 ou mais, o 12º algarismo subiu 1. Daí saem até dois ISBN-13 válidos, e um deles costuma ser de outro livro da mesma editora (*A Tree Grows in Brooklyn* ficava com o ISBN de *To Kill a Mockingbird*). O ISBN-10 é exato: se ele é um dos candidatos, vale sozinho. Senão, o ISBN-13 entra só quando sobra um candidato.
- `book_tags.csv` + `tags.csv` vão para `obra_tag`, depois de remover as tags genéricas ou de status (lista de exclusão em `catalogo/tags_ignoradas.txt`: `to-read`, `currently-reading`, `favorites`, `owned`, `books-i-own`, `kindle`, `ebook`, `library`, `default`, `wish-list`, nomes de anos etc.).
- `ratings.csv` vira `data/raw/notas.parquet` (`usuario_base`, `goodbooks_book_id`, `nota`).
- Os nomes exatos das colunas são conferidos na carga. Se divergirem, a carga falha com uma mensagem clara.
- **Duplicatas** (decisão do Leitor, 19/11/2026): duas entradas do goodbooks-10k para o mesmo texto viram uma Obra só (`carga_goodbooks.FUSOES`). Fica a entrada com work na Open Library: *Alice in Wonderland* (257) entra em *Alice's Adventures in Wonderland* (1725), e a coletânea *Batman: The Dark Knight Returns* (568) entra na entrada "#1" (2100), que passa a usar o título da coletânea.
  - A duplicada não vira Obra. As Notas dela passam para a que fica, e quem deu Nota às duas fica com a Nota da que fica. Os ISBNs e as tags dela também passam, e a popularidade é a soma das duas.
  - Uma Obra da duplicada que já esteja no banco é fundida a cada carga. As Leituras, Dispensas, Quero ler, Edições, Eventos e ISBNs passam para a que fica (havendo conflito, vale o da que fica). Os Vizinhos dela saem, e o `recalcular` seguinte refaz a Coleitura.

### 6.2 Enriquecimento pelos dumps da Open Library

Processamento em streaming, sem carregar os dumps inteiros na memória:

1. **Editions**: para cada Edição do dump com ISBN da Obra em `obra_isbn` de origem `base` ou `leitor`, marca o `work_key` dela para a Obra (vale o mais frequente). A work votada é conferida contra as works do dump de mesmo título normalizado (com o subtítulo, se houver) e com uma chave de autor em comum com outras Obras do mesmo autor, já que a Open Library tem várias works e vários registros de autor para o mesmo texto: vence a de mais Edições. Uma votada cujo título não tem nenhuma palavra igual ou quase igual (erro de digitação, cognato) à do título da Obra é de outra Obra: o ISBN caiu na work errada na Open Library (*Dune*, cujo único ISBN da Base aponta para a work de *Shōgun*; *Hamlet*, que caía em *The Merchant of Venice*). Ela perde para qualquer candidata e, se for de outro autor e não houver candidata, é descartada. Uma work fica com uma Obra só. Na disputa, passa na frente a Obra de título igual ao da work (com ou sem o subtítulo) e, depois, a que votou nela: o roteiro de *Hamlet* de Branagh, que está na Base e cujo ISBN cai numa Edição da work de *Hamlet*, perde para *Hamlet*. Quando a work de uma Obra muda, a descrição que veio da work anterior é apagada. A mesma busca dá work às Obras sem nenhum ISBN no dump. Uma segunda passada sobre o dump de editions coleta **todos** os ISBNs dessas works para `obra_isbn` com `origem='open_library'` (é o que faz as Edições brasileiras caírem direto no passo 1 do §7.2). Os ISBNs de origem `open_library` da execução anterior são apagados antes e não votam: vieram da work escolhida antes e manteriam um erro dela (uma Edição de *Hamlet* chegou a cair em *Twelfth Night*). Um ISBN que já está em `obra_isbn` com outra origem fica com a Obra que tem. Logo depois da migração 0004, que criou a coluna, rode o `carregar-base` antes do `enriquecer-ol`: a migração só soube separar os ISBNs do Leitor e marcou o resto como `open_library`. A mesma passada grava, por Obra, o título da Edição em português de data mais recente (`languages` contém `/languages/por`) como `titulo_exibicao`. Uma Edição sem `languages` e com ISBN brasileiro (prefixos 978-85 e 978-65) também conta como em português, mas só na falta de uma que declare o idioma (decisão do Leitor, 18/11/2026). Sem Edição em português, `titulo_exibicao = titulo`. Com qualquer Edição em português, pelo mesmo critério, a Obra recebe `tem_edicao_pt = true`, que o filtro de idioma usa (R10, §8.6); sem nenhuma, volta a `false`, a menos que uma Edição gravada pelo Leitor seja em português.
2. **Works**: para as works marcadas, preenche `descricao` (se a Obra não tiver), os assuntos (`subjects`, que entram em `obra_tag` com `contagem = 0` para não competir com as tags de leitores) e `ol_work_key`.
3. Marca `enriquecida_em`.

Saída esperada (registrada em log): % de Obras com `ol_work_key`, % com descrição e % com título em português, e quantas works votadas foram trocadas, descartadas ou achadas na conferência. Alerta se a cobertura de descrição ficar abaixo de 70 %.

### 6.3 Gêneros

Lista revisada e aprovada sem mudanças pelo Leitor (18/11/2026). Fica em `catalogo/generos.yaml` com as tags que mapeiam cada Gênero:

| Gênero | Tags de exemplo |
|---|---|
| Fantasia | fantasy, epic-fantasy, urban-fantasy, magic |
| Ficção científica | science-fiction, sci-fi, dystopia, space-opera, cyberpunk |
| Terror | horror |
| Suspense e thriller | thriller, suspense, psychological-thriller |
| Mistério e policial | mystery, crime, detective, murder-mystery |
| Romance amoroso | romance, contemporary-romance, historical-romance |
| Ficção histórica | historical-fiction |
| Clássicos | classics, classic-literature |
| Ficção contemporânea | literary-fiction, contemporary, fiction |
| Jovem adulto | young-adult, ya, teen |
| Infantil | childrens, children, picture-books, middle-grade |
| Biografias e memórias | biography, memoir, autobiography |
| História | history, world-war-ii |
| Ciência e divulgação | science, popular-science, psychology |
| Negócios e autoajuda | business, self-help, personal-development, productivity |
| Filosofia e religião | philosophy, religion, spirituality |
| Poesia | poetry |
| Quadrinhos | graphic-novels, comics, manga |

`obra_genero.forca` = soma das `contagem` das tags do Gênero na Obra ÷ soma de todas as `contagem` úteis da Obra. Uma Obra pertence ao Gênero se `forca ≥ 0,05`.

---

## 7. Fase 1: Estante e Montagem da Estante

### 7.1 Busca (R1)

`catalogo.buscar(texto) -> list[ResultadoBusca]`, com duas fontes em paralelo:

1. **Catálogo local**: busca por trigram em `titulo`, `titulo_original`, `titulo_exibicao` e `autores`, mais igualdade em `obra_isbn` se o texto for um ISBN. Resultados marcados como "no catálogo", sem precisar de resolução.
   - Títulos e autores vão num texto só, em minúsculas e sem acento (`obra_texto_busca`, com `unaccent`, migração 0003), com um índice GIN trigram. "fundacao asimov" acha *Fundação*.
   - Cada palavra útil da busca (sem "de", "o", "the"…) é comparada com esse texto por `word_similarity`, e a semelhança da Obra é a média entre as palavras (mínimo 0,5). "duna herbert" precisa casar com as duas palavras: *Lincoln*, de David **Herbert** Donald, fica abaixo de *Duna*. Empates vão para a mais popular.
2. **Google Books**: `q` montado por heurística. Texto com só dígitos e hífens de 10 ou 13 dígitos vira `isbn:…`; o resto vai como texto livre. Resultados cujo ISBN já está em `obra_isbn` são fundidos ao item do catálogo correspondente: uma Edição em português toma o lugar dele (é o título que o Leitor reconhece); em outro idioma, o item do Catálogo fica como está, sem repetir a Obra.

A lista mostra primeiro os itens do catálogo e depois os do Google Books, com capa, título, autor e ano. Meta: **≤ 2 s no p95**. Se o Google Books estourar o timeout, mostra só os resultados locais e um aviso discreto.

### 7.2 Resolução Edição → Obra

`catalogo.resolver_obra(resultado) -> Resolucao`, aplicada ao escolher um resultado do Google Books. A ordem é esta, e a primeira que acertar vence:

| # | Regra | Resultado |
|---|---|---|
| 1 | Algum ISBN da Edição está em `obra_isbn` | Obra existente (`confianca='isbn'`) |
| 2 | Open Library `/isbn/{isbn}` → `works[0].key` igual a `obra.ol_work_key` | Obra existente (`'ol_work'`) |
| 3 | Título original (de `translation_of` ou `work_titles` da Edição na OL, ou o título da work) + último sobrenome do 1º autor bate com uma Obra (`rapidfuzz.token_set_ratio ≥ 90` no título e sobrenome igual depois de normalizar acentos) | Obra existente (`'titulo_original'`) |
| 4 | Nenhuma das anteriores | Cria uma Obra `origem='leitor'` com os dados da OL (ou do Google Books, se a OL não tiver) e devolve `candidatas`: as 5 Obras do Catálogo mais próximas por trigram de título e autor |

- `resolver_obra` **não grava nada**: devolve a Obra encontrada ou, no caso 4, a proposta da Obra nova e as candidatas. `registrar_resolucao` grava quando o Leitor salva a Leitura, na mesma transação. Assim, uma busca abandonada não deixa Obra órfã no Catálogo, e não é preciso fundir Obras depois.
- No caso 4, a UI pergunta **"É uma destas?"**. Escolher uma candidata grava a Edição e a Leitura nela; "Nenhuma" cria a Obra nova. O Leitor também pode informar o título original à mão (R1): `informar_titulo_original` reaplica a regra 3 com ele.
- Na regra 3, o título da própria Edição também entra entre os títulos comparados (cobre as Edições no idioma original e funciona com a Open Library fora do ar). `token_set_ratio` dá 100 para "Dune" × "Dune Messiah"; o `ratio` simples desempata. O sobrenome ignora sufixos como Jr., Junior, Filho e Neto.
- Em qualquer caso, a Edição escolhida é gravada em `edicao`, ligada à Obra, e os ISBNs dela entram em `obra_isbn` com `origem='leitor'` (a próxima busca resolve pela regra 1, e o `enriquecer-ol` não os apaga). Um ISBN da Edição que já estava lá com origem `open_library` passa a ser do Leitor e da Obra que ele confirmou. Se a Edição é em português e a Obra ainda não tem título em português (`titulo_exibicao = titulo`), o título da Edição vira o `titulo_exibicao` (decisão do Leitor, 18/11/2026). Uma Edição em português (`idioma = 'pt'` no Google Books ou `por` na Open Library) também marca `obra.tem_edicao_pt`.
- No banco real, *Dune* (goodbooks) ficou ligada a uma work duplicada da Open Library (`/works/OL2918756W`); a canônica é `/works/OL893414W`. Por isso a *Duna* da Aleph chega a *Dune* pela regra 3, não pela 1 nem pela 2.
- Se a Obra já estiver na Estante, a UI avisa ("Você já tem *Duna* na Estante, com nota 5") e não cria nada (R1).
- **Cadastro manual** (R1, história 11): título + autor criam uma Obra `origem='leitor'` sem Edição, e passam pelos passos 3 e 4 com o texto digitado.

### 7.3 Adicionar uma Leitura

`estante.adicionar(leitor_id, obra_id, nota, edicao_id=None, origem) -> Leitura`:

- Respeita `UNIQUE (leitor_id, obra_id)` e devolve um erro de domínio `JaNaEstante` se a Obra já estiver lá.
- Se a Obra é `origem='leitor'` e ainda não tem o `embedding` da execução de conteúdo ativa, o app calcula na hora, depois de salvar a Leitura e numa transação à parte (`recomendacao.calcular_vizinhos_da_obra`): gera o embedding com o modelo ativo (carregado uma vez por `st.cache_resource`), grava `obra.embedding` e insere os 50 Vizinhos de conteúdo via KNN no pgvector, restrito a `origem='base'`, com o mesmo limite de 5 Obras do mesmo autor do §8.2. Se falhar (GPU ocupada, modelo ausente), a Leitura já está salva e a Obra fica pendente para o `atualizar` (§10).
- A Nota pode ficar vazia (R2): a Leitura vai para a Estante, mas fica fora da pontuação.

`estante.mudar_nota(...)` e `estante.remover(...)` (R2) agem direto na tabela. Como as Sugestões são calculadas na leitura (§8.5), a mudança aparece na próxima abertura de "Para você", sem nenhum recálculo.

### 7.4 Montagem da Estante

Abre automaticamente enquanto o Leitor tem **menos de 5 Leituras com Nota** e ainda não clicou em "Pular" (gravado como o evento `montagem_pulada`). Também fica acessível pelo menu.

Obras sem `capa_url` (3.332 da base) recebem uma capa de reserva gerada localmente (SVG com título e autor), sem chamar a Covers API, que limita a busca por ISBN a 100 requisições a cada 5 min.

1. **Gêneros:** chips de seleção múltipla (`st.pills`) com a lista do §6.3. É preciso escolher pelo menos 1.
2. **Grade:** 24 Obras do Catálogo por página, fora da Estante, intercaladas por Gênero escolhido (round-robin) e, dentro de cada Gênero, ordenadas por `popularidade × forca`. Cada card tem capa, `titulo_exibicao`, autor, um seletor de Nota (`st.feedback("stars")`) e o botão **"Não li"**, que tira o card desta sessão. Há o botão "Mostrar mais".
3. **Contador:** "3 de 5 Notas". Ao chegar a 5, aparece o botão **"Ver minhas sugestões"**. Na fase 1, como "Para você" ainda não existe, ele leva à Estante.
4. Um campo "Não achou? Buscar livro" abre a busca do §7.1 no mesmo fluxo.

As Leituras criadas aqui recebem `origem='montagem'`.

### 7.5 Estante (R3)

- Lista com capa, `titulo_exibicao`, autor e Nota (editável na própria linha).
- Ordenação por Nota ou por data de inclusão, decrescente.
- Estante vazia: chamada para a Montagem da Estante.
- Remover pede confirmação.

### 7.6 Eventos (métricas do PRD §7)

`estante.registrar_evento(tipo, obra_id=None, **dados)`. Tipos da v1:

| tipo | dados | mede |
|---|---|---|
| `busca_iniciada` | `{texto}` | O3 (início) |
| `leitura_salva` | `{origem, duracao_s, com_nota}`, onde `duracao_s` = tempo desde o último `busca_iniciada` da sessão | O3 |
| `nota_alterada` | `{de, para}` | — |
| `leitura_removida` | `{nota}` | — |
| `sugestao_exibida` | `{posicao, pontuacao, motivo_obra_id, execucoes}`, uma vez por item por abertura da lista | O2 |
| `sugestao_aberta` | `{posicao}` | O2 |
| `ja_li_de_sugestao` | `{posicao, nota}` | O5 |
| `montagem_pulada` | `{}` | — (fecha a abertura automática da Montagem) |
| `sugestao_dispensada` | `{posicao}`, com `posicao` nula fora de "Para você" | O2 (R7) |
| `quero_ler_salvo` | `{posicao}`, idem | O2 (R8) |
| `leitura_iniciada` | `{posicao}`, idem; vinda de Quero ler, a posição salva lá | — (R13) |

A página "Métricas" é um P1 opcional. Na v1 basta consultar com SQL. A SPEC traz as consultas de O2, O3 e O5 em `reports/consultas-metricas.sql`, que faz parte da entrega da fase 1.

---

## 8. Fases 2 e 3: recomendação

### 8.1 Coleitura (item-item, cosseno ajustado)

Calculada sobre `data/raw/notas.parquet` (na avaliação, só sobre o conjunto de treino do §9).

```
R[u,i]   = nota − média_do_leitor_u    (só nas Notas que existem; matriz esparsa 53 mil × 10 mil)
num[i,j] = Σ_u R[u,i]·R[u,j]                       → Rᵀ R esparso, no CPU, por blocos de 1.000 Obras
n[i,j]   = nº de leitores que deram Nota a i e a j → Bᵀ B, B binária
sim[i,j] = num[i,j] / (‖R[:,i]‖·‖R[:,j]‖) × n[i,j] / (n[i,j] + λ)
```

- As normas usam todos os leitores de cada Obra (aproximação usual).
- O produto roda no CPU (scipy, float64): com as 6 milhões de Notas leva ~14 s, e a GPU não ganha nada (medido em 19/11/2026: 2,5 s no CPU contra 1,9 s na GPU, em fp32).
- **λ = 10** (encolhimento para pares com poucos coleitores). Pares com `n[i,j] < 5` são zerados.
- Por Obra, guarda os **K = 20** maiores `sim > 0`.
- K e λ foram calibrados no §9.4 (ADR 0007). O ponto de partida era K = 50 e λ = 50, e a diferença no NDCG@20 ficou abaixo de 3 %.
- `parametros.escala` guarda a média das similaridades dos Vizinhos gravados, que a mistura do §8.5 usa.
- ALS (`implicit`, GPU) é o candidato alternativo. A similaridade vem do cosseno entre vetores de item, e a saída tem o mesmo formato (`vizinho`). Ele só entra se ganhar na avaliação (§9).

### 8.2 Similaridade de conteúdo (embeddings)

- **Texto de cada Obra**, montado por `recomendacao.texto_da_obra(obra)`:
  ```
  {titulo} ({titulo_original}). Autor: {autores}. Gêneros: {gêneros}. Temas: {top 15 tags + assuntos}. {descrição, até 1.500 caracteres}
  ```
  O título original só entra se for diferente, e as partes vazias saem. Os temas são até 15 tags de leitores (as de maior contagem) e até 10 assuntos da Open Library, em minúsculas e sem repetir. A descrição é cortada na última palavra inteira, com "…".
  O prefixo ou instrução exigido pelo modelo vencedor é aplicado por `recomendacao.embeddings`, num único lugar.
- O embedding é normalizado (norma 1). A similaridade é o cosseno.
- **Em lote:** todas as Obras do Catálogo na GPU, em batches de 64, fp16. Os Vizinhos saem de `E Eᵀ` por blocos, guardando os top K = 50, sem a própria Obra e com **as Obras do mesmo autor limitadas a 5** (senão uma série domina a lista).
- **Interativo:** uma Obra por vez (§7.3), com KNN no pgvector (índice HNSW, `vector_cosine_ops`).
- O modelo é carregado uma vez por processo e o nome dele fica em `execucao_modelo.modelo`.
- **Embeddings por execução:** `calcular-conteudo` guarda os embeddings em `data/embeddings/conteudo-<execucao>.npz`, e só o `ativar` os copia para `obra.embedding` (com `embedding_execucao_id`). Assim o bake-off calcula vários modelos sem mexer no que o app usa. As Obras do Leitor que a execução ativada não cobre ficam pendentes para o `atualizar`.

### 8.3 Página da Obra (R5)

`recomendacao.pagina_da_obra(obra_id, leitor_id) -> PaginaObra`:

- Mostra capa, `titulo_exibicao` (com o título original abaixo, se for diferente), autor, ano, descrição, Gêneros, a Nota do Leitor (se já leu) e as ações.
- **R5a "Parecidos com este":** os top 10 Vizinhos da execução de conteúdo ativa.
- **R5b "Quem leu este também gostou":** os top 10 Vizinhos da execução de coleitura ativa. Se não houver nenhum, mostra o texto exato do PRD: "Ainda não há dados de outros leitores para este livro". Nenhuma outra fonte preenche a seção.
- Obras da Estante aparecem com o selo **"lido"**.
- Cada item é um link para `?obra=<id>`, o que permite navegar em cadeia.
- Livro sugerido e não lido tem o botão **"Já li"**, que abre a Nota e grava a Leitura com `origem='sugestao'` (R1 + R2 num passo).

### 8.4 Bake-off do modelo de embedding

Finalistas: **ver §8.4.1** (preenchido a partir de `research/modelos-embedding.md`).

Para cada finalista:

O comando `bakeoff` faz os três passos para cada finalista e avalia todos juntos.

1. `calcular-conteudo --modelo X` gera uma execução inativa.
2. `avaliar`, com α = 1 (só conteúdo), produz o NDCG@20 e o Recall@20 do §9.
3. **Teste entre idiomas:** em `tests/dados/pares_pt_en.yaml`, 20 Obras do Catálogo com um texto em português, montado com a descrição de uma Edição brasileira (Google Books), e o texto em inglês do Catálogo. Critério: em ≥ 18 de 20, o embedding do texto em português tem a própria Obra entre os 3 vizinhos mais próximos do Catálogo.
   - O texto em português imita uma Obra do Leitor vinda de uma Edição brasileira: título, autor e descrição, sem tags.
   - Os pares são as Obras mais populares com uma Edição brasileira (ISBN 978-85 ou 978-65) cuja descrição o Google Books tem em português, uma por autor.
   - Como o repositório é público e as descrições são textos das editoras, o YAML guarda só os identificadores (Obra, ISBN, volume do Google Books, título). As descrições ficam no cache local `data/bakeoff/pares_pt_en.json`, refeito pelo Google Books quando falta.

**Vencedor:** o maior NDCG@20 entre os que passam no teste entre idiomas. Em empate (diferença < 0,005), vence o menor e mais rápido. O resultado vira o ADR 0006, com os números.

**Resultado (18/11/2026, ADR 0006):** `Qwen/Qwen3-Embedding-4B`, com NDCG@20 de 0,1143 (β = 0,25), 19/20 no teste entre idiomas e 126 ms por Obra. O harrier reprovou no teste entre idiomas (16/20); o jina passou (20/20), com NDCG@20 menor (0,0919). Sem o peso da popularidade, nenhum dos três vencia o baseline de popularidade.

#### 8.4.1 Finalistas

Fonte: [research/modelos-embedding.md](research/modelos-embedding.md), com as notas do MTEB(Multilingual, v2) recalculadas a partir dos resultados oficiais em 17/11/2026. Todos os finalistas cabem em 12 GB em fp16.

| # | Modelo | Licença | Tamanho (VRAM fp16) | Dimensão usada | Por que está aqui |
|---|---|---|---|---|---|
| 1 | `Qwen/Qwen3-Embedding-4B` | Apache 2.0 | 4 B (~8 GB) | 1024 (truncado via MRL de 2560) | Melhor qualidade entre os que cabem (6º no MMTEB, 69,45) |
| 2 | `harrier-oss-v1-0.6b` | MIT | 0,6 B (~1,2 GB) | 1024 (nativo) | Nota quase igual (69,01) com 1/7 do tamanho; o mais rápido no fluxo interativo |
| 3 | `jina-embeddings-v5-text-small` | CC BY-NC 4.0 | pequeno | 1024 (adaptador `text-matching`) | Adaptador próprio para similaridade texto-texto, que é exatamente o nosso caso |

Regras do bake-off:

- **Mesma dimensão para todos (1024):** a comparação fica justa e cabe no limite de índice HNSW do pgvector (2.000 em `vector`). Com isso, `obra.embedding` passa a ser `vector(1024)`.
- **Prefixos e instruções:** cada modelo usa o formato que o model card manda para **documento**. Os dois lados da comparação são documentos (Obra × Obra), então nenhum dos dois recebe a instrução de query.
- **Licença:** o finalista 3 é não comercial. Isso não importa para o uso pessoal da v1, mas, se ele vencer, o ADR 0006 tem que registrar que a hospedagem comercial (P2) exige trocar de modelo. Substitutos se ele for descartado: `Qwen/Qwen3-Embedding-0.6B` ou `BAAI/bge-m3`.
- **Desempate prático:** além do critério do §8.4, o finalista precisa gerar o embedding de uma Obra em **< 1 s** na RTX 3060 com o Streamlit aberto (§7.3). Se o 4B ganhar em NDCG por < 0,01 e não cumprir o tempo, vence o 0,6B.
- **Não confirmado na pesquisa** e medido no próprio bake-off: VRAM real com lote, latência real e se o MRL do harrier funciona.

### 8.5 "Para você" (R4)

`recomendacao.para_voce(leitor_id, limite=20, generos=(), so_edicao_pt=False) -> ParaVoce`, implementada como **uma consulta SQL** sobre as execuções ativas:

```
peso(nota):  5 → +1,0 · 4 → +0,6 · 3 → 0 · 2 → −0,5 · 1 → −1,0       (tabela em config)

para cada Leitura r com Nota e peso ≠ 0:
  para cada Vizinho c de r (conteúdo e coleitura, execuções ativas):
    parcela(c, r) = peso(nota_r) × [ α·sim_conteudo(r→c)/escala_conteudo
                                     + (1−α)·sim_coleitura(r→c)/escala_coleitura ]
                    (similaridade ausente = 0; escala = parametros.escala da execução, ADR 0007)

soma(c)      = Σ_r parcela(c, r)
pontuacao(c) = soma(c) × (1 + popularidade(c))^β                     (ADR 0006)
candidatos   = c ∉ Estante, c ∉ Dispensas, c ∉ Quero ler  e  pontuacao(c) > 0
filtros      = Gênero e idioma (R10), depois da pontuação (§8.6)
ordem        = pontuacao desc, depois popularidade desc
Contribuintes(c) = os 3 r com maior parcela(c, r) > 0, com parcela ÷ Σ parcelas positivas (R11)
Motivo(c)    = o primeiro Contribuinte
```

- **Escala:** cada execução divide as suas similaridades pela média delas (`execucao_modelo.parametros.escala`) antes da mistura. Sem isso, o conteúdo (~0,55 de média com o Qwen3-4B) engole a Coleitura (~0,07) em qualquer α razoável (ADR 0007). Execução sem escala vale 1.
- **α** fica em config: 1,0 na fase 2 e **0,25** desde a calibração da fase 3 (ADR 0007).
- **β** (peso da popularidade) fica em config: 0,25 no bake-off (ADR 0006), 0 na calibração da fase 3 e **0,25** de novo por decisão do Leitor (ADR 0007, atualização de 19/11/2026). O fator é positivo, então não muda quem é candidata (soma > 0), a exclusão da Estante nem o Motivo: só a ordem.
- Como a "Obra" é a unidade (ADR 0001), excluir a Estante já exclui todas as Edições e traduções (critério do R4).
- O Motivo nunca é uma Leitura com Nota ≤ 3, porque o peso dessas é ≤ 0 e a parcela não pode ser positiva. A consulta também só aceita Motivo de peso > 0, para o caso raro de similaridade negativa. O texto é "Porque você deu {nota} a *{titulo_exibicao}*".
- **Menos de 3 Leituras com Nota:** não calcula. Mostra "Avalie pelo menos 3 livros para receber sugestões" e um contador "{n} de 3", com um link para a Montagem da Estante.
- Meta de desempenho: **≤ 500 ms** com 500 Leituras na Estante.

### 8.6 Fase 4: Ajustes (R7, R8, R10, R11)

Decisões do Leitor (19/11/2026): o filtro de idioma usa as Edições em português; Quero ler é uma página própria; a Obra salva em Quero ler sai de "Para você"; a Obra dispensada sai só de "Para você".

**R7, Dispensa.** `estante.dispensar(leitor_id, obra_id, posicao=None)` grava em `dispensa` (repetir não duplica), tira a Obra de Quero ler e registra `sugestao_dispensada`. `estante.desfazer_dispensa(...)` apaga a linha.
- A consulta do §8.5 exclui as Dispensas das candidatas. A pontuação das outras não muda, e a vaga vai para a próxima Sugestão.
- A Obra dispensada continua em "Parecidos com este" e "Quem leu este também gostou". A página dela mostra "Você dispensou este livro de Para você" e o botão "Desfazer".
- A avaliação offline (§9) não tem Dispensas. `recomendacao.pontuacao` não muda, e o teste de paridade com o SQL continua o mesmo.

**R8, Quero ler.** `estante.salvar_quero_ler(leitor_id, obra_id, posicao=None)` grava em `quero_ler`, desfaz uma Dispensa da Obra e registra `quero_ler_salvo`. Uma Obra da Estante levanta `JaNaEstante`. `estante.tirar_de_quero_ler(...)` apaga a linha, e `estante.listar_quero_ler(leitor_id)` devolve a lista, da mais recente para a mais antiga.
- `estante.adicionar` tira a Obra de Quero ler na mesma transação. É o "Já li" do R8.
- As Obras de Quero ler saem das candidatas do §8.5.
- `quero_ler.posicao` guarda a posição em "Para você" quando a Obra foi salva de lá. O "Já li" na página Quero ler grava essas Obras com `origem='sugestao'` e registra `ja_li_de_sugestao` com essa posição (O5). As salvas da página da Obra entram com `origem='catalogo'`.

**R10, filtros.** `para_voce(..., generos=("fantasia", ...), so_edicao_pt=True)`.
- **Gênero:** a Obra passa se pertence a **algum** dos Gêneros escolhidos (linha em `obra_genero`, §6.3).
- **Idioma:** com `so_edicao_pt`, passa só a Obra com `tem_edicao_pt`. A coluna vem dos dumps da Open Library (§6.2) e das Edições gravadas pelo Leitor (§7.2). A migração 0006 a preenche provisoriamente com `titulo_exibicao <> titulo`, que só acerta as Obras com título em português diferente do canônico. O próximo `enriquecer-ol` completa.
- Os filtros entram no `WHERE` final da consulta, depois da pontuação. A pontuação e a ordem relativa das Sugestões que passam são as mesmas da lista sem filtro, e o `LIMIT` vem depois do filtro, então a lista filtrada não fica curta à toa.
- Na UI, os filtros ficam no topo de "Para você": chips de Gênero (`st.pills`, seleção múltipla) e a chave "Só com edição em português". Mudar um filtro conta como nova abertura para o `sugestao_exibida`.

**R11, Motivo detalhado.** `Sugestao.contribuintes` traz até 3 `Contribuinte(obra_id, titulo_exibicao, nota, participacao)`, em ordem de parcela. `participacao` = parcela ÷ soma das parcelas positivas da Sugestão, de 0 a 1. O primeiro é o Motivo (`motivo_obra_id`). Os campos `motivo_*` continuam, para o evento `sugestao_exibida`.
- A consulta calcula os contribuintes na CTE das parcelas, com `row_number()` em vez do `DISTINCT ON`.
- O texto é montado só na UI (§13, LLM nos Motivos). Num popover "Por quê?" do card, cada linha mostra "*{titulo}*, sua nota {nota}: {participacao} %".

### 8.7 Fase 5: Estou lendo (R13)

Decisões do Leitor (19/11/2026, [ADR 0008](adr/0008-estou-lendo-sem-progresso.md)): "Estou lendo" é uma lista, sem página nem percentual; tem página própria; entra por "Para você", Quero ler e a página da Obra; Obra da Estante não entra (sem releitura); a Dispensa tira da lista.

**Domínio** (`recomendador/estante/listas.py`). `estante.salvar_estou_lendo(leitor_id, obra_id, posicao=None)` grava em `estou_lendo`, tira a Obra de Quero ler, desfaz a Dispensa dela e registra `leitura_iniciada`. Uma Obra da Estante levanta `JaNaEstante`. Salvar de novo não duplica e mantém a primeira posição. `estante.tirar_de_estou_lendo(...)` ("Parei de ler") apaga a linha, e `estante.listar_estou_lendo(leitor_id)` devolve a lista, da mais recente para a mais antiga.
- **Posição (O5).** Sem `posicao`, vale a de `quero_ler`, se a Obra estava lá. Assim uma Obra salva de "Para você", que passou por Quero ler e depois por Estou lendo, ainda entra na Estante com `origem='sugestao'` e registra `ja_li_de_sugestao`.
- **Exclusão mútua.** `estante.adicionar` ("Já li") tira a Obra de Estou lendo na mesma transação, como já faz com Quero ler. `estante.dispensar` e `estante.salvar_quero_ler` também a tiram (a segunda leva a posição de volta, se não receber outra).
- **"Para você".** As Obras de Estou lendo saem das candidatas do §8.5, no mesmo `WHERE` final das Dispensas e de Quero ler. `recomendacao.pontuacao` não muda, e o teste de paridade com o SQL também não.
- **Página da Obra.** `PaginaObra.estou_lendo` diz se a Obra está na lista. Nesse caso a página mostra "Você está lendo este livro." e só os botões "Já li" e "Parei de ler".

**UI.** Página "Estou lendo" no `st.navigation`, antes de Quero ler, com "Já li" e "Parei de ler" em cada item. Vazia: chamada para Quero ler. O botão "Comecei a ler" fica nos cards de "Para você", em cada item de Quero ler e na página da Obra fora da Estante.

---

## 9. Avaliação offline

Módulo `pipeline/avaliacao.py`, com semente fixa (42) e resultado reprodutível.

### 9.1 Divisão

- Considera os leitores do goodbooks-10k com ≥ 20 Notas e ao menos uma Nota ≥ 4, e amostra **5.000** deles.
- Para cada um, o **teste** são 20 % das Notas ≥ 4, sorteadas. O treino é todo o resto.
- A coleitura usada na avaliação é calculada **só** com o treino de todos os leitores, com o teste removido. O conteúdo não usa Notas, então não há vazamento.

### 9.2 Protocolo

Para cada leitor da amostra, monta uma "Estante" com as Notas de treino, roda a mesma pontuação do §8.5 (em Python, sem SQL, sobre os Vizinhos da execução avaliada), pega as top 20 fora do treino e compara com o teste. A pontuação é `W @ S` em matrizes esparsas (`recomendacao.pontuacao`: W são os pesos das Notas de cada Estante, S as similaridades misturadas por α), para os 5.000 leitores de uma vez; um teste confere que a consulta SQL do "Para você" dá o mesmo resultado.

### 9.3 Métricas

- **Recall@20** e **NDCG@20** (relevância binária: Obra do teste = 1).
- **Cobertura**: % do Catálogo que aparece em alguma lista top 20.
- **Baseline obrigatório:** popularidade (top 20 por `popularidade`, fora do treino). Todo modelo precisa vencê-lo em NDCG@20.

### 9.4 Calibração e critério de entrada

- Varredura de α ∈ {0; 0,25; 0,5; 0,75; 1}, β ∈ {0; 0,25; 0,5; 1} (cada execução isolada grava a de β em `metricas.varredura_beta`), K ∈ {20, 50, 100}, λ ∈ {10, 50, 100} e duas tabelas de peso (a do PRD e a simétrica, 5 → 1 · 4 → 0,5 · 3 → 0 · 2 → −0,5 · 1 → −1). O resultado vai para `reports/avaliacao-*.md` e a grade completa para `reports/varredura-*.csv`.
- K e λ variam só a coleitura, que a avaliação recalcula sobre o treino a cada configuração. O conteúdo usa os Vizinhos gravados da execução (K = 50); com α = 1, K e λ não se aplicam.
- A combinação (α de `config`) fica em `metricas.combinada` das duas execuções, com a melhor configuração da varredura em `combinada.melhor`.
- **Uma execução só é ativada se o NDCG@20 dela for ≥ ao da ativa do mesmo tipo**, com a mesma divisão e a mesma configuração. `recalcular` aplica isso sozinho, e `ativar --forcar` existe para uso manual.
- **Resultado (19/11/2026, ADR 0007):** escalas igualadas, α = 0,25, β = 0, K = 20, λ = 10 e a tabela de pesos do PRD. NDCG@20 combinado 0,3176, contra 0,3117 da Coleitura sozinha, 0,0650 do conteúdo sozinho e 0,0828 da popularidade. Depois, o Leitor voltou o β para 0,25 (NDCG@20 0,2965, cobertura 40 %), para proteger as Estantes com muitas Obras fora da Base.
- O UCSD Goodreads é validação extra opcional e manual, só local (licença: ADR 0003). Ele não entra no `recalcular`.

---

## 10. Inicialização ao abrir o app

O app **não** sobe com o Windows: ele só roda quando o Leitor o abre, com `scripts/abrir.cmd` (dá para criar um atalho dele na Área de Trabalho). O `abrir.cmd` chama `iniciar.ps1`, que:

0. Se o app já estiver no ar (outra janela), só abre `127.0.0.1:8501` no navegador.
1. Abre o Docker Desktop, se estiver fechado, e espera ele responder (`docker info`, até 120 s). Roda `docker compose up -d --wait db`, que espera o `healthcheck` do Postgres (`pg_isready`).
2. `uv run python -m recomendador atualizar`, com log em `logs/atualizar-AAAA-MM-DD.log`. O app abre mesmo que esse passo falhe.
3. `uv run streamlit run app/main.py --server.address 127.0.0.1 --server.headless true` na própria janela, e abre o navegador quando o app responder. Fechar a janela encerra o app.

`atualizar` faz, em ordem e com tempo máximo total de 10 min:

1. Aplica as migrações pendentes (`alembic upgrade head`).
2. Gera os embeddings e os Vizinhos de conteúdo das Obras `origem='leitor'` que estão sem eles.
3. Enriquece pela API da Open Library as Obras `origem='leitor'` sem `enriquecida_em`, a 1 req/s e no máximo 100 por execução (`pipeline/enriquecimento_leitor.py`). Obra sem ISBN é marcada sem consulta; com a Open Library fora do ar, o resto fica para a próxima abertura.
4. Grava `ultima_atualizacao` (tabela `config_app`, chave/valor).

O recálculo completo (`recalcular`) **não** roda na abertura.

Como o `atualizar` roda a cada abertura, o limite de 10 min vale como atraso máximo para o app abrir. Os passos 2 e 3 já são limitados (só Obras pendentes, no máximo 100 por vez) para que, no dia a dia, a abertura leve segundos.

---

## 11. UI Streamlit

`st.navigation` com sete páginas. A página Obra fica oculta do menu e é acessada por `?obra=<id>`.

| Página | Conteúdo | Requisitos |
|---|---|---|
| Para você | Filtros no topo. Até 20 Sugestões em cards (capa, título, autor, Motivo, "Por quê?", "Quero ler", "Comecei a ler", "Já li", "Não tenho interesse"). | R4, R7, R8, R10, R11, R13 |
| Estou lendo | As Obras em leitura, com "Já li" e "Parei de ler". Vazia: chamada para Quero ler. | R13 |
| Quero ler | As Obras salvas, com "Comecei a ler", "Já li" e "Tirar da lista". Vazia: chamada para "Para você". | R8, R13 |
| Estante | §7.5 | R3 |
| Adicionar | Busca (§7.1) → escolha → "É uma destas?" se necessário → Nota → salvar. Também tem o cadastro manual. | R1, R2 |
| Montagem da Estante | §7.4 | — |
| Obra (oculta) | §8.3, com "Quero ler", "Comecei a ler" (§8.7) e "Desfazer" a Dispensa (§8.6) | R5, R7, R8, R13 |

- O rodapé traz a atribuição do goodbooks-10k (CC BY-SA 4.0) e da Open Library.
- Funções de leitura usam `st.cache_data` com TTL curto (30 s). Qualquer escrita limpa o cache (`st.cache_data.clear()`), para que a mudança de Nota apareça na hora (R2).
- O modelo de embedding fica em `st.cache_resource`.

---

## 12. Testes

`pytest`, com um banco `recomendador_test` recriado por sessão (Alembic `upgrade head`) e cada teste numa transação revertida no fim.

| Camada | Como | Exemplos |
|---|---|---|
| Domínio + banco | Banco real, sem mocks | Deduplicação por Obra; mudar a Nota de 5 para 1 derruba as Sugestões cujo Motivo era a Obra (R2); remover uma Leitura faz a Obra voltar a ser candidata; nunca sugere Obra da Estante; Motivo sempre com Nota ≥ 4; menos de 3 Notas → estado "avalie mais"; R5b vazio → mensagem exata; a Obra dispensada não volta; "Já li" tira de Quero ler e de Estou lendo; Estou lendo leva a posição de Quero ler; o filtro não muda a pontuação nem a ordem; os 3 Contribuintes com a participação |
| Algoritmos | Funções puras com matrizes pequenas feitas à mão | Cosseno ajustado e encolhimento contra um cálculo manual 4×3; top K exclui a própria Obra e respeita o limite por autor; NDCG@20 contra um valor conhecido |
| Resolução Edição → Obra | Respostas gravadas da OL e do Google Books (JSON em `tests/dados/http/`), via transporte falso do `httpx` | Um caso por regra (1 a 4) do §7.2, incluindo *Duna* (Aleph) → *Dune* |
| Fixture de Catálogo | ~40 Obras sintéticas, com Vizinhos fixos | Com 5 Notas positivas, `para_voce` devolve ≥ 10 Sugestões (O1) |
| Pipeline | Amostra de 200 Obras / 2 mil Notas em `tests/dados/goodbooks-mini/` | `carregar-base` é idempotente; `ativar` deixa no máximo uma execução ativa por tipo |
| UI | `streamlit.testing.v1.AppTest` só nos fluxos críticos | Estante vazia mostra a chamada; Montagem chega a 5 e mostra o botão |

As chamadas reais às APIs externas e à GPU ficam em testes marcados `@pytest.mark.externo` e `@pytest.mark.gpu`, fora da execução padrão.

---

## 13. Pontos de extensão (P1) e restrições (P2)

**P1:** R7, R8, R10 e R11 foram implementados na fase 4 (§8.6), e R13 na fase 5 (§8.7).

**P2, o que o desenho não pode impedir:**

- **Multiusuário e hospedagem:** `leitor_id` em tudo que é pessoal. A UI está isolada do pacote, então trocar o Streamlit não toca o domínio (ADR 0005).
- **Notas dos Leitores na Coleitura:** o pipeline lê as Notas de uma fonte abstrata (`fontes_de_notas`), que hoje é só o Parquet.
- **Base de coleitura maior:** a carga é por adaptador (`carregar-base --fonte goodbooks10k`).
- **Importar histórico** (Goodreads, Hardcover, Skoob): reaproveita `resolver_obra` (§7.2) linha a linha.
- **LLM nos Motivos:** o Motivo é um dado estruturado (`motivo_obra_id`, parcelas), e o texto é montado só na UI.

---

## 14. Fases e critérios de aceite

Os critérios do PRD valem como estão. Esta tabela acrescenta os critérios técnicos de cada fase.

| Fase | Entrega | Pronto quando |
|---|---|---|
| **0. Fundação** | docker compose, esquema, `carregar-base`, `enriquecer-ol`, `mapear-generos`, `abrir.cmd` | Catálogo com 10 mil Obras; % de `ol_work_key`, de descrição e de título em português registrados no log; ≥ 90 % das Obras com algum Gênero; abrir `scripts/abrir.cmd` com o Docker Desktop fechado sobe o banco e o app e abre `127.0.0.1:8501` no navegador |
| **1. Estante** | R1, R2, R3, Montagem da Estante, Eventos | Critérios de R1 a R3 do PRD; busca ≤ 2 s p95; os 4 caminhos do §7.2 cobertos por teste; adicionar + dar Nota < 30 s (medido pelo evento `leitura_salva`) |
| **2. Parecidos** | Bake-off (ADR 0006), R5 + R5a, R4 com α = 1, avaliação offline | NDCG@20 só com conteúdo > baseline de popularidade; ≥ 80 % das Leituras com R5a preenchido (O4); com 5 Notas, ≥ 10 Sugestões (O1) |
| **3. Coleitura** | R5b, R4 completo, calibração de α | NDCG@20 combinado ≥ o melhor dos dois isolados; **taxa de correspondência das Leituras com Obras `origem='base'` ≥ 40 %**, senão reabrir a escolha da Base de coleitura (PRD §9); ≥ 40 % das Leituras com R5b preenchido (O4) |
| **4. Ajustes** | R7, R8, R10, R11 (§8.6), migração 0006, `tem_edicao_pt` no `enriquecer-ol` | Critérios de R7, R8, R10 e R11 do PRD cobertos por teste contra o banco real; o teste de paridade SQL × avaliação inalterado; a consulta do O2 (salvas ÷ (salvas + dispensadas) nas top 10) em `reports/consultas-metricas.sql`; `enriquecer-ol` rodado de novo no banco do app, com a contagem de `tem_edicao_pt` no log |
| **5. Estou lendo** | R13 (§8.7, ADR 0008), migração 0007, página Estou lendo | Critério do R13 do PRD coberto por teste contra o banco real: entra por "Para você", Quero ler e a página da Obra; sai de Quero ler ao entrar; "Já li" tira da lista e grava `origem='sugestao'` com a posição vinda de Quero ler; não aparece em "Para você"; o teste de paridade SQL × avaliação inalterado |

---

## 15. Riscos

| Risco | Efeito | Mitigação |
|---|---|---|
| Edições brasileiras não casam com o Catálogo | R5b vazio, Coleitura fraca | Coletar todos os ISBNs das works nos dumps da OL (§6.2); regra 3 do §7.2; "É uma destas?"; medir na fase 3 |
| Termos do Google Books sobre cache | Uso fora dos termos | Persistir dados da OL de preferência; capa por URL; cache só na sessão |
| Viés de popularidade do goodbooks-10k (só livros populares) | Sugestões óbvias | Cobertura medida no §9.3; limite por autor; Base maior no P2 |
| Docker Desktop não abre ou demora | App não abre | `iniciar.ps1` abre o Docker Desktop, espera até 120 s e mostra o erro com o caminho do log |
| Dumps da OL grandes (~12 GB) | Primeira carga lenta | Streaming; processamento único; a carga roda bem uma vez e não precisa ser rápida |
| VRAM de 12 GB | Modelo de embedding grande não cabe | Os finalistas já são filtrados por VRAM (§8.4.1); fp16; batches pequenos |
