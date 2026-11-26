# Avaliação offline — 26/11/2026

Divisão (SPEC §9.1): {"leitores": 5000, "min_notas": 20, "frac_teste": 0.2, "semente": 42}.
Leitores com teste: 5000.

Pontuação com β = 0,25 (peso da popularidade, ADR 0006) e a tabela de pesos do PRD. A Coleitura é recalculada só com as Notas de treino.

Entre colchetes, o IC de 95 % por bootstrap sobre os leitores (1000 reamostras, §9.3). Uma diferença é pareada (os mesmos leitores nas duas configurações) e é **empate** quando o IC dela contém o zero.

| Execução | Modelo | NDCG@20 | Recall@20 | Cobertura | Δ NDCG@20 vs popularidade | Extras |
|---|---|---|---|---|---|---|
| 6 | `cosseno-ajustado` | 0,2925 [0,2872; 0,2984] | 0,2587 [0,2539; 0,2636] | 0,4037 | +0,2098 [0,2045; 0,2152] |  |
| 12 | `cosseno-ajustado` | 0,2925 [0,2872; 0,2984] | 0,2587 [0,2539; 0,2636] | 0,4037 | +0,2098 [0,2045; 0,2152] |  |
| 11 | `Qwen/Qwen3-Embedding-4B` | 0,1145 [0,1116; 0,1176] | 0,1104 [0,1076; 0,1132] | 0,2728 | +0,0317 [0,0284; 0,0351] |  |
| 1 | `Qwen/Qwen3-Embedding-4B` | 0,1143 [0,1114; 0,1173] | 0,1103 [0,1076; 0,1133] | 0,2708 | +0,0315 [0,0282; 0,0347] | s_catalogo: 1054, ms_uma_obra: 126, entre_idiomas: 19/20, entre_idiomas_passou: True |
| — | Popularidade (baseline) | 0,0828 [0,0797; 0,0855] | 0,0802 [0,0774; 0,0830] | 0,0068 | | |

## Diferenças pareadas entre execuções do mesmo tipo

| Execução | Menos a execução | Δ NDCG@20 |
|---|---|---|
| 1 | 11 | −0,0003 [-0,0009; 0,0003], empate |
| 6 | 12 | +0,0000 [0,0000; 0,0000], empate |

## NDCG@20 (cobertura) por β

| Execução | β = 0 | β = 0,25 | β = 0,5 | β = 1 |
|---|---|---|---|---|
| 1 | 0,0650 (0,4191) | 0,1143 (0,2708) | 0,1318 (0,1576) | 0,1339 (0,0828) |
| 6 | 0,3121 (0,5384) | 0,2925 (0,4037) | 0,2520 (0,2833) | 0,1900 (0,1429) |
| 11 | 0,0650 (0,4189) | 0,1145 (0,2728) | 0,1318 (0,1570) | 0,1336 (0,0842) |
| 12 | 0,3121 (0,5384) | 0,2925 (0,4037) | 0,2520 (0,2833) | 0,1900 (0,1429) |

## Combinação: conteúdo 11 + Coleitura 12

Com α = 0,25 (config) e β = 0,25: NDCG@20 0,2964 [0,2909; 0,3022], Recall@20 0,2618 [0,2570; 0,2669], cobertura 0,4034.
Critério do §14 (combinado ≥ melhor isolado, 0,2925): cumprido.
- Δ NDCG@20 da combinação menos a execução 11: +0,1819 [0,1767; 0,1871].
- Δ NDCG@20 da combinação menos a execução 12: +0,0039 [0,0029; 0,0049].
- Δ NDCG@20 da combinação menos a melhor da varredura: −0,0211 [-0,0231; -0,0191].

### Varredura (SPEC §9.4)

296 configurações; a grade completa está em `varredura-2026-11-26-tags-de-status.csv`. K e λ variam só a Coleitura (recalculada no treino); o conteúdo usa os Vizinhos gravados da execução.

**Melhor NDCG@20:** 0,3175 com α = 0,25, β = 0, K = 20, λ = 10, pesos `prd` (cobertura 0,5635).
0 das outras 295 configurações empatam com a melhor (o IC da diferença pareada contém o zero).

As 10 melhores:

| α | β | K | λ | Pesos | NDCG@20 | Recall@20 | Cobertura | Δ vs a melhor |
|---|---|---|---|---|---|---|---|---|
| 0,25 | 0 | 20 | 10 | prd | 0,3175 | 0,2744 | 0,5635 | — |
| 0,25 | 0 | 20 | 50 | prd | 0,3167 | 0,2743 | 0,5019 | −0,0009 [-0,0017; -0,0000] |
| 0,25 | 0 | 20 | 10 | simetrica | 0,3144 | 0,2712 | 0,5684 | −0,0031 [-0,0036; -0,0026] |
| 0,25 | 0 | 20 | 100 | prd | 0,3142 | 0,2723 | 0,4601 | −0,0033 [-0,0044; -0,0021] |
| 0,25 | 0 | 20 | 50 | simetrica | 0,3138 | 0,2717 | 0,5096 | −0,0037 [-0,0046; -0,0028] |
| 0 | 0 | 20 | 10 | prd | 0,3121 | 0,2697 | 0,5384 | −0,0054 [-0,0064; -0,0043] |
| 0,25 | 0 | 50 | 10 | prd | 0,3116 | 0,2671 | 0,5332 | −0,0059 [-0,0070; -0,0047] |
| 0 | 0 | 20 | 50 | prd | 0,3113 | 0,2692 | 0,4708 | −0,0062 [-0,0074; -0,0050] |
| 0,25 | 0 | 20 | 100 | simetrica | 0,3109 | 0,2695 | 0,4658 | −0,0066 [-0,0078; -0,0053] |
| 0,5 | 0 | 100 | 10 | prd | 0,3107 | 0,2658 | 0,5317 | −0,0068 [-0,0080; -0,0056] |

#### NDCG@20 (cobertura) por α e β — K = 20, λ = 10, pesos do PRD

| α | β = 0 | β = 0,25 | β = 0,5 | β = 1 |
|---|---|---|---|---|
| 0 | 0,3121 (0,5384) | 0,2925 (0,4037) | 0,2520 (0,2833) | 0,1900 (0,1429) |
| 0,25 | 0,3175 (0,5635) | 0,2964 (0,4034) | 0,2516 (0,2673) | 0,1861 (0,1177) |
| 0,5 | 0,2909 (0,5602) | 0,2800 (0,3792) | 0,2360 (0,2342) | 0,1775 (0,1002) |
| 0,75 | 0,1946 (0,5076) | 0,2197 (0,3317) | 0,1989 (0,1914) | 0,1647 (0,0878) |
| 1 | 0,0650 (0,4189) | 0,1145 (0,2728) | 0,1318 (0,1570) | 0,1336 (0,0842) |

#### NDCG@20 por K e λ — α = 0,25, β = 0, pesos do PRD

| K | λ = 10 | λ = 50 | λ = 100 |
|---|---|---|---|
| 20 | 0,3175 | 0,3167 | 0,3142 |
| 50 | 0,3116 | 0,3084 | 0,3039 |
| 100 | 0,3088 | 0,3054 | 0,3009 |

#### Melhor NDCG@20 por tabela de pesos

- `prd` {5: 1.0, 4: 0.6, 3: 0.0, 2: -0.5, 1: -1.0}: 0,3175 (α = 0,25, β = 0, K = 20, λ = 10)
- `simetrica` {5: 1.0, 4: 0.5, 3: 0.0, 2: -0.5, 1: -1.0}: 0,3144 (α = 0,25, β = 0, K = 20, λ = 10)
