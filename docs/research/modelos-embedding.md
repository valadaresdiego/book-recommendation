# Modelos de embedding multilíngues (PT + EN) para similaridade de livros

Data da pesquisa: 17/11/2026. Hardware-alvo: RTX 3060 12 GB. Armazenamento: PostgreSQL + pgvector.

## Tabela resumo (abertos, MTEB(Multilingual, v2) = MMTEB)

Posição = ranking Borda entre **todos** os modelos (abertos e fechados) no benchmark `MTEB(Multilingual, v2)`. Nota = "Mean (Task)". Os dados vêm do repositório oficial de resultados [embeddings-benchmark/results](https://github.com/embeddings-benchmark/results), carregado com o pacote `mteb` 2.27.15 e rodado localmente em 17/11/2026 (a interface web do leaderboard não renderiza sem JavaScript). A posição exata na UI ao vivo pode diferir um pouco. VRAM fp16 = parâmetros x 2 bytes, **estimativa** só dos pesos (não medida).

| # | Modelo (HF) | Params | Dim nativa / MRL | Contexto | Licença | VRAM fp16 (pesos) | Prefixo / instrução | Posição MMTEB | Nota MMTEB |
|---|---|---|---|---|---|---|---|---|---|
| 1 | [microsoft/harrier-oss-v1-27b](https://huggingface.co/microsoft/harrier-oss-v1-27b) | 27,0 B | 5376 / MRL não confirmado | 32k (leaderboard: 131k) | MIT | ~54 GB | Query com instrução; documento sem | 1 | 74,27 |
| 2 | [tencent/KaLM-Embedding-Gemma3-12B-2511](https://huggingface.co/tencent/KaLM-Embedding-Gemma3-12B-2511) | 11,8 B | 3840 / MRL sim (64 a 3840) | 32k | tencent-kalm-embedding-community (termos não lidos) | ~23,5 GB | Query: `Instruct: ...\nQuery: `; doc sem | 2 | 72,32 |
| 3 | [Qwen/Qwen3-Embedding-8B](https://huggingface.co/Qwen/Qwen3-Embedding-8B) | 7,6 B | 4096 / MRL sim (32 a 4096) | 32k | Apache-2.0 | ~15 GB | Query: `Instruct: ...\nQuery: `; doc sem | 4 | 70,58 |
| 4 | [nvidia/llama-embed-nemotron-8b](https://huggingface.co/nvidia/llama-embed-nemotron-8b) | 7,5 B | 4096 / MRL não confirmado | 32k | NVIDIA NSCL (não comercial) + Llama 3.1 | ~15 GB | Query com instrução; doc sem | 3 | 69,46 |
| 5 | [Qwen/Qwen3-Embedding-4B](https://huggingface.co/Qwen/Qwen3-Embedding-4B) | 4,0 B | 2560 / MRL sim (32 a 2560) | 32k | Apache-2.0 | ~8 GB | Idem Qwen3 | 6 | 69,45 |
| 6 | [microsoft/harrier-oss-v1-0.6b](https://huggingface.co/microsoft/harrier-oss-v1-0.6b) | 0,6 B | 1024 / MRL não confirmado | 32k | MIT | ~1,2 GB | Query com instrução (preset `sts_query` existe); doc sem | 10 | 69,01 |
| 7 | [jinaai/jina-embeddings-v5-text-small](https://huggingface.co/jinaai/jina-embeddings-v5-text-small) | 0,6 B | 1024 / MRL sim (32 a 1024) | 32k | **CC BY-NC 4.0** | ~1,2 GB | `task=` (retrieval, text-matching, clustering, classification); `prompt_name` query/document | 15 (sem Mean no cálculo local) | 67,7 (só no card) |
| 8 | [microsoft/harrier-oss-v1-270m](https://huggingface.co/microsoft/harrier-oss-v1-270m) | 0,27 B | 640 / MRL não confirmado | 32k | MIT | ~0,5 GB | Igual ao harrier | 19 | 66,55 |

Outros relevantes: [Octen/Octen-Embedding-8B](https://huggingface.co/Octen/Octen-Embedding-8B) (posição 7, 67,84, Apache, 15 GB, não cabe), [codefuse-ai/F2LLM-v2-4B](https://huggingface.co/codefuse-ai/F2LLM-v2-4B) (posição 12, 67,06, Apache, 8 GB), [Qwen/Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) (posição 20, 64,34, Apache, MRL 32 a 1024), [jina-v5-text-nano](https://huggingface.co/jinaai/jina-embeddings-v5-text-nano) (239 M, 768 dim, NC, card diz 65,5), [intfloat/multilingual-e5-large-instruct](https://huggingface.co/intfloat/multilingual-e5-large-instruct) (posição 27, 63,22, MIT, 512 tokens), [google/embeddinggemma-300m](https://huggingface.co/google/embeddinggemma-300m) (posição 31, 61,15, licença Gemma, bf16 ou fp32, **não fp16**), [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) (posição 51, MIT, 1024 dim, 8192 tokens, sem prefixo; nota Mean ausente no cálculo local).

Excluídos por não serem abertos: gemini-embedding-001 (posição 5) e Bytedance Seed1.6-embedding (posição 11).

Observações de método:
- Parâmetros e dimensões vêm dos model cards e do metadado do `mteb`. Quando divergem, usei o card.
- Para o jina-v5, o cálculo local não tem "Mean (Task)" (resultados incompletos no repositório). A nota 67,7 vem do card do modelo e não foi confirmada no leaderboard.
- Blogs de terceiros (mixpeek, futureagi etc.) citam números parecidos, mas não os usei como fonte.

## Desempenho em português

O MMTEB não publica ranking só de português. Fiz um recorte local: média das tarefas com subconjunto `por` (12 tarefas, incluindo bitext mining, Belebele, Wikipedia retrieval/reranking, Massive, SIB200). É **indicativo**, não oficial, e há tarefas ruidosas (SIB200 do F2LLM destoa, 0,93).

| Modelo | Média PT (recorte) |
|---|---|
| harrier-oss-v1-27b | 0,750 |
| F2LLM-v2-4B | 0,748 (inflado pelo SIB200) |
| Qwen3-Embedding-8B | 0,743 |
| llama-embed-nemotron-8b | 0,736 |
| KaLM-Gemma3-12B | 0,735 |
| Qwen3-Embedding-4B | 0,727 |
| harrier-oss-v1-0.6b | 0,717 |
| multilingual-e5-large-instruct | 0,704 |
| harrier-oss-v1-270m | 0,694 |
| BAAI/bge-m3 | 0,693 |
| Qwen3-Embedding-0.6B | 0,686 |
| jina-v5-text-nano | 0,678 |
| embeddinggemma-300m | 0,672 |
| jina-v5-text-small | 0,666 |

Retrieval/reranking em português (Wikipedia, Belebele): Qwen3-4B e 8B ficam acima de harrier-0.6b (ex.: WikipediaRetrieval 0,907 e 0,918 contra 0,842). No STS global, Qwen3-8B e 4B (0,811 e 0,809) e Octen (0,813) lideram; harrier-0.6b tem 0,771 e jina-v5-small 0,788.

## O que cabe em 12 GB (fp16, lote offline)

| Cabe | Não cabe em fp16 |
|---|---|
| Qwen3-Embedding-4B (~8 GB de pesos; com textos de 100 a 400 tokens e lote de 16 a 32 deve sobrar margem, mas teste) | harrier-27b (~54 GB) |
| harrier-0.6b, harrier-270m, Qwen3-0.6B, jina-v5-small/nano, bge-m3, e5-large-instruct (todos abaixo de 1,5 GB) | KaLM-12B (~23,5 GB) |
| F2LLM-v2-4B (~8 GB) | Qwen3-8B, Nemotron-8B, Octen-8B (~15 GB cada; só com 8-bit/4-bit, que não testei) |
| embeddinggemma-300m cabe, mas só em bf16/fp32 (o card avisa que fp16 não é suportado) | |

Latência interativa (< 1 s para 1 texto): não medi. Para modelos até 4B numa 3060, texto curto deve ficar bem abaixo de 1 s, mas **não confirmado**. Meça no bake-off.

## Recomendação: 3 finalistas para o bake-off

| Finalista | Por quê | Trade-off | Dimensão no pgvector |
|---|---|---|---|
| **Qwen3-Embedding-4B** (Apache-2.0) | Melhor qualidade que cabe em fp16 (posição 6, 69,45; STS 0,809; bom em PT). Licença livre. MRL. | ~8 GB de VRAM; mais lento; instrução em inglês na query | `vector(1024)` via MRL (truncar e renormalizar) com HNSW. Alternativas: 2000 em `vector`, ou 2560 nativo em `halfvec(2560)` (limite 4000). |
| **harrier-oss-v1-0.6b** (MIT) | Quase empata em nota (69,01, posição 10) com 1/7 do tamanho, 1,2 GB, MIT, contexto 32k | Query exige instrução; MRL não documentado; STS menor (0,771) | Nativo 1024 em `vector(1024)`. |
| **jina-embeddings-v5-text-small** | Adaptador `text-matching` feito para similaridade; STS 0,788; MRL; 1,2 GB | **CC BY-NC 4.0**: uso comercial exige contato com a Jina. Nota MMTEB só no card | `vector(1024)` ou truncar para 768/512. |

Se a licença não comercial for problema, troque o terceiro por Qwen3-Embedding-0.6B (Apache, MRL, posição 20) ou BAAI/bge-m3 (MIT, sem prefixo, 8192 tokens, linha de base conhecida).

Protocolo sugerido: monte 200 a 300 pares de livros julgados à mão (similar ou não) e compare nDCG@10 ou correlação de Spearman entre os 3 candidatos, e 1024 contra 512 dimensões. O MMTEB é média de muitas tarefas e línguas e não mede "similaridade de livros".

Dica de entrada (inferência minha a partir dos cards, a validar): para similaridade simétrica livro-com-livro, use a mesma instrução nos dois lados nos modelos com instrução (ex.: `Instruct: Retrieve semantically similar books\nQuery: ...`), ou o adaptador `text-matching` no jina.

## pgvector e Docker

Fontes: [README do pgvector](https://github.com/pgvector/pgvector) e [tags no Docker Hub](https://hub.docker.com/r/pgvector/pgvector/tags).

- Versão atual: **0.8.7** (README e tags `0.8.7-pg17`/`0.8.7-pg18`). Data de lançamento não confirmada (o Docker Hub mostra tags enviadas "há 5 dias", por volta de 12/11/2026).
- Imagens oficiais: `pgvector/pgvector:pg17` e `pgvector/pgvector:pg18` (também `-trixie` e `-bookworm`). Para reprodutibilidade, fixe `0.8.7-pg18` ou `0.8.7-pg17`. O pg18 já existe, então "pg17 ou mais recente" é atendido.
- Limites de dimensão confirmados no README:

| Tipo | Armazenamento máx. | Índice HNSW | Índice IVFFlat |
|---|---|---|---|
| `vector` | 16.000 | **2.000** | **2.000** |
| `halfvec` | 16.000 | **4.000** | **4.000** |
| `bit` | não informado | 64.000 | 64.000 |
| `sparsevec` | 16.000 não nulos | 1.000 não nulos | não listado |

Para 10 a 20 mil vetores, busca exata (sem índice) já é rápida; o HNSW só vira necessidade com muito mais dados.

## Itens não confirmados

- Posição ao vivo na UI do leaderboard (o ranking acima é reprodução local a partir dos resultados oficiais).
- MRL para harrier e nemotron.
- Nota MMTEB oficial do jina-v5 (só a do card).
- Termos exatos da licença do KaLM.
- Data de lançamento do pgvector 0.8.7.
- Latência real e VRAM real com lote (apenas estimativas).
