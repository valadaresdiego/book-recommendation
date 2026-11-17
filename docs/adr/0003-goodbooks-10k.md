# A Base de coleitura é o goodbooks-10k

A Base de coleitura em produção é o **goodbooks-10k**: ~6 M de Notas de 1 a 5 sobre 10 mil Obras, já agrupadas por obra do Goodreads, sob licença CC BY-SA 4.0. Ele traz ainda `book_tags`, as estantes do Goodreads, que servem de sinal de conteúdo. Detalhes e fontes estão em `docs/research/fontes-de-dados.md`.

## Opções consideradas

- **Book-Crossing (2004):** rejeitado. Identifica por ISBN de edição, o que exigiria mapear 271 mil ISBNs para Obras; não tem quase nada lançado depois de 2004; e a escala de 0 a 10 mistura notas implícitas (0).
- **UCSD Goodreads Book Graph:** maior (2,36 M livros), mas a licença só permite uso acadêmico, sem redistribuição. Pode ser usado **só offline**, para calibrar α e os pesos, e nunca é carregado no app.
- **Hardcover:** a documentação e os termos não estavam acessíveis para confirmação, e o que terceiros relatam não permite obter Notas em volume. Fica como possível origem para importar as Notas do próprio Leitor (P2).
