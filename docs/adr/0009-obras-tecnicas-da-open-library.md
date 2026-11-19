# Obras técnicas entram no Catálogo pelos dumps da Open Library, sem Coleitura

"Para você" nunca sugeria livros técnicos. Das 10 mil Obras do goodbooks-10k, só *The Pragmatic Programmer* é de programação. Nenhuma Base de coleitura aberta cobre esse tipo de livro com licença que sirva (ADR 0003). Decisão do Leitor, em 19/11/2026: **o Catálogo continua fechado (ADR 0002), mas ganha uma segunda fonte, carregada offline: as Obras técnicas dos dumps da Open Library.** Elas são sugeridas só por Similaridade de conteúdo, numa aba própria de "Para você", a aba "Tecnologia".

## O que é "técnico"

Desenvolvimento de software, dados e ML, arquitetura, engenharia de software, UX e design de produto, DevOps e gestão de times de tecnologia. Ficam de fora as biografias e a história da tecnologia, que a Base já cobre. Essas Obras formam o Gênero "Tecnologia".

## Quais Obras da Open Library entram

O dump de works tem ~94 mil Obras com assuntos técnicos. Só 14 % delas têm descrição e 15 % têm ano, e muitas são anais de congresso, monografias acadêmicas ou ficção com o assunto "Artificial intelligence". Entram:
- as Obras com ≥ 10 Edições no dump, de qualquer editora;
- as Obras com alguma Edição de editora técnica (O'Reilly, Packt, Manning, Addison-Wesley, Alta Books, Novatec...) e alguma Edição desde 2012, se tiverem ≥ 2 Edições ou uma Edição desde 2018;
- as Obras de uma lista curada de clássicos, revisada pelo Leitor.

Saem a ficção, os anais e as séries. São umas 4.300 Obras.

Contar só Edições (≥ 5) foi rejeitado: tirava os lançamentos (*AI Engineering*, de 2025, tem 2 Edições na Open Library) e deixava o grosso nas monografias da Springer. A lista curada cobre os clássicos que os critérios perdem: Obras duplicadas na Open Library (*Refactoring*) ou com assuntos fora do critério (*SICP*).

## Como são sugeridas

- **Só conteúdo.** As Obras novas não têm Coleitura nem Notas na Base. Na aba "Tecnologia", a pontuação é a do §8.5 da SPEC com α = 1 e β = 0, sobre os Vizinhos de uma execução própria, de tipo `tecnico`. Ela liga cada Obra do Catálogo às Obras técnicas mais parecidas. Qualquer Leitura com Nota pode ser o Motivo.
- **A lista geral não muda.** As Obras da Open Library não entram como Vizinho na execução de conteúdo de sempre. Assim, a lista geral e a calibração da Fase 3 (ADR 0007) ficam como estavam. As Obras técnicas da Base aparecem nas duas abas.
- **Sem popularidade.** A `popularidade` continua sendo o nº de Notas na Base de coleitura, e as Obras novas ficam com 0. O nº de Edições na Open Library serve para escolher as Obras e para ordenar a Montagem da Estante, nunca para pontuar Sugestões.

## Opções consideradas

- **UCSD Goodreads Book Graph** (tem livros técnicos com Notas): rejeitado. A licença só permite uso acadêmico (ADR 0003).
- **Dumps de ratings e de reading log da Open Library:** não identificam o leitor, então não dão Coleitura. Serviriam só como popularidade, que a aba não usa.
- **Busca ao vivo no Google Books por assunto:** rejeitada pelos mesmos motivos do ADR 0002. Buscar no Google Books as descrições que faltam também foi rejeitado: os termos não permitem guardar cópia permanente.
- **Misturar as Obras técnicas no ranking geral:** rejeitado. Sem Coleitura e com popularidade 0, elas ficariam sempre no fim da lista, e mudariam os Vizinhos de conteúdo das Obras da Base.
- **KNN na hora, pelo índice HNSW, em vez de Vizinhos gravados:** rejeitado pelo ADR 0004.

## Consequências

- Não há métrica offline para a aba "Tecnologia" (a avaliação do §9 depende da Coleitura). A qualidade é julgada pelo Leitor no uso e pelo evento `sugestao_exibida`, que passa a dizer de qual lista veio.
- ~88 % das Obras novas não têm descrição, e o embedding delas sai de título, autor e assuntos.
- Quase nenhuma Obra técnica da Open Library tem Edição em português conhecida (96 de ~94 mil). Com a chave "Só com edição em português", a aba fica curta.
- A consequência do ADR 0002 ("o app não descobre livros nichados") continua valendo fora da Tecnologia. Para ampliar outro assunto, o caminho é o mesmo: critério de assuntos e de editoras sobre os dumps, mais uma lista curada.
- Reverter é apagar as Obras de `origem='open_library'` sem Leituras, o Gênero "Tecnologia", a execução `tecnico` e a aba.
