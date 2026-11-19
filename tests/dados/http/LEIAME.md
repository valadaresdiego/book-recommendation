# Respostas HTTP gravadas

Respostas reais da Open Library e do Google Books, gravadas em 18/11/2026, servidas aos testes por
um transporte falso do `httpx` (`tests/http_gravado.py`, SPEC §12). Só o corpo JSON foi salvo;
a chave da API do Google não aparece em nenhum arquivo.

- `ol/<caminho>`: o caminho pedido à Open Library. A API responde `/isbn/{isbn}.json` com um 302
  para `/books/OL…M.json`; aqui a Edição fica direto sob `ol/isbn/`.
  - `isbn/9788576573135.json`: *Duna* (Aleph, 2017), `translation_of: Dune`, work `OL893414W`.
  - `works/OL893415W.json`: um redirecionamento (`/type/redirect`) para `OL893414W`.
  - `works/OL893414W.json`: a work canônica de *Dune*.
  - `isbn/9786580309313.json` e `works/OL24141556W.json`: *Torto Arado* (Todavia).
- `gb/<q>.json`: a busca do Google Books com `q` = nome do arquivo (`_` no lugar de espaço e `:`).
  - `duna_herbert.json`: não traz a *Duna* da Aleph entre os 20 primeiros, mas traz *Messias de Duna*.
  - `isbn_9788576573135.json`: a *Duna* da Aleph.
  - `torto_arado.json`: a edição portuguesa (LeYa), que a Open Library não conhece (404).
  - `django_inpublisher_packt.json` (gravado em 19/11/2026): a busca `editora:packt django`; traz
    *Django 4 by Example* (ISBN 9781801813051).

Para gravar de novo, use o mesmo `q` e salve só o corpo da resposta.
