# Avaliação offline — 19/11/2026

Divisão (SPEC §9.1): {"leitores": 5000, "min_notas": 20, "frac_teste": 0.2, "semente": 42}.
Leitores com teste: 5000.

Pontuação com β = 0 (peso da popularidade, ADR 0006) e a tabela de pesos do PRD. A Coleitura é recalculada só com as Notas de treino.

| Execução | Modelo | NDCG@20 | Recall@20 | Cobertura | Extras |
|---|---|---|---|---|---|
| 5 | `cosseno-ajustado` | 0,3117 | 0,2692 | 0,5395 |  |
| 1 | `Qwen/Qwen3-Embedding-4B` | 0,0650 | 0,0678 | 0,4183 | s_catalogo: 1054, ms_uma_obra: 126, entre_idiomas: 19/20, entre_idiomas_passou: True |
| — | Popularidade (baseline) | 0,0828 | 0,0802 | 0,0068 | |

## NDCG@20 (cobertura) por β

| Execução | β = 0 | β = 0,25 | β = 0,5 | β = 1 |
|---|---|---|---|---|
| 1 | 0,0650 (0,4183) | 0,1143 (0,2714) | 0,1322 (0,1578) | 0,1341 (0,0830) |
| 5 | 0,3117 (0,5395) | 0,2924 (0,4039) | 0,2518 (0,2838) | 0,1899 (0,1429) |

## Combinação: conteúdo 1 + Coleitura 5

Com α = 0,25 (config) e β = 0: NDCG@20 0,3176, Recall@20 0,2745, cobertura 0,5632.
Critério do §14 (combinado ≥ melhor isolado, 0,3117): cumprido.

### Varredura (SPEC §9.4)

296 configurações; a grade completa está no CSV do mesmo dia. K e λ variam só a Coleitura (recalculada no treino); o conteúdo usa os Vizinhos gravados da execução.

**Melhor NDCG@20:** 0,3176 com α = 0,25, β = 0, K = 20, λ = 10, pesos `prd` (cobertura 0,5632).

As 10 melhores:

| α | β | K | λ | Pesos | NDCG@20 | Recall@20 | Cobertura |
|---|---|---|---|---|---|---|---|
| 0,25 | 0 | 20 | 10 | prd | 0,3176 | 0,2745 | 0,5632 |
| 0,25 | 0 | 20 | 50 | prd | 0,3166 | 0,2744 | 0,4994 |
| 0,25 | 0 | 20 | 10 | simetrica | 0,3143 | 0,2711 | 0,5697 |
| 0,25 | 0 | 20 | 100 | prd | 0,3140 | 0,2720 | 0,4579 |
| 0,25 | 0 | 20 | 50 | simetrica | 0,3137 | 0,2715 | 0,5082 |
| 0 | 0 | 20 | 10 | prd | 0,3117 | 0,2692 | 0,5395 |
| 0,25 | 0 | 50 | 10 | prd | 0,3112 | 0,2663 | 0,5325 |
| 0,5 | 0 | 100 | 10 | prd | 0,3111 | 0,2658 | 0,5321 |
| 0 | 0 | 20 | 50 | prd | 0,3110 | 0,2690 | 0,4712 |
| 0,25 | 0 | 20 | 100 | simetrica | 0,3109 | 0,2694 | 0,4631 |

#### NDCG@20 (cobertura) por α e β — K = 20, λ = 10, pesos do PRD

| α | β = 0 | β = 0,25 | β = 0,5 | β = 1 |
|---|---|---|---|---|
| 0 | 0,3117 (0,5395) | 0,2924 (0,4039) | 0,2518 (0,2838) | 0,1899 (0,1429) |
| 0,25 | 0,3176 (0,5632) | 0,2965 (0,4043) | 0,2519 (0,2707) | 0,1865 (0,1196) |
| 0,5 | 0,2952 (0,5616) | 0,2826 (0,3827) | 0,2382 (0,2380) | 0,1785 (0,1009) |
| 0,75 | 0,2023 (0,5108) | 0,2243 (0,3340) | 0,2021 (0,1948) | 0,1657 (0,0885) |
| 1 | 0,0650 (0,4183) | 0,1143 (0,2714) | 0,1322 (0,1578) | 0,1341 (0,0830) |

#### NDCG@20 por K e λ — α = 0,25, β = 0, pesos do PRD

| K | λ = 10 | λ = 50 | λ = 100 |
|---|---|---|---|
| 20 | 0,3176 | 0,3166 | 0,3140 |
| 50 | 0,3112 | 0,3079 | 0,3034 |
| 100 | 0,3083 | 0,3050 | 0,3006 |

#### Melhor NDCG@20 por tabela de pesos

- `prd` {5: 1.0, 4: 0.6, 3: 0.0, 2: -0.5, 1: -1.0}: 0,3176 (α = 0,25, β = 0, K = 20, λ = 10)
- `simetrica` {5: 1.0, 4: 0.5, 3: 0.0, 2: -0.5, 1: -1.0}: 0,3143 (α = 0,25, β = 0, K = 20, λ = 10)
