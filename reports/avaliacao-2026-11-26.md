# Avaliação offline — 26/11/2026

Divisão (SPEC §9.1): {"leitores": 5000, "min_notas": 20, "frac_teste": 0.2, "semente": 42}.
Leitores com teste: 5000.

Pontuação com β = 0,25 (peso da popularidade, ADR 0006) e a tabela de pesos do PRD. A Coleitura é recalculada só com as Notas de treino.

Entre colchetes, o IC de 95 % por bootstrap sobre os leitores (1000 reamostras, §9.3). Uma diferença é pareada (os mesmos leitores nas duas configurações) e é **empate** quando o IC dela contém o zero.

| Execução | Modelo | NDCG@20 | Recall@20 | Cobertura | Δ NDCG@20 vs popularidade | Extras |
|---|---|---|---|---|---|---|
| 6 | `cosseno-ajustado` | 0,2925 [0,2872; 0,2984] | 0,2587 [0,2539; 0,2636] | 0,4037 | +0,2098 [0,2045; 0,2152] |  |
| 1 | `Qwen/Qwen3-Embedding-4B` | 0,1143 [0,1114; 0,1173] | 0,1103 [0,1076; 0,1133] | 0,2708 | +0,0315 [0,0282; 0,0347] | s_catalogo: 1054, ms_uma_obra: 126, entre_idiomas: 19/20, entre_idiomas_passou: True |
| — | Popularidade (baseline) | 0,0828 [0,0797; 0,0855] | 0,0802 [0,0774; 0,0830] | 0,0068 | | |

## NDCG@20 (cobertura) por β

| Execução | β = 0 | β = 0,25 | β = 0,5 | β = 1 |
|---|---|---|---|---|
| 1 | 0,0650 (0,4191) | 0,1143 (0,2708) | 0,1318 (0,1576) | 0,1339 (0,0828) |
| 6 | 0,3121 (0,5384) | 0,2925 (0,4037) | 0,2520 (0,2833) | 0,1900 (0,1429) |

## Combinação: conteúdo 1 + Coleitura 6

Com α = 0,25 (config) e β = 0,25: NDCG@20 0,2967 [0,2912; 0,3025], Recall@20 0,2620 [0,2573; 0,2671], cobertura 0,4033.
Critério do §14 (combinado ≥ melhor isolado, 0,2925): cumprido.
- Δ NDCG@20 da combinação menos a execução 1: +0,1824 [0,1773; 0,1877].
- Δ NDCG@20 da combinação menos a execução 6: +0,0041 [0,0031; 0,0051].
- Δ NDCG@20 da combinação menos a melhor da varredura: −0,0211 [-0,0230; -0,0190].

### Varredura (SPEC §9.4)

296 configurações; a grade completa está no CSV do mesmo dia. K e λ variam só a Coleitura (recalculada no treino); o conteúdo usa os Vizinhos gravados da execução.

**Melhor NDCG@20:** 0,3177 com α = 0,25, β = 0, K = 20, λ = 10, pesos `prd` (cobertura 0,5632).
0 das outras 295 configurações empatam com a melhor (o IC da diferença pareada contém o zero).

As 10 melhores:

| α | β | K | λ | Pesos | NDCG@20 | Recall@20 | Cobertura | Δ vs a melhor |
|---|---|---|---|---|---|---|---|---|
| 0,25 | 0 | 20 | 10 | prd | 0,3177 | 0,2746 | 0,5632 | — |
| 0,25 | 0 | 20 | 50 | prd | 0,3167 | 0,2744 | 0,4989 | −0,0010 [-0,0019; -0,0002] |
| 0,25 | 0 | 20 | 10 | simetrica | 0,3145 | 0,2714 | 0,5690 | −0,0032 [-0,0038; -0,0026] |
| 0,25 | 0 | 20 | 100 | prd | 0,3141 | 0,2721 | 0,4578 | −0,0037 [-0,0048; -0,0024] |
| 0,25 | 0 | 20 | 50 | simetrica | 0,3138 | 0,2719 | 0,5073 | −0,0039 [-0,0048; -0,0030] |
| 0 | 0 | 20 | 10 | prd | 0,3121 | 0,2697 | 0,5384 | −0,0056 [-0,0066; -0,0046] |
| 0,25 | 0 | 50 | 10 | prd | 0,3117 | 0,2670 | 0,5322 | −0,0061 [-0,0072; -0,0049] |
| 0 | 0 | 20 | 50 | prd | 0,3113 | 0,2692 | 0,4708 | −0,0064 [-0,0076; -0,0053] |
| 0,5 | 0 | 100 | 10 | prd | 0,3111 | 0,2659 | 0,5320 | −0,0067 [-0,0078; -0,0054] |
| 0,25 | 0 | 20 | 100 | simetrica | 0,3108 | 0,2695 | 0,4633 | −0,0069 [-0,0081; -0,0056] |

#### NDCG@20 (cobertura) por α e β — K = 20, λ = 10, pesos do PRD

| α | β = 0 | β = 0,25 | β = 0,5 | β = 1 |
|---|---|---|---|---|
| 0 | 0,3121 (0,5384) | 0,2925 (0,4037) | 0,2520 (0,2833) | 0,1900 (0,1429) |
| 0,25 | 0,3177 (0,5632) | 0,2967 (0,4033) | 0,2519 (0,2703) | 0,1865 (0,1197) |
| 0,5 | 0,2953 (0,5606) | 0,2827 (0,3819) | 0,2381 (0,2377) | 0,1785 (0,1012) |
| 0,75 | 0,2023 (0,5107) | 0,2241 (0,3342) | 0,2020 (0,1951) | 0,1656 (0,0882) |
| 1 | 0,0650 (0,4191) | 0,1143 (0,2708) | 0,1318 (0,1576) | 0,1339 (0,0828) |

#### NDCG@20 por K e λ — α = 0,25, β = 0, pesos do PRD

| K | λ = 10 | λ = 50 | λ = 100 |
|---|---|---|---|
| 20 | 0,3177 | 0,3167 | 0,3141 |
| 50 | 0,3117 | 0,3082 | 0,3037 |
| 100 | 0,3086 | 0,3051 | 0,3008 |

#### Melhor NDCG@20 por tabela de pesos

- `prd` {5: 1.0, 4: 0.6, 3: 0.0, 2: -0.5, 1: -1.0}: 0,3177 (α = 0,25, β = 0, K = 20, λ = 10)
- `simetrica` {5: 1.0, 4: 0.5, 3: 0.0, 2: -0.5, 1: -1.0}: 0,3145 (α = 0,25, β = 0, K = 20, λ = 10)
