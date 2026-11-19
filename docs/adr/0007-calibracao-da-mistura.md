# Escalas igualadas na mistura conteúdo + Coleitura; α = 0,25, β = 0, K = 20, λ = 10

A fase 3 calibrou a pontuação de "Para você" (SPEC §8.5) com a varredura do §9.4. Três decisões, tomadas pelo Leitor em 19/11/2026:

1. **Cada execução divide as suas similaridades pela média delas** (`execucao_modelo.parametros.escala`) antes da mistura por α.
2. **α = 0,25** (peso do conteúdo) e **β = 0** (sem peso da popularidade), na `config`.
3. **Coleitura com K = 20 e λ = 10**, no lugar do ponto de partida do §8.1 (K = 50, λ = 50).

Execuções ativas: conteúdo 1 (`Qwen/Qwen3-Embedding-4B`) e Coleitura 5 (cosseno ajustado, K = 20, λ = 10), ativada em 19/11/2026.

## Por que igualar as escalas

A primeira varredura somou as similaridades brutas. Nenhum α > 0 alcançava a Coleitura sozinha, e o NDCG@20 caía conforme α subia. O motivo é a escala:

| Posição do Vizinho | 1º | 10º | 20º | 50º |
|---|---|---|---|---|
| Conteúdo (Qwen3-4B), média | 0,702 | 0,582 | 0,560 | 0,535 |
| Coleitura (K = 50, λ = 50), média | 0,163 | 0,036 | 0,017 | 0,007 |

A similaridade de conteúdo é alta e quase plana. Com α = 0,25, a parcela do conteúdo ainda era de 5 a 10 vezes a da Coleitura, e funcionava como uma contagem de quantas Leituras têm a candidata entre os Vizinhos. Só um α de 0,02 a 0,05 equilibrava as duas. Esse número é difícil de ler e teria de ser recalibrado a cada troca de modelo de embedding.

Dividindo cada tipo pela média dos seus Vizinhos, o α volta a ser o peso relativo de cada critério, e o melhor α é 0,25. As alternativas testadas deram o mesmo resultado, dentro do ruído:

| Mistura (K = 20, λ = 10, β = 0) | NDCG@20 |
|---|---|
| Só Coleitura (α = 0) | 0,3117 |
| Bruta, α = 0,02 | 0,3163 |
| Conteúdo centrado (sim − 0,48), α = 0,1 | 0,3163 |
| **Escalas igualadas, α = 0,25** | **0,3176** |

A escala é gravada por `calcular-conteudo` e `calcular-coleitura`, e a migração 0005 preencheu a das execuções antigas. Os Vizinhos interativos de uma Obra do Leitor (§7.3) não mudam a escala da execução.

## Números

Avaliação offline do §9 (5.000 leitores, semente 42), em `reports/avaliacao-2026-11-19.md`, com a grade completa em `reports/varredura-2026-11-19.csv`. A Coleitura é recalculada só com as Notas de treino.

NDCG@20 (cobertura), K = 20, λ = 10, pesos do PRD:

| α | β = 0 | β = 0,25 | β = 0,5 | β = 1 |
|---|---|---|---|---|
| 0 (só Coleitura) | 0,3117 (54 %) | 0,2924 (40 %) | 0,2518 (28 %) | 0,1899 (14 %) |
| **0,25** | **0,3176 (56 %)** | 0,2965 (40 %) | 0,2519 (27 %) | 0,1865 (12 %) |
| 0,5 | 0,2952 (56 %) | 0,2826 (38 %) | 0,2382 (24 %) | 0,1785 (10 %) |
| 0,75 | 0,2023 (51 %) | 0,2243 (33 %) | 0,2021 (19 %) | 0,1657 (9 %) |
| 1 (só conteúdo) | 0,0650 (42 %) | 0,1143 (27 %) | 0,1322 (16 %) | 0,1341 (8 %) |

Popularidade (baseline): 0,0828. NDCG@20 por K e λ (α = 0,25, β = 0):

| K | λ = 10 | λ = 50 | λ = 100 |
|---|---|---|---|
| 20 | **0,3176** | 0,3166 | 0,3140 |
| 50 | 0,3112 | 0,3079 | 0,3034 |
| 100 | 0,3083 | 0,3050 | 0,3006 |

A tabela de pesos simétrica (4 → 0,5) ficou um pouco abaixo da do PRD (0,3143 contra 0,3176), e a do PRD continua.

## Por que β = 0

O β = 0,25 do ADR 0006 compensava o conteúdo sozinho, que achava Obras parecidas mas pouco lidas. A Coleitura já traz a popularidade embutida: o β só piora o NDCG@20 e corta a cobertura (56 % → 40 % com β = 0,25).

**Risco aceito:** uma Leitura de Obra fora da Base só tem Vizinhos de conteúdo. Uma Estante com muitas Obras assim volta a receber Sugestões de conteúdo pouco lidas, que era o problema do ADR 0006. A avaliação não mede esse caso, porque os leitores da Base só têm Obras da Base. Se ele aparecer no uso, a saída é voltar o β na `config`, sem mudar código.

## Consequências

- Fase 3: o NDCG@20 combinado (0,3176) é ≥ ao melhor isolado (Coleitura, 0,3117). Critério do §14 cumprido.
- K e λ variam só a Coleitura. O conteúdo usa os Vizinhos gravados (K = 50); testar K = 100 no conteúdo exigiria `calcular-conteudo --k`, e ficou de fora.
- Com β = 0, o conteúdo sozinho fica abaixo da popularidade (0,0650 contra 0,0828). Ele não é usado sozinho desde a fase 3. Se a Coleitura for desativada, o β volta para 0,25.
- Uma execução só substitui a ativa do mesmo tipo se as duas foram avaliadas com a mesma divisão e o mesmo β (`ativar` confere `metricas.divisao` e `metricas.beta`). As execuções de conteúdo 2 e 3 têm métricas com β = 0,25 e precisam de um `avaliar` novo antes de concorrer.
- O ALS (`implicit`), candidato alternativo do §8.1, não foi testado. A Coleitura item-item já passa com folga do conteúdo e da popularidade.

## Atualização (19/11/2026): β volta para 0,25

O Leitor decidiu voltar o β para 0,25 antes de começar a registrar Leituras, para não correr o risco aceito acima: as Obras fora da Base, que só têm Vizinhos de conteúdo, voltariam a trazer Sugestões pouco lidas.

- Custo medido na varredura (α = 0,25, K = 20, λ = 10, tabela do PRD): NDCG@20 de 0,3176 para 0,2965 (−6,6 %) e cobertura de 56 % para 40 %. Ainda bem acima da popularidade (0,0828).
- α, K, λ e a tabela de pesos não mudam.
- Como o `ativar` só compara execuções avaliadas com o mesmo β, as execuções ativas precisam de um `avaliar` com β = 0,25 antes de uma nova concorrer com elas.
- Voltar para β = 0 é só mudar `beta_popularidade` na `config`.
