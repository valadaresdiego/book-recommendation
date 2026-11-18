# Recomendador de Livros

Registro pessoal do que o leitor já leu, com nota, e recomendação do que ler a seguir, sempre com o motivo de cada sugestão.

## Livros

**Obra**:
O texto em si, independente de idioma, tradução ou editora (*Dune*, 1965). É a unidade sobre a qual tudo é registrado e recomendado.
_Evite_: livro (quando ambíguo), título, work

**Edição**:
Uma publicação concreta de uma Obra, com ISBN, idioma, editora, capa e título próprios (*Duna*, Aleph, 2017). Serve só para identificar e exibir uma Obra.
_Evite_: volume, versão, livro

**Título original**:
O título da Obra no idioma em que foi publicada pela primeira vez. Liga uma Edição traduzida à sua Obra.

**Resolução**:
A identificação da Obra a que pertence uma Edição escolhida na busca: pelo ISBN, pela work da Open Library, pelo título original com o autor ou, se nada casar, uma Obra nova.
_Evite_: correspondência, match, vinculação

**Candidata**:
Uma Obra do Catálogo parecida com a Edição escolhida, oferecida ao Leitor na pergunta "É uma destas?" quando a Resolução não acha a Obra sozinha.
_Evite_: sugestão (é outro conceito), opção

**Gênero**:
Uma categoria de uma lista fixa e curada (cerca de 15), à qual cada Obra pode pertencer. Não confundir com as tags livres herdadas da Base de coleitura.
_Evite_: categoria, tag, assunto

**Catálogo**:
O conjunto fechado de Obras que o app conhece e pode sugerir: as Obras da Base de coleitura e as Obras das Estantes.
_Evite_: acervo, base de livros

## Leitor

**Leitor**:
A pessoa que usa o app. Na v1 existe um só.
_Evite_: usuário (fora do código), cliente, conta

**Leitura**:
O registro de que o Leitor leu uma Obra, com Nota e data de inclusão. Guarda a Edição que o Leitor escolheu, mas só para exibição.
_Evite_: livro lido, registro, item da estante

**Nota**:
A avaliação inteira de 1 a 5 que o Leitor dá a uma Leitura. Uma Leitura sem Nota não entra nas Sugestões.
_Evite_: avaliação, rating, estrelas

**Estante**:
O conjunto das Leituras de um Leitor.
_Evite_: biblioteca, coleção, lidos

**Montagem da Estante**:
O primeiro passo do Leitor com a Estante vazia: ele escolhe gêneros de interesse e dá Nota às Obras populares do Catálogo que já leu, até ter Notas suficientes para receber Sugestões.
_Evite_: onboarding, cadastro inicial, importação

## Recomendação

**Base de coleitura**:
Uma base pública de Notas de muitos leitores anônimos, usada para descobrir o que quem gostou de uma Obra também gostou.
_Evite_: dataset, base pública (sem qualificar)

**Coleitura**:
A semelhança entre duas Obras medida pelas Notas que os mesmos leitores da Base de coleitura deram a ambas.
_Evite_: filtragem colaborativa (fora do código), "quem leu também gostou" (é o nome da seção, não do conceito)

**Similaridade de conteúdo**:
A semelhança entre duas Obras medida pelos seus metadados: assuntos, autor e descrição.
_Evite_: parecidos (é o nome da seção, não do conceito)

**Vizinho**:
Uma Obra entre as mais semelhantes a outra Obra por um critério (Coleitura ou Similaridade de conteúdo), com o grau dessa semelhança.
_Evite_: similar, relacionado

**Sugestão**:
Uma Obra do Catálogo, fora da Estante, recomendada ao Leitor com uma pontuação e um Motivo.
_Evite_: recomendação (para o item), candidato (depois de pontuado)

**Motivo**:
A Leitura de Nota alta que mais contribuiu para uma Sugestão, mostrada em linguagem simples.
_Evite_: explicação, justificativa
