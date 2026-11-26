# PRD: Recomendador de Livros (v1, uso pessoal)

> **Status:** rascunho · **Data:** 17/11/2026 · **Usuário da v1:** só o autor · **Execução da v1:** local, no PC do autor ([ADR 0005](adr/0005-local-first.md))
>
> **Como construir:** [SPEC](SPEC.md) · **Termos:** [GLOSSARY](../GLOSSARY.md) · **Decisões:** [ADRs](adr/)

## 1. Problema

Escolher a próxima leitura dá trabalho: as listas de "mais vendidos" e os algoritmos das lojas não conhecem o meu histórico, e os que conhecem (Goodreads, Skoob) misturam rede social, controle de leitura e anúncios. Quero um lugar simples onde eu registro o que já li, dou nota, e recebo sugestões que fazem sentido **para o meu gosto**, com o motivo de cada sugestão. Sem isso, continuo escolhendo livro por acaso e acertando menos.

**Isto não é um app de leitura.** Não abre livro, não marca página, não controla progresso. Só registra o que eu li e recomenda o que ler. A lista "Estou lendo" (R13) só diz que comecei uma Obra: não guarda página, percentual nem prazo ([ADR 0008](adr/0008-estou-lendo-sem-progresso.md)).

## 2. Objetivos

| # | Objetivo | Como saber que deu certo |
|---|----------|--------------------------|
| O1 | Gerar uma lista de sugestões útil logo no começo | Com **5 livros avaliados**, a lista "Para você" já aparece com pelo menos 10 títulos |
| O2 | Sugestões que eu realmente quero ler | Das 10 primeiras sugestões, **≥ 5** eu salvo como "quero ler" em vez de dispensar |
| O3 | Registrar um livro lido sem fricção | Buscar, adicionar e dar nota em **< 30 s** por livro |
| O4 | Cada livro com recomendações próprias | **≥ 80 %** dos meus livros lidos mostram "Parecidos com este" preenchido; **≥ 40 %** mostram "Quem leu este também gostou" preenchido |
| O5 | Acertar no longo prazo | Livros que li **por causa** de uma sugestão têm nota média **≥ 4** (avaliado após 3 meses) |

## 3. Fora do escopo (não-objetivos)

| Não vamos fazer | Por quê |
|-----------------|---------|
| Leitor de e-book, progresso de leitura (página, percentual, prazo), metas anuais | O produto é recomendação, não leitura. Goodreads/Skoob já fazem isso. A lista "Estou lendo" (R13) não conta como progresso: é só o estado entre Quero ler e Já li ([ADR 0008](adr/0008-estou-lendo-sem-progresso.md)). |
| Vários usuários, perfis, rede social, seguir amigos | Só eu uso na v1. Adiciona login, privacidade e moderação sem benefício agora. |
| Resenhas escritas e comentários | Nota basta para o algoritmo. Texto livre não melhora as sugestões da v1. |
| Links de compra, preços, afiliados | Não ajuda a decidir *o que* ler; pode virar P2. |
| App nativo (iOS/Android) | Um web app responsivo resolve o uso de uma pessoa. |
| Hospedagem, acesso pelo celular fora de casa, login | A v1 roda local (ADR 0005). Hospedar fica para uma segunda onda. |
| Gerar o "quem leu também gostou" a partir dos **meus** dados | Com um usuário só não existe "quem mais leu". Os dados vêm de uma base pública (ver R5). |

## 4. Histórias de usuário

Persona única: **o leitor** (eu).

**Registrar leituras**
1. Como leitor, quero buscar um livro por título, autor ou ISBN e adicioná-lo como lido, para não digitar capa, autor e ano à mão.
2. Como leitor, quero dar uma nota de 1 a 5 a cada livro lido, para que as sugestões pesem o que gostei e o que não gostei.
3. Como leitor, quero mudar a nota ou remover um livro, para corrigir erros e refletir mudanças de opinião.
4. Como leitor, quero ver minha estante (todos os lidos) ordenada por nota ou por data de inclusão, para rever o que já li.

**Receber sugestões**
5. Como leitor, quero uma lista "Para você" com livros que ainda não li, para escolher a próxima leitura.
6. Como leitor, quero ver o motivo de cada sugestão ("porque você deu 5 a *Duna*"), para confiar ou descartar rapidamente.
7. Como leitor, quero abrir qualquer livro (lido ou sugerido) e ver "Parecidos com este" e "Quem leu este também gostou", para explorar a partir de um título que me interessou.
8. Como leitor, quero que livros com nota baixa **afastem** sugestões parecidas, para não receber mais do que não gosto.

