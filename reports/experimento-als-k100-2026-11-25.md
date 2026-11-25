# K = 100 no conteúdo e ALS: avaliação offline (25/11/2026)

O ADR 0007 deixou dois testes pendentes: o K = 100 no conteúdo e o ALS (`implicit`), que é o candidato alternativo à Coleitura item-item (SPEC §8.1). Os dois perdem para o que está no ar.

- **Protocolo:** o do §9: 5.000 leitores, semente 42, 20 % das Notas ≥ 4 de cada leitor no teste, Coleitura e ALS treinados só com as Notas de treino, tabela de pesos do PRD.
- **Script:** `scripts/experimento_als_k100.py`, rodado com `uv run --with implicit python scripts/experimento_als_k100.py <saida.csv>`. Ele só lê o banco.
- **Grade completa:** `experimento-als-k100-2026-11-25.csv`.
- **Conferência:** a mistura que está no ar deu os mesmos números do ADR 0007 (0,3177 com β = 0; 0,2967 com β = 0,25).

## Conteúdo com K = 100

Os Vizinhos saem dos embeddings da execução de conteúdo 1 (`data/embeddings/conteudo-1.npz`, Qwen3-Embedding-4B), com o mesmo limite de 5 Obras do mesmo autor. O K = 50 recalculado reproduz o gravado.

| Configuração | β = 0 | β = 0,25 |
|---|---|---|
| Conteúdo K = 50, sozinho | 0,0650 | 0,1143 |
| Conteúdo K = 100, sozinho | 0,0541 | 0,0990 |
| **Mistura α = 0,25: conteúdo K = 50 + item-item (no ar)** | **0,3177** | **0,2967** |
| Mistura α = 0,25: conteúdo K = 100 + item-item | 0,3157 | 0,2927 |
| Mistura α = 0,5: conteúdo K = 50 + item-item | 0,2953 | 0,2827 |
| Mistura α = 0,5: conteúdo K = 100 + item-item | 0,2695 | 0,2610 |

NDCG@20. Com K = 100, o conteúdo traz Vizinhos menos parecidos (a similaridade de conteúdo é quase plana, ADR 0007), que somam pontos a Obras ruins. **O K = 50 fica.**

## ALS no lugar da Coleitura item-item

- **Modelo:** `implicit.als.AlternatingLeastSquares` (0.7.3, CPU), 15 iterações.
- **Similaridade:** o cosseno entre os vetores de item, com os K maiores > 0, como no §8.1. A saída vai para a mesma pontuação do §8.5.
- **Entradas:**
  - "todas": cada Nota é uma interação;
  - "boas": só as Notas ≥ 4.
- **Grade:** fatores 64, 128 e 256; regularização 0,01 e 0,1; K = 20 e K = 50.

| Configuração (β = 0,25) | NDCG@20 | Cobertura |
|---|---|---|
| **Item-item, K = 20, λ = 10 (no ar), sozinha** | **0,2925** | 40 % |
| Melhor ALS sozinho: todas, 64 fatores, reg 0,1, K = 20 | 0,2467 | 64 % |
| **Mistura α = 0,25 com item-item (no ar)** | **0,2967** | 40 % |
| Melhor mistura α = 0,25 com ALS: mesma configuração | 0,2603 | 58 % |

- Com β = 0, o melhor ALS sozinho dá 0,1836 e a item-item dá 0,3121.
- O ALS perde 12 % a 16 % do NDCG@20 em todas as configurações. Mais fatores e K = 50 pioram.
- O ALS cobre mais o Catálogo (58 % a 88 %), mas o critério de entrada do §9.4 é o NDCG@20. **A Coleitura item-item fica.**

## O que não foi testado

- A pontuação nativa do ALS (vetor do leitor × vetores de item), porque o "Para você" pontua a partir das Leituras da Estante (§8.5) e não tem vetor de leitor.
- A ponderação BM25 ou TF-IDF da entrada, e o ALS na GPU: o `implicit` do Windows não traz CUDA. No CPU, 64 e 128 fatores treinam em 4 s, e 256 fatores em ~65 s.
