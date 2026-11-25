# A Edição escolhida na busca vai junto pelas listas

O Leitor pediu, em 25/11/2026, para buscar um livro que ainda não leu e guardá-lo em Quero ler (R8). A busca (SPEC §7.1) termina numa Edição: `registrar_resolucao` grava em `edicao` a que o Leitor escolheu, com capa, editora e ISBN. Até aqui, só a Leitura tinha `edicao_id`; as listas Quero ler e Estou lendo guardavam só a Obra. Um livro guardado pela busca perderia a Edição no caminho até o "Já li".

Decisão do Leitor, em 25/11/2026: **`quero_ler` e `estou_lendo` ganham `edicao_id` (migração 0010).** A Edição passa de uma lista para a outra junto com a posição em "Para você", e `estante.adicionar` a usa quando o "Já li" não traz outra.

## Regras

- `edicao_id` é nulo quando a Obra veio de "Para você" ou da página da Obra; só a busca preenche.
- "Comecei a ler" leva a Edição de Quero ler para Estou lendo; voltar para Quero ler a traz de volta.
- `adicionar` sem `edicao_id` usa a de Estou lendo ou a de Quero ler. Uma Edição passada explicitamente vale mais.
- A capa da lista é a da Edição, quando há; senão, a da Obra.
- `ON DELETE SET NULL`, como `leitura.edicao_id`: apagar uma Edição não apaga o item da lista.

## Opções consideradas

- **Aceitar a Leitura sem Edição:** sem migração, mas o Leitor perderia a edição que tem na estante física e a capa em português que escolheu, que é o motivo de a busca gravar a Edição.
- **Achar a Edição no "Já li" pela Obra:** a Obra pode ter várias Edições gravadas (a fusão das works junta as de outras Obras, SPEC §8.8), e nada diz qual é a do Leitor.

## Consequências

- Uma coluna em cada lista (migração 0010). Reverter é apagar as duas colunas: as Leituras já criadas continuam com a Edição.
- A Obra do Leitor criada só para Quero ler tem Edição e lista, então conta como "em uso" no `carregar-tecnicas` (SPEC §8.8), como as outras Obras do Leitor.
