"""Mistral adapter with circuit breaker and retry logic."""
import time
import asyncio
import random
import httpx
import structlog
from typing import List, Dict

from app.llm.api import LLMPort, ModelTier, LLMResponse
from app.core.config import get_settings
from app.llm.template import TemplateAdapter

logger = structlog.get_logger(__name__)

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = 0.0

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()

    def record_success(self):
        self.failures = 0

    def is_open(self) -> bool:
        if self.failures >= self.failure_threshold:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                return False
            return True
        return False

# Global circuit breaker
circuit_breaker = CircuitBreaker()

class MistralAdapter(LLMPort):
    def __init__(self):
        self.settings = get_settings()
        self.client = httpx.AsyncClient()
        self.template_fallback = TemplateAdapter()

    async def complete(self, messages: List[Dict[str, str]], tier: ModelTier, json_mode: bool = False, timeout: float = 8.0) -> LLMResponse:
        if circuit_breaker.is_open():
            logger.warning("Circuit breaker is open. Using template adapter.")
            return await self.template_fallback.complete(messages, tier, json_mode, timeout)
            
        model = self.settings.MISTRAL_CHAT_MODEL if tier == ModelTier.PRIMARY else self.settings.MISTRAL_FAST_MODEL
        
        payload = {
            "model": model,
            "messages": messages,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
            
        retries = 2
        for attempt in range(retries + 1):
            try:
                # Sanitize logged prompts to never log raw identifiers. We just don't log the prompt content.
                response = await self.client.post(
                    self.settings.MISTRAL_BASE_URL + "/chat/completions",
                    headers={"Authorization": f"Bearer {self.settings.MISTRAL_API_KEY}"},
                    json=payload,
                    timeout=timeout
                )
                
                if response.status_code == 429 or (500 <= response.status_code < 600):
                    if attempt < retries:
                        sleep_time = (2 ** attempt) + random.uniform(0, 1)
                        logger.warning("Mistral transient error", status_code=response.status_code, attempt=attempt)
                        await asyncio.sleep(sleep_time)
                        continue
                        
                response.raise_for_status()
                data = response.json()
                
                circuit_breaker.record_success()
                
                return LLMResponse(
                    text=data["choices"][0]["message"]["content"],
                    mode="llm"
                )
                
            except httpx.HTTPStatusError as e:
                # We already handled 429 and 5xx. If we reach here, it's either unrecoverable (4xx) or max retries reached.
                if e.response.status_code == 429 or (500 <= e.response.status_code < 600):
                    if attempt < retries:
                        sleep_time = (2 ** attempt) + random.uniform(0, 1)
                        await asyncio.sleep(sleep_time)
                        continue
                circuit_breaker.record_failure()
                logger.error("Mistral unrecoverable error", error=str(e))
                return await self.template_fallback.complete(messages, tier, json_mode, timeout)
            except Exception as e:
                circuit_breaker.record_failure()
                logger.error("Mistral exception", error=str(e))
                return await self.template_fallback.complete(messages, tier, json_mode, timeout)
                
        circuit_breaker.record_failure()
        return await self.template_fallback.complete(messages, tier, json_mode, timeout)
