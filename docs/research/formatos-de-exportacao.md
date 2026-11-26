# Formatos de exportação de histórico: Goodreads, Hardcover e Skoob

Pesquisa feita em 2026-11-26 para o R9 (PRD §5, P2). "Não confirmado" = não achei em fonte primária. As páginas do Hardcover (hardcover.app, docs.hardcover.app) devolveram 403 ao fetcher, e a ajuda do Goodreads (help.goodreads.com) não carregou sem JavaScript.

## Resumo

| Serviço | Exportação oficial | ISBN | Nota | Estados | Entra no R9? |
|---|---|---|---|---|---|
| Goodreads | CSV "Export Library" | `ISBN` e `ISBN13` como fórmula (`="0439023483"`), vazios em parte das linhas | inteira de 0 a 5, 0 = sem nota | `Exclusive Shelf`: `read`, `to-read`, `currently-reading` e prateleiras exclusivas do usuário | Sim (decisão do Leitor, 26/11/2026) |
| Hardcover | Existe desde 08/2025, formato não confirmado (CSV ou JSON) | não confirmado | meias estrelas (0,5 a 5), não confirmado no arquivo | Want to Read, Currently Reading, Read, Paused, Did Not Finish | Não, sem amostra do arquivo |
| Skoob | Não há | as ferramentas de terceiros não trazem | 1 a 5 estrelas, meia estrela não confirmada | Lido, Lendo, Quero ler, Relendo, Abandonei | Não, só por raspagem da API |

## Goodreads

- Exemplo real lido: fixture do Bookwyrm, [`bookwyrm/tests/data/goodreads.csv`](https://raw.githubusercontent.com/bookwyrm-social/bookwyrm/main/bookwyrm/tests/data/goodreads.csv). UTF-8 sem BOM, vírgula, aspas RFC 4180.
- Colunas (por nome; a ordem e o número mudaram com o tempo). As 24 atuais: `Book Id, Title, Author, Author l-f, Additional Authors, ISBN, ISBN13, My Rating, Average Rating, Publisher, Binding, Number of Pages, Year Published, Original Publication Year, Date Read, Date Added, Bookshelves, Bookshelves with positions, Exclusive Shelf, My Review, Spoiler, Private Notes, Read Count, Owned Copies`. Exports de antes de 2023 trazem mais 7 (`Recommended For`, `Recommended By`, `Original Purchase Date`...). Fonte: [thread "What's in an export file"](https://www.goodreads.com/topic/show/22566592-what-s-in-an-export-file?page=1).
- `Title` traz a série entre parênteses: "Gideon the Ninth (The Locked Tomb #1)". É o mesmo formato do `title` do goodbooks-10k.
- ISBN vazio vem como `=""`. A frequência não foi medida em fonte nenhuma; edições Kindle costumam vir sem ISBN (não confirmado).
- `Date Read` e `Date Added` em `AAAA/MM/DD`. `Date Read` vem vazio com frequência, mesmo em `read` (um usuário relatou 800 de ~3.580: [thread](https://www.goodreads.com/topic/show/22563338-export-file-is-missing-data----how-to-fill-the-holes)).
- Releitura é uma linha só, com `Read Count` > 1 e só a data mais recente.
- `Book Id` parece ser o id da Edição (inferência, não confirmado). O goodbooks-10k tem `goodreads_book_id` e `best_book_id`, também de Edição, e `work_id`, que o export não traz.
- O importador do Bookwyrm mapeia as colunas pelo nome em minúsculas e `read`, `to-read` e `currently-reading` para os estados dele: [`importer.py`](https://raw.githubusercontent.com/bookwyrm-social/bookwyrm/main/bookwyrm/importers/importer.py).

## Hardcover

- A exportação foi anunciada em 27/08/2025 no [roadmap](https://roadmap.hardcover.app/feature-requests/posts/csv-export), em `hardcover.app/account/exports`. Os comentários sugerem JSON; um README de terceiro fala em CSV. Nenhuma fonte lista as colunas.
- A API GraphQL (`https://api.hardcover.app/v1/graphql`, token pessoal no `Authorization: Bearer`) tem `user_books` com `status_id` (1 Want to read, 2 Currently reading, 3 Read, 5 Did not finish; 4 Paused só em terceiros), `rating` (float), `edition` (com ISBN, pode ser nula) e `book`. Fontes: [dev.to](https://dev.to/emma/fun-with-hardcovers-book-api-a-quick-reference-17h), [hardcover-cli](https://pkg.go.dev/github.com/KIRKR101/hardcover-cli@v0.2.0/internal/api). Limites (60 req/min) só em terceiros.
- Uma ferramenta de terceiros que exporta no layout do Goodreads arredonda a meia estrela para cima ([PR](https://github.com/AliSayyah/hardcover-desktop/pull/37), fechado sem merge).

## Skoob

- Sem exportação oficial encontrada. As ferramentas raspam a API do site: [skoobpy](https://github.com/Diegoslourenco/skoobpy) (API antiga `/v1/bookcase/books/{user_id}`, CSV `Title;Author;Published Year;Pages;Publisher;Skoob's Page`, sem ISBN nem nota) e [tropxeskoob](https://github.com/pedrobrantes/tropxeskoob) (API nova `prd-api.skoob.com.br/api/v1/bookshelf`, com token; colunas = chaves do JSON, sem amostra).
- Para identificar a Obra sobram título, subtítulo, autor, ano e editora.