**Casos de borda**
9. Como leitor novo, com menos de 3 livros avaliados, quero entender que preciso avaliar mais livros, em vez de ver uma lista vazia sem explicação.
10. Como leitor, quando um livro não tem dados de outros leitores, quero ver isso dito com clareza, em vez de uma lista inventada.
11. Como leitor, quando a busca não encontra o livro, quero cadastrá-lo manualmente (título + autor), para não perder o registro.

## 5. Requisitos

### P0: sem isso não lança

**R1. Buscar e adicionar livro lido**
- Busca por título, autor ou ISBN no Catálogo local e no Google Books. A Open Library identifica a obra e o título original (ver Q3).
- Ao adicionar, guarda: título, autor(es), ano, capa, assuntos/gêneros, descrição, ISBN e o identificador da *obra* (agrupa edições e traduções).
- Para livro traduzido, guarda também o **título original** e, quando houver, o ISBN da edição original. É o que liga a edição brasileira à base pública de avaliações (R5b), que é quase toda em inglês.
- Cadastro manual (título + autor) quando a busca não encontra.
- Critérios de aceite:
  - [ ] Dado que digito "duna herbert", quando busco, então vejo resultados com capa, autor e ano em até 2 s.
  - [ ] Dado um livro já na estante, quando tento adicioná-lo de novo (mesma obra, outra edição), então o app avisa que já está lá e não duplica.
  - [ ] Dado que a busca não retorna nada, então aparece a opção "cadastrar manualmente".
  - [ ] Dado que adiciono a edição brasileira de um livro estrangeiro, então o título original fica preenchido automaticamente ou pode ser informado à mão.

**R2. Nota**
- Nota inteira de 1 a 5 (meia estrela: ver Q5). Obrigatória para entrar no cálculo; livro sem nota fica na estante mas é ignorado nas sugestões.
- Editar e remover a qualquer momento; sugestões refletem a mudança na próxima vez que a lista é aberta.
- Critérios de aceite:
  - [ ] Dado que mudo a nota de *X* de 5 para 1, quando abro "Para você", então as sugestões cujo motivo era *X* caem ou somem.
  - [ ] Dado que removo um livro, então ele pode voltar a aparecer como sugestão.

**R3. Minha estante**
- Lista dos livros lidos com capa, título, autor e nota; ordena por nota ou data de inclusão.
- Critérios de aceite:
  - [ ] Estante vazia mostra chamada para adicionar o primeiro livro.

**R4. Lista "Para você"**
- Até 20 sugestões, ordenadas por pontuação, **nunca** incluindo livros já lidos.
- Cada sugestão mostra 1 motivo em linguagem simples, citando o livro lido que mais pesou.
- Combina as duas fontes: similaridade de conteúdo (R5a) e "quem leu também gostou" (R5b). Livros com nota 1–2 pesam negativamente.
- Critérios de aceite:
  - [ ] Dado < 3 livros avaliados, então vejo "Avalie pelo menos 3 livros para receber sugestões" e um contador.
  - [ ] Dado ≥ 5 livros avaliados, então vejo ≥ 10 sugestões.
  - [ ] Nenhuma sugestão é um livro da estante (inclusive outra edição ou tradução da mesma obra).
  - [ ] Todo item tem um motivo; nenhum motivo cita livro com nota ≤ 2 como razão positiva.

**R5. Página do livro**
- Para qualquer livro (lido ou sugerido): capa, título, autor, ano, descrição, assuntos, e minha nota se já li.
- **R5a. "Parecidos com este"**: até 10 livros com conteúdo semelhante (assuntos, autor, descrição).
- **R5b. "Quem leu este também gostou"**: até 10 livros que leitores que deram nota alta a este também avaliaram bem, calculado sobre uma base pública de avaliações (ver Q2).
- Livros já lidos aparecem nas duas seções com selo "lido", para eu reconhecer o padrão.
- Critérios de aceite:
  - [ ] Dado um livro sem correspondência na base pública, então R5b mostra "Ainda não há dados de outros leitores para este livro" e **não** preenche com outra fonte.
  - [ ] Clicar em qualquer recomendação abre a página daquele livro (navegação em cadeia).
  - [ ] Livro sugerido tem ação "Já li" que abre direto a nota (R1 + R2 num passo).

