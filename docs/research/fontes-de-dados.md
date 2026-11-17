# Fontes de dados para o recomendador de livros pessoal

Pesquisa feita em 2026-11-17. Cada afirmação traz o link da fonte. "Não confirmado" = não achei em fonte primária. Várias páginas do Hardcover devolveram HTTP 403 ao fetcher; as figuras do Hardcover vêm só de páginas de terceiros e precisam ser conferidas na conta.

## Tabela-resumo

| Fonte | Acesso | Limites | Licença / termos | Identifica obra ou edição? | Serve para |
|---|---|---|---|---|---|
| Google Books API v1 | API key (ou OAuth) | Padrão reportado: 1.000 req/dia (não oficial); cota por minuto/usuário existe, valor não confirmado | Termos Books API + Google APIs ToS: sem cópia permanente, cache só conforme cache header | Edição (volume id); sem id de obra documentado | Metadados/capa/ISBN de edições BR sob demanda |
| Open Library | Sem chave; User-Agent com contato | 1 req/s anônimo, 3 req/s identificado; covers por ISBN: 100 req/IP/5 min | Licença dos dumps não declarada na página | Obra (works) e edição (editions), com `translation_of`/`translated_from` | Mapear edição -> obra, tradução -> original; dumps mensais |
| Hardcover API | GraphQL, token da conta | 60 req/min, timeout 30 s, profundidade 3 (só terceiros) | Termos não lidos (403) | A confirmar | Notas e listas do próprio usuário; metadados |
| Book-Crossing | Download de ZIP | n/a | Livre para pesquisa citando Ziegler et al. 2005; sem licença formal | Edição (ISBN) | Protótipo de filtragem colaborativa (dados de 2004) |
| goodbooks-10k | Download (GitHub releases) | n/a | CC BY-SA 4.0 (arquivo LICENSE); origem Goodreads | Obra (ids de ratings = work) | Matriz usuário x livro x nota, 10k livros mais populares |
| UCSD Goodreads Book Graph | Download (mcauleylab.ucsd.edu) | n/a | Só uso acadêmico; sem redistribuir; sem uso comercial | Livro, com obras nos metadados | Matriz grande de notas; licença restritiva |
| Dados BR (BN/CBL) | Sem base pública de ISBN confirmada | n/a | n/a | Edição | Não achei base aberta utilizável |

## 1. Google Books API v1

