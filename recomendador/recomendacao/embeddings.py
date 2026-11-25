"""Modelos de embedding de texto (SPEC §8.2 e §8.4).

O formato que cada modelo pede para **documento** (prefixo, tarefa, dimensão) fica aqui,
num lugar só. Os dois lados da comparação são Obras, então nenhum recebe instrução de query.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from recomendador.db.modelos import DIMENSAO_EMBEDDING

LOTE = 64


class Codificador(Protocol):
    nome: str

    def codificar(self, textos: Sequence[str]) -> np.ndarray:
        """Uma linha por texto, `DIMENSAO_EMBEDDING` colunas, float32 e norma 1."""
        ...


@dataclass(frozen=True)
class Formato:
    """Como chamar `SentenceTransformer.encode` para um documento."""

    truncar: int | None = None  # MRL: corta para `DIMENSAO_EMBEDDING` e renormaliza
    prompt_name: str | None = None
    encode_kwargs: dict = field(default_factory=dict)
    dtype: str = "float16"  # na GPU; o jina recomenda bfloat16
    lote: int = LOTE  # textos por lote na GPU
    trust_remote_code: bool = False


# Finalistas do bake-off (SPEC §8.4.1).
FORMATOS: dict[str, Formato] = {
    "Qwen/Qwen3-Embedding-4B": Formato(truncar=DIMENSAO_EMBEDDING, lote=16),  # 7,6 GB de pesos
    "microsoft/harrier-oss-v1-0.6b": Formato(),
    # O adaptador `text-matching` é o de similaridade texto-texto; o prompt padrão do
    # modelo ("Document: ") vale para os dois lados.
    "jinaai/jina-embeddings-v5-text-small": Formato(
        encode_kwargs={"task": "text-matching"}, dtype="bfloat16", trust_remote_code=True
    ),
}


class ModeloSentenceTransformers:
    """Um modelo do Hugging Face via sentence-transformers, em fp16 na GPU (se houver)."""

    def __init__(self, nome: str, dispositivo: str | None = None) -> None:
        import torch
        from sentence_transformers import SentenceTransformer

        if nome not in FORMATOS:
            raise ValueError(f"Modelo sem formato conhecido: {nome} (ver FORMATOS)")
        self.nome = nome
        self._formato = FORMATOS[nome]
        dispositivo = dispositivo or ("cuda" if torch.cuda.is_available() else "cpu")
        self._modelo = SentenceTransformer(
            nome,
            device=dispositivo,
            trust_remote_code=self._formato.trust_remote_code,
            truncate_dim=self._formato.truncar,
            model_kwargs={"dtype": getattr(torch, self._formato.dtype)}
            if dispositivo == "cuda"
            else {},
        )

    def codificar(self, textos: Sequence[str]) -> np.ndarray:
        kwargs = dict(self._formato.encode_kwargs)
        if self._formato.prompt_name:
            kwargs["prompt_name"] = self._formato.prompt_name
        e = self._modelo.encode(
            list(textos),
            batch_size=self._formato.lote,
            convert_to_numpy=True,
            normalize_embeddings=False,
            show_progress_bar=len(textos) > self._formato.lote,
            **kwargs,
        )
        return normalizar(np.asarray(e, dtype=np.float32))

    def liberar(self) -> None:
        """Solta o modelo e a memória da GPU (o bake-off carrega um finalista por vez)."""
        import gc

        import torch

        del self._modelo
        gc.collect()
        torch.cuda.empty_cache()


def normalizar(e: np.ndarray) -> np.ndarray:
    """Norma 1 por linha; confere a dimensão comum do bake-off."""
    if e.shape[1] != DIMENSAO_EMBEDDING:
        raise ValueError(f"Embedding com {e.shape[1]} dimensões; esperado {DIMENSAO_EMBEDDING}")
    normas = np.linalg.norm(e, axis=1, keepdims=True)
    return (e / np.where(normas == 0, 1, normas)).astype(np.float32)


def vetor_pgvector(v: np.ndarray) -> str:
    """O vetor no formato de texto do pgvector, para `CAST(:v AS vector)`."""
    return "[" + ",".join(f"{x:.6g}" for x in v) + "]"