**R6. Um leitor, local** _(revisado: o login saiu, ver [ADR 0005](adr/0005-local-first.md))_
- O app roda só no meu computador, acessível apenas em `localhost`, sem login. Existe um único leitor fixo.
- Modelo de dados já com o id do leitor (`leitor_id`) em tudo que é pessoal (estante, notas), para não fechar a porta ao P2 de multiusuário.
- Critérios de aceite:
  - [ ] O app não responde a acessos de outros computadores da rede.

**R12. Montagem da Estante** _(novo; substitui a importação no P0)_
- No primeiro uso, com a estante vazia, escolho gêneros de interesse e vejo uma grade dos livros mais lidos desses gêneros. Para cada um, dou nota se li ou marco "Não li".
- Um contador vai até 5 notas (O1) e então leva às sugestões. A busca do R1 fica disponível no mesmo fluxo.
- Critérios de aceite:
  - [ ] Dado que abro o app com a estante vazia, então vejo a Montagem da Estante, não uma tela vazia.
  - [ ] Dado que dou a 5ª nota, então aparece o botão "Ver minhas sugestões".
  - [ ] Livros marcados "Não li" não voltam na mesma sessão.

### P1: logo depois do lançamento

| Req. | Descrição | Critério principal |
|------|-----------|--------------------|
| R7 | **Dispensar sugestão** ("não tenho interesse") | Livro dispensado não volta à lista "Para você" |
| R8 | **Quero ler**: salvar sugestão, ou um livro que busquei, numa lista à parte | Lista separada da estante; sai dela quando marco "Já li"; o livro buscado entra sem Nota |
| R10 | **Filtros** na lista "Para você" por gênero e idioma | Filtro não recalcula a pontuação, só esconde itens |
| R11 | **Motivo detalhado**: ver todos os livros lidos que contribuíram para uma sugestão | Lista os 3 maiores contribuintes com peso |
| R13 | **Estou lendo**: lista das Obras que comecei, sem página nem percentual | Entra por "Para você", Quero ler ou a página do livro; sai de Quero ler ao entrar e sai da lista quando marco "Já li"; não aparece em "Para você" |
| R14 | **Livros técnicos**: uma aba "Tecnologia" em "Para você", com Sugestões de software, dados, arquitetura, UX, DevOps e gestão de times de tecnologia ([ADR 0009](adr/0009-obras-tecnicas-da-open-library.md)) | Com 3 livros avaliados, mesmo sem nenhum técnico, a aba mostra ≥ 10 sugestões técnicas, cada uma com motivo; lançamentos recentes (ex.: *AI Engineering*) estão no catálogo; a lista geral não muda |

### P2: futuro (projetar para não impedir)

- **Multiusuário**: quando houver outros leitores, usar as notas deles no "quem leu também gostou" (por isso o `usuario_id` em R6).
- **Base pública maior** (ex.: UCSD Book Graph, ~2 M livros) para aumentar a cobertura de R5b.
- **R9 Importar histórico** _(movido do P1: não tenho histórico em nenhum serviço hoje; a Montagem da Estante, R12, cobre o começo)_: CSV do Goodreads, notas do Hardcover ou planilha do Skoob. Importa ≥ 90 % das linhas com correspondência e mostra as que falharam para resolver à mão. A importação do Goodreads chegou a ser feita e foi retirada em 26/11/2026, porque não uso o Goodreads ([ADR 0011](adr/0011-importacao-do-goodreads.md)).
- **Hospedagem** (acesso pelo celular, login): segunda onda, depois de a v1 local se provar útil.
- **LLM** para reescrever motivos e reordenar sugestões.
- **Onde conseguir o livro**: biblioteca, loja, e-book.

## 6. Como as recomendações funcionam (visão de produto)

Duas fontes, com papéis diferentes:

| Fonte | Responde | Dados | Funciona para livro pouco conhecido? |
|-------|----------|-------|---------------------------------------|
| **Conteúdo** (R5a) | "É parecido com este?" | Assuntos, autor, descrição do catálogo | Sim, basta ter metadados |
| **Coleitura** (R5b) | "Quem gostou deste também gostou de quê?" | Base pública de avaliações de milhares de leitores | Só se o livro estiver na base |

Pontuação de um candidato *c* na lista "Para você", para cada livro lido *r*:

```
pontuacao(c) = Σ_r  similaridade(c, r) × peso(nota_r)

peso: 5 → +1,0 · 4 → +0,6 · 3 → 0 · 2 → −0,5 · 1 → −1,0
similaridade = α · conteudo(c, r) + (1 − α) · coleitura(c, r)   (α inicial = 0,5; ajustável)
```

