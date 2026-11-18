# Qwen3-Embedding-4B para a Similaridade de conteúdo, com a popularidade como peso

O bake-off do SPEC §8.4 escolheu o **`Qwen/Qwen3-Embedding-4B`** (Apache 2.0), truncado para 1024 dimensões via MRL. Ele é a execução de conteúdo 1, ativada em 18/11/2026.

O bake-off também mudou a pontuação de "Para você": a soma do §8.5 passa a ser multiplicada por **(1 + popularidade)^β**, com β = 0,25 na `config`. Sem esse peso, nenhum modelo de conteúdo vencia o baseline de popularidade, que é o critério da Fase 2.

## Números

Avaliação offline do §9: 5.000 leitores do goodbooks-10k, semente 42, 20 % das Notas ≥ 4 de cada um como teste. Relatório completo em `reports/avaliacao-2026-11-18.md`.

| Modelo | NDCG@20 (β = 0) | NDCG@20 (β = 0,25) | Cobertura (β = 0,25) | Entre idiomas | 1 Obra | Catálogo inteiro |
|---|---|---|---|---|---|---|
| **Qwen3-Embedding-4B** | 0,0650 | **0,1143** | 27 % | **19/20** | 126 ms | 17,5 min |
| harrier-oss-v1-0.6b | 0,0566 | 0,1215 | 37 % | 16/20 (reprovado) | 40 ms | 3,6 min |
| jina-embeddings-v5-text-small | 0,0372 | 0,0919 | 32 % | 20/20 | 80 ms | 5,8 min |
| Popularidade (baseline) | 0,0828 | | 0,7 % | | | |

- **Vencedor pela regra do §8.4:** é o maior NDCG@20 entre os que passam no teste entre idiomas (≥ 18 de 20), com qualquer β até 0,5. O harrier tem NDCG@20 maior, mas reprovou no teste entre idiomas. Esse teste é o que garante que uma Edição brasileira cadastrada pelo Leitor caia perto da Obra certa.
- **Tempo de uma Obra:** 126 ms na RTX 3060, abaixo do limite de 1 s do §8.4.1.
- **VRAM:** 7,6 GB enquanto o modelo está carregado. O app só carrega o modelo quando há uma Obra do Leitor sem embedding (§7.3), e o `atualizar` só carrega quando há pendentes.

## Por que a popularidade entrou na pontuação

Com β = 0, a pontuação do §8.5 só usa a popularidade para desempatar. Nenhum modelo passou de 0,065 de NDCG@20, contra 0,083 da popularidade sozinha. A similaridade de texto acha Obras parecidas, mas muitas delas pouco lidas, que os leitores da Base raramente avaliaram.

Multiplicar a soma por (1 + popularidade)^β mantém o sinal da soma, e portanto o conjunto de candidatas, a exclusão da Estante e o Motivo. Só muda a ordem:

| β | 0 | 0,25 | 0,5 | 1 |
|---|---|---|---|---|
| NDCG@20 (Qwen3-4B) | 0,0650 | 0,1143 | 0,1322 | 0,1341 |
| Cobertura | 42 % | 27 % | 16 % | 8 % |

**β = 0,25**, em vez do que maximiza o NDCG@20, porque a avaliação favorece a popularidade: os livros de teste são os que os leitores da Base avaliaram, e esses tendem a ser os mais lidos. Com 0,25, o NDCG@20 já passa a popularidade com folga (+38 %) e as Sugestões ainda cobrem mais de um quarto do Catálogo. O β fica na `config` e entra na varredura do `avaliar` (§9.4), junto com α na fase 3.

## Consequências

- Fase 2: NDCG@20 do conteúdo (0,1143) > baseline de popularidade (0,0828). Critério do §14 cumprido.
- Obras pouco lidas aparecem menos em "Para você". "Parecidos com este" (R5a) não usa o β: mostra os Vizinhos de conteúdo puros.
- Uma Obra do Leitor tem popularidade 0, e o fator dela é 1. Ela não é candidata às Sugestões, porque os Vizinhos interativos são só Obras da Base (§7.3).
- O jina-v5-small é não comercial (CC BY-NC 4.0). Ele não venceu, então a hospedagem comercial (P2) não exige trocar de modelo.
- O harrier fica como plano B se a VRAM do Qwen3-4B atrapalhar: é 3× mais rápido e cabe em 1,1 GB, mas tem de passar no teste entre idiomas (o prefixo de query `sts_query` pode ajudar e não foi testado).
