# Avaliação offline — 18/11/2026

Divisão (SPEC §9.1): {"leitores": 5000, "min_notas": 20, "frac_teste": 0.2, "semente": 42}.
Leitores com teste: 5000.

Pontuação com β = 0,2500 (peso da popularidade, ADR 0006).

| Execução | Modelo | NDCG@20 | Recall@20 | Cobertura | Extras |
|---|---|---|---|---|---|
| 2 | `microsoft/harrier-oss-v1-0.6b` | 0,1215 | 0,1129 | 0,3682 | s_catalogo: 218, ms_uma_obra: 40, entre_idiomas: 16/20, entre_idiomas_passou: False |
| 1 | `Qwen/Qwen3-Embedding-4B` | 0,1143 | 0,1104 | 0,2714 | s_catalogo: 1054, ms_uma_obra: 126, entre_idiomas: 19/20, entre_idiomas_passou: True |
| 3 | `jinaai/jina-embeddings-v5-text-small` | 0,0919 | 0,0873 | 0,3170 | s_catalogo: 349, ms_uma_obra: 80, entre_idiomas: 20/20, entre_idiomas_passou: True |
| — | Popularidade (baseline) | 0,0828 | 0,0802 | 0,0068 | |

## NDCG@20 (cobertura) por β

| Execução | β = 0,0 | β = 0,5 | β = 1,0 | β = 0,25 |
|---|---|---|---|---|
| 1 | 0,0650 (0,4183) | 0,1322 (0,1578) | 0,1341 (0,0830) | 0,1143 (0,2714) |
| 2 | 0,0566 (0,4995) | 0,1458 (0,2181) | 0,1436 (0,1044) | 0,1215 (0,3682) |
| 3 | 0,0372 (0,3959) | 0,1289 (0,2012) | 0,1412 (0,1026) | 0,0919 (0,3170) |