O motivo exibido é o *r* com a maior parcela positiva. Os números são ponto de partida para a engenharia calibrar, não contrato.

**Livros técnicos (R14).** Nenhuma base pública com licença utilizável tem notas de leitores para livros técnicos. Por isso, eles vêm da Open Library e são sugeridos só por conteúdo (α = 1), numa aba própria, sem popularidade. A lista geral continua com a mistura acima ([ADR 0009](adr/0009-obras-tecnicas-da-open-library.md)).

## 7. Métricas de sucesso

Com um único usuário, as métricas são eventos registrados pelo próprio app, revisados à mão.

**Indicadores rápidos (1ª–4ª semana)**
- Livros avaliados na estante: meta **≥ 20** na 1ª semana (com a Montagem da Estante, R12).
- Tempo médio para adicionar + avaliar um livro: **< 30 s** (O3).
- Taxa de aceite das top 10: salvos ÷ (salvos + dispensados) **≥ 50 %**; ambicioso **≥ 70 %** (O2, depende de R7/R8).
- Cobertura por livro: % da estante com R5a e R5b preenchidos (O4).

**Indicadores lentos (3 meses)**
- Livros lidos a partir de uma sugestão: **≥ 3**.
- Nota média desses livros: **≥ 4** (O5), comparada com a média da estante.
- Continuo usando: abri o app em **≥ 1 de cada 2 semanas**.

## 8. Perguntas em aberto

| # | Pergunta | Quem responde | Bloqueia? |
|---|----------|---------------|-----------|
| Q1 | ~~Qual a proporção das minhas leituras em português de autores nacionais vs. traduções de títulos estrangeiros?~~ **Respondida (17/11/2026): a maioria é tradução.** R5b fica na v1 (fase 3). A correspondência com a base pública precisa ir da edição brasileira para a obra original (ver R1). | Eu (usuário) | Resolvida |
| Q2 | ~~Qual base pública usar para coleitura?~~ **Respondida: goodbooks-10k** (CC BY-SA 4.0, notas por obra). Book-Crossing rejeitado; UCSD Goodreads só para avaliação offline, por licença ([ADR 0003](adr/0003-goodbooks-10k.md)). A taxa de correspondência é medida na fase 3. | Engenharia / dados | Resolvida |
| Q3 | ~~Google Books ou Open Library?~~ **Respondida: os dois, com papéis diferentes.** Google Books faz a busca; a Open Library (API para um livro por vez, dumps para o catálogo) identifica a obra e o título original, porque é a única que agrupa traduções numa obra. Ver [pesquisa](research/fontes-de-dados.md). | Engenharia | Resolvida |
| Q4 | ~~Web hospedado ou local?~~ **Respondida: local** (Streamlit + PostgreSQL no Docker + GPU), sem login ([ADR 0005](adr/0005-local-first.md)). | Eu | Resolvida |
| Q5 | ~~Meia estrela?~~ **Respondida: não**, nota inteira de 1 a 5. | Eu | Resolvida |
| Q6 | ~~De onde vem meu histórico?~~ **Respondida: de nenhum lugar.** Entra a Montagem da Estante (R12) no P0; a importação (R9) vai para o P2. | Eu | Resolvida |

## 9. Fases e prazos

Sem prazo fixo. Cada fase entrega algo usável.

| Fase | Entrega | Requisitos |
|------|---------|------------|
| 0. Fundação | Banco, catálogo carregado da base pública, início automático com o PC | (ver SPEC §6) |
| 1. Estante | Buscar, adicionar, dar nota, ver estante, Montagem da Estante | R1, R2, R3, R6, R12 |
| 2. Parecidos | Página do livro com "Parecidos com este" e lista "Para você" só com conteúdo | R4 (α = 1), R5, R5a |
| 3. Coleitura | Base pública carregada; "Quem leu também gostou" e mistura na lista | R5b, R4 completo |
| 4. Ajustes | Dispensar, quero ler, filtros, motivo detalhado | R7, R8, R10, R11 |
| 5. Estou lendo | Lista das Obras em leitura, entre Quero ler e Já li | R13 |
| 6. Livros técnicos | Obras técnicas da Open Library no catálogo e aba "Tecnologia" em "Para você" | R14 |

**Dependências:** API de catálogo (fase 1); escolha e licença da base pública (fase 3). Como a maioria das leituras é tradução (Q1), a fase 3 continua antes da 4. O risco que resta é a taxa de correspondência edição brasileira → obra original. Se ficar abaixo de 40 % (O4), reavaliar a base (Q2).
