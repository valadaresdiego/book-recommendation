# "Estou lendo" é uma lista, não controle de progresso

O PRD §1 diz que o app "não controla progresso", e o §3 deixa "progresso de leitura" fora do escopo. O Leitor pediu uma categoria "Estou lendo", além de Quero ler e Já li, com uma lista própria. Decisão do Leitor, em 19/11/2026: **"Estou lendo" entra como uma lista (R13), sem página, percentual, prazo nem data de término.** Ela guarda só que o Leitor começou a Obra e quando, igual à lista Quero ler.

## Por que não fere o PRD §3

O que o §3 exclui é acompanhar a leitura em si: página atual, percentual, ritmo, metas. Isso é o que Goodreads e Skoob já fazem, e não ajuda a recomendar. "Estou lendo" só separa duas situações que hoje se misturam em Quero ler: "quero ler um dia" e "já comecei". A separação ajuda a recomendação: a Obra em leitura sai de "Para você", e o "Já li" dela ainda conta para o O5 quando ela veio de uma Sugestão.

## Regras

- Uma Obra fica em no máximo uma das listas Quero ler, Estou lendo e Dispensa. Entrar em Estou lendo tira de Quero ler e desfaz a Dispensa; dispensar ou voltar para Quero ler tira de Estou lendo.
- Obra da Estante não entra (sem releitura na v1): levanta `JaNaEstante`, como em Quero ler.
- O "Já li" tira a Obra de Estou lendo na mesma transação que cria a Leitura.
- Ao passar de Quero ler para Estou lendo, a posição em "Para você" vai junto (O5).

## Opções consideradas

- **Uma tabela única de listas, com o tipo:** rejeitada. A exclusão mútua seria só um `UPDATE` do tipo, mas Quero ler e Dispensa já têm tabelas próprias (migração 0006), e misturar os dois modelos custa mais do que três `DELETE`s.
- **Guardar página ou percentual:** rejeitado pelo PRD §3. Se um dia entrar, é outra decisão, com outro ADR.

## Consequências

- Uma tabela nova, `estou_lendo`, igual à `quero_ler` (migração 0007). Reverter é apagar a tabela e a página.
- Um evento novo, `leitura_iniciada {posicao}`. Ele não mede nenhuma meta do PRD hoje, mas permite saber quantas Sugestões viram leitura de fato antes do "Já li".
