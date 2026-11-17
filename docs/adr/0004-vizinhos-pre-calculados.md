# Similaridades calculadas em lote; o banco guarda Vizinhos

A Coleitura e a Similaridade de conteúdo são calculadas fora do fluxo de interação, em Python e na GPU. O resultado são os **Vizinhos** de cada Obra do Catálogo (as top-K por cada critério, com a similaridade), gravados no Postgres. "Para você", "Parecidos com este" e "Quem leu também gostou" são leituras e somas sobre essas tabelas. Assim, mudar uma Nota se reflete na hora (R2), a resposta fica abaixo de 2 s e o Motivo sai direto da maior parcela de Vizinho × peso(Nota).

## Consequências

- Uma Obra recém-adicionada fora do Catálogo só tem Vizinhos de conteúdo depois que o cálculo roda para ela.
- Trocar o modelo (por exemplo, de item-item para fatoração) muda só o job de cálculo, não o app, desde que o resultado continue sendo uma similaridade entre pares de Obras.
- O Postgres roda em Docker com pgvector e guarda também os embeddings de conteúdo de cada Obra. Para uma Obra nova, os Vizinhos de conteúdo saem de uma busca KNN no pgvector logo ao adicioná-la, e a GPU só gera o embedding.
