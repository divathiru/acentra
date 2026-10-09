"""Embedder implementations."""
import abc
import asyncio
import hashlib
import structlog
import httpx
from typing import List
from app.core.config import get_settings

logger = structlog.get_logger(__name__)

class EmbedPort(abc.ABC):
    @abc.abstractmethod
    async def embed(self, texts: List[str]) -> List[List[float]]:
        pass

class MistralEmbedder(EmbedPort):
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = httpx.AsyncClient(timeout=30.0)
        self.model = self.settings.MISTRAL_EMBED_MODEL
        self.api_key = self.settings.MISTRAL_API_KEY
    
    async def embed(self, texts: List[str]) -> List[List[float]]:
        import random
        from httpx import HTTPStatusError
        
        batch_size = 32
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            try:
                response = await self.client.post(
                    "https://api.mistral.ai/v1/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "input": batch},
                )
                response.raise_for_status()
                data = response.json()
                batch_emb = [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
                all_embeddings.extend(batch_emb)
            except Exception as e:
                logger.warning("Mistral embedding unavailable/rate-limited, using FakeEmbedder fallback", error=str(e))
                fake_emb = await FakeEmbedder().embed(batch)
                all_embeddings.extend(fake_emb)
        return all_embeddings

class FakeEmbedder(EmbedPort):
    def __init__(self) -> None:
        self.dim = get_settings().EMBED_DIM
    
    async def embed(self, texts: List[str]) -> List[List[float]]:
        res = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            emb = [(float(b) / 255.0) - 0.5 for b in h[:min(len(h), self.dim)]]
            while len(emb) < self.dim:
                emb.extend(emb[:self.dim - len(emb)])
            emb = emb[:self.dim]
            norm = sum(x*x for x in emb) ** 0.5
            if norm > 0:
                emb = [x/norm for x in emb]
            res.append(emb)
        return res