- Chave: dados públicos exigem API key ou token OAuth; dados privados exigem OAuth. [Using the API](https://developers.google.com/books/docs/v1/using)
- Cota: a documentação oficial não traz números. O padrão de 1.000 req/dia é citado por usuários, não por página oficial; existe limite "por minuto por usuário" (valor oficial não confirmado; ver Quotas no Cloud Console). Fontes: [fórum Google](https://discuss.google.dev/t/requesting-higher-quota-for-google-books-api-bookquest-app/286093), [Capping API usage](https://docs.cloud.google.com/apis/docs/capping-api-usage).
- Paginação: `maxResults` padrão 10, máximo 40. [Using the API](https://developers.google.com/books/docs/v1/using)
- Armazenamento: os termos da Books API não falam de cache; incorporam os Google APIs ToS e exigem remover conteúdo que infrinja direitos e não cobrar usuários sem acordo. [Books API terms](https://developers.google.com/books/terms) Os Google APIs ToS proíbem cópias permanentes e cache além do cache header (seção 5(e)) e exigem apagar conteúdo em cache ao encerrar (8(b)). [Google APIs Terms](https://developers.google.com/terms) Implicação: não montar base permanente de metadados/capas do Google; cache curto.
- Campos de `volumeInfo`: title, subtitle, authors, publisher, publishedDate, description (HTML), industryIdentifiers (ISBN_10/ISBN_13/OTHER), pageCount, dimensions, printType, mainCategory, categories, averageRating, ratingsCount, contentVersion, imageLinks (smallThumbnail a extraLarge), language (ISO 639-1), previewLink, infoLink, canonicalVolumeLink. [Volumes reference](https://developers.google.com/books/docs/v1/reference/volumes)
- Obra: só há Volume ID (por edição); não há id de obra/grupo documentado. [Using the API](https://developers.google.com/books/docs/v1/using)
- Regionalização: `langRestrict` (ISO 639-1, ex. `pt`) na busca. `country` não aparece como parâmetro documentado nessa página; resultados dependem do IP. [Using the API](https://developers.google.com/books/docs/v1/using) Cobertura de edições brasileiras: não confirmado.

## 2. Open Library

- Limites: 1 req/s sem identificação, 3 req/s com User-Agent (nome do app + contato). [Developer API](https://openlibrary.org/developers/api)
- Não é pensada como "backend de dados para serviços de terceiros" nem infra comercial de alto tráfego; não usar a API para bulk, usar dumps mensais; lotes via `search.json`; outros casos: openlibrary@archive.org. [Developer API](https://openlibrary.org/developers/api)
- Dumps: mensais (TSV: type, key, revision, last_modified, JSON). Tamanhos comprimidos: completo ~29,6 GB; todos os tipos ~12,4 GB; editions ~9,2 GB; works ~2,9 GB; authors ~0,5 GB; ratings ~5 MB; reading log ~65 MB; wikidata ~700 MB. Licença: não declarada na página (remete aos ToS do Internet Archive): não confirmado. [Dumps](https://openlibrary.org/developers/dumps)
- Modelo works/editions; `edition.works` liga a edição à obra. Campos de tradução no tipo edition: `translation_of` (string), `translated_from` (idiomas, múltiplo), `work_titles`, `languages`. Não existe `original_languages`. [edition.type](https://raw.githubusercontent.com/internetarchive/openlibrary/master/openlibrary/plugins/openlibrary/types/edition.type) Taxa de preenchimento desses campos: não confirmado.
- Covers API: acesso por ID que não seja CoverID/OLID (ex. ISBN) limitado a 100 req/IP/5 min (403 ao exceder); não fazer crawl; uso previsto é exibir capas em páginas públicas com link de crédito; bulk via archive.org. Não há dumps mensais de capas (só coleções históricas covers_0000 a covers_0014, com 0006 e 0007 indisponíveis); há dump de metadados de capas (~70 MB). [Covers API](https://openlibrary.org/dev/docs/api/covers), [Dumps](https://openlibrary.org/developers/dumps)

## 3. Hardcover API

Não consegui ler docs.hardcover.app, hardcover.app/account/api nem os termos (HTTP 403). Tudo abaixo vem de terceiros e é "não confirmado" em fonte primária.

- Tipo: GraphQL, endpoint `https://api.hardcover.app/v1/graphql`, token Bearer obtido nas configurações da conta (hardcover.app/account/api); mesma API usada pelo site e apps. [skills.lc](https://skills.lc/openclaw/skills/openclaw-skills-skills-asaphko-hardcover-skill-md), [glama.ai](https://glama.ai/mcp/servers/jn6wxtio67)
- Limites reportados: 60 req/min, timeout 30 s, profundidade máxima de query 3; sem operadores `_like/_ilike/_regex`; 401 = token inválido/expirado, 429 = rate limit. [openclawdirectory](https://openclawdirectory.pages.dev/web-frontend-development/hardcover)
- Validade do token: terceiros dizem 1 ano; outro guia diz só que é longa e revogável/regenerável. [BookLore docs](https://booklore-app.github.io/booklore-docs/docs/metadata/hardcover-token) Beta: não confirmado.
- Termos (server-side, comercial, armazenamento): não confirmado. Há menção de que imagens enviadas por usuários exigem política DMCA se exibidas publicamente. [glama.ai](https://glama.ai/mcp/servers/jn6wxtio67)
- Dados expostos (nota média, notas individuais, listas, editions, ids): não confirmado em fonte primária. Pelo desenho (token por usuário) o esperado é acesso aos dados do próprio usuário. Matriz usuário x livro x nota em volume: não confirmado, e os limites reportados (60/min, profundidade 3) tornam improvável. Importar as próprias notas do usuário parece viável, mas verificar.

## 4. Book-Crossing (Ziegler et al., 2004)

- Tamanho: 278.858 usuários (anonimizados, com dados demográficos), 1.149.780 notas (explícitas e implícitas), 271.379 livros; crawl de 4 semanas em ago/set 2004, com permissão de Ron Hornbaker (Humankind Systems). [Página do Freiburg](https://dbis.informatik.uni-freiburg.de/forschung/projekte/2nd-Gen-RS)
- Escala: explícitas 1-10, implícitas = 0. [recommenderlabBX](https://rdrr.io/cran/recommenderlabBX), [Netzschleuder](https://networks.skewed.de/net/bookcrossing) (terceiros). Subconjunto com notas explícitas: 493.813. [manual](https://mhahsler.r-universe.dev/recommenderlabBX/doc/manual.html)
- Identificação: ISBN, ou seja, edição.
- Licença: a página do Freiburg não traz termos. Uso livre para pesquisa citando Ziegler et al., WWW 2005 (via terceiros). Espelhos divergem: ODbL no [TU Berlin](https://mldata-static.ml.tu-berlin.de/repository/data/viewslug/book-crossing-ratings-10/1.html), CC BY 4.0 no [hyper.ai](https://hyper.ai/en/datasets/5524). Tratar como "pesquisa com citação".
- Download: o host original (www2.informatik.uni-freiburg.de/~cziegler/BX/) recusou conexão na minha tentativa. Snapshot Wayback de 2014: [web.archive.org](https://web.archive.org/web/20140228065458/http://www.informatik.uni-freiburg.de/~cziegler/BX/). Espelhos: hyper.ai (zip ~50 MB), TU Berlin.
- Qualidade: o conversor do TU Berlin disse não conseguir reconciliar as contagens oficiais com os dados. [TU Berlin](https://mldata-static.ml.tu-berlin.de/repository/data/viewslug/book-crossing-ratings-10/1.html) Demais problemas (esparsidade, dados de 2004, ISBNs inválidos): conhecimento geral, não confirmado aqui.

## 5. goodbooks-10k

- Tamanho: ~6 milhões de notas para os 10.000 livros mais avaliados; user_id 1-53.424; `to_read.csv` ~1 milhão de pares. [README](https://github.com/zygmuntz/goodbooks-10k)
- Escala: inteiros de 1 a 5. [README](https://github.com/zygmuntz/goodbooks-10k)
- Licença: CC BY-SA 4.0 declarada em [LICENSE](https://raw.githubusercontent.com/zygmuntz/goodbooks-10k/master/LICENSE). Os dados vêm do Goodreads; direitos de origem: não confirmado.
- Campos: ratings.csv (user_id, book_id, rating), books.csv (ids Goodreads, autores, título, média), book_tags, tags, to_read, XMLs brutos. Os book_id de ratings correspondem a work IDs do Goodreads (edições combinadas); book_id/best_book_id do Goodreads apontam para a edição mais popular. [README raw](https://raw.githubusercontent.com/zygmuntz/goodbooks-10k/master/README.md) Presença de isbn, isbn13, original_title, language_code em books.csv: não verificada nas páginas lidas; conferir no arquivo.
- Download: Releases do repositório e pasta `samples/`. [GitHub](https://github.com/zygmuntz/goodbooks-10k)

## 6. UCSD Goodreads Book Graph

- Tamanho (completo): 2.360.655 livros (1.521.962 obras, 400.390 séries, 829.529 autores), 876.145 usuários, 228.648.342 interações (112.131.203 leituras, 104.551.549 notas); ~15 mi de reviews multilíngues; subconjunto de spoilers ~1,3 mi. [Página](https://cseweb.ucsd.edu/~jmcauley/datasets/goodreads.html)
- Termos: "somente uso acadêmico", não redistribuir, sem uso comercial; só estantes públicas; ids anonimizados. [Página](https://cseweb.ucsd.edu/~jmcauley/datasets/goodreads.html), [GitHub](https://github.com/MengtingWan/goodreads) (código Apache-2.0; os dados não).
- Subconjuntos por gênero: children (124 mil livros), comics & graphic (89 mil), fantasy & paranormal (259 mil; 55,4 mi interações), history & biography (303 mil), mystery/thriller/crime (219 mil), poetry (37 mil), romance (335 mil), young adult (93 mil). Livros podem estar em mais de um. [Página](https://cseweb.ucsd.edu/~jmcauley/datasets/goodreads.html)
- Campos: a página lida não lista nomes de campo; menciona arquivo de metadados de obras. work_id, language_code, shelves: não confirmado aqui.
- Download: mcauleylab.ucsd.edu (metadados ~2 GB, interações CSV ~4,1 GB, JSON detalhado ~11 GB); o GitHub diz que os datasets foram movidos. Verificar se o link responde hoje. [Página](https://cseweb.ucsd.edu/~jmcauley/datasets/goodreads.html), [GitHub](https://github.com/MengtingWan/goodreads)

## 7. Bônus: bases brasileiras

- A Agência Brasileira do ISBN passou da Biblioteca Nacional à CBL (único emissor desde março de 2020); a CBL diz ter preservado os dados recebidos da BN. [PublishNews](https://www.publishnews.com.br/materias/2019/12/20/isbn-passa-a-ser-de-responsabilidade-da-cbl-boa-noticia-para-o-mercado-editorial), [ISBN Internacional](https://www.isbn-international.org/node/333)
- Dados abertos da BN (plano 2025-2027): conjunto sobre obras publicadas pela própria Fundação (inclui ISBN/ISSN), não o registro nacional de ISBN; contato dadosabertos@bn.gov.br. [Plano](https://www.gov.br/bn/pt-br/acesso-a-informacao-2/dados-abertos/Plano_de_Dados_Abertos_FBN_Jun_2025___Jun2027.pdf)
- Base pública com ISBN BR -> obra original: não encontrada. Alternativa prática: dumps da Open Library (campos de tradução) + ISBN via Google Books, com heurísticas (título original, autor).
