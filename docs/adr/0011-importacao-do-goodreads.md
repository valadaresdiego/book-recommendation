# A importação de histórico começa pelo Goodreads, sem guardar estado

O R9 (PRD §5, P2) pede importar o histórico de Leituras de um CSV do Goodreads, das notas do Hardcover ou de uma planilha do Skoob. Ele pede ≥ 90 % das linhas com correspondência importadas, e as que falharem mostradas para o Leitor resolver à mão. A pesquisa de 26/11/2026 ([research/formatos-de-exportacao.md](../research/formatos-de-exportacao.md)) achou um formato conhecido só no Goodreads. O arquivo do Hardcover não tem amostra nem colunas documentadas, e o Skoob não exporta.

Decisões do Leitor, em 26/11/2026:

- **Só o CSV do Goodreads.** Hardcover e Skoob ficam para quando houver um arquivo real.
- **A Leitura importada tem `origem='importacao'`** (valor novo do enum, migração 0011). Ela registra `leitura_salva` sem `duracao_s`, então fica fora do O3, e não é `sugestao`, então fica fora do O5. O indicador "1ª semana" de `reports/consultas-metricas.sql` também a exclui.
- **`to-read` vai para Quero ler e `currently-reading` para Estou lendo**, sem posição, como um livro buscado. As outras prateleiras exclusivas são ignoradas e listadas.
- **Vale a Estante.** Uma Obra que já está lá não muda, e o relatório mostra a Nota do arquivo quando é diferente.
- **A data de leitura não é guardada.** As linhas entram da leitura mais antiga para a mais nova, e a Estante, que desempata a data de inclusão pelo id, mostra a mais recente primeiro.
- **A revisão das linhas sem correspondência vale só na sessão**, com a pergunta "É uma destas?" do §7.2. Reimportar o mesmo arquivo pula o que já entrou e mostra de novo só o que falta.
- **A resolução segue a ordem do §7.2**, com a Open Library na regra 2, e a tela mostra o progresso.
- Meia nota, que o Goodreads não tem, será arredondada para baixo quando entrar um formato que a tenha (3,5 vira 3).

## Opções consideradas

- **Planilha genérica ou API do Hardcover junto:** recusadas por agora. A planilha cobriria o Skoob à mão, mas o Leitor não tem histórico em nenhum serviço (PRD Q6). A escala e os limites da API do Hardcover não foram confirmados.
- **Tabela com as linhas pendentes:** recusada. A revisão poderia continuar em outra abertura do app, mas isso custa uma migração e um estado a mais. Reimportar o mesmo arquivo dá o mesmo resultado, porque a importação é idempotente.
- **Coluna `leitura.lida_em`, ou a data do arquivo em `criado_em`:** recusadas. A coluna é dado novo, que só a importação preencheria. Usar a data como `criado_em` mudaria o sentido de "data de inclusão" e deslocaria o início de uso nas métricas.
- **Criar sozinho a Obra das linhas sem correspondência:** recusada. Daria 100 % de importação, mas duplicaria Obras que o Catálogo tem com outro título, e a fusão depois é cara (§6.1, §8.8).

## Consequências

- Um valor novo em `origem_leitura`. O Postgres não remove valores de um enum, então reverter só apaga as Leituras importadas, ou muda a origem delas.
- Um evento novo, `historico_importado`, com as contagens de cada importação.
- `estante` passa a usar `catalogo` (`resolver_obra` e `registrar_resolucao`) na importação. Antes, só o `app/` juntava os dois.
- Os ISBNs do arquivo entram em `obra_isbn` com `origem='leitor'` nas linhas importadas, como os de uma Edição escolhida na busca. Uma reimportação resolve pela regra 1, sem a Open Library.
