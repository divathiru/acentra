"""Template adapter for the LLM module."""
import json
from typing import List, Dict
from app.llm.api import LLMPort, ModelTier, LLMResponse

class TemplateAdapter(LLMPort):
    async def complete(self, messages: List[Dict[str, str]], tier: ModelTier, json_mode: bool = False, timeout: float = 8.0) -> LLMResponse:
        if json_mode:
            # Fallback JSON structure for intent understanding
            payload = {
                "kind": "unclear",
                "workflow_id": None,
                "entities": {},
                "urgency": "normal",
                "sentiment": "neutral",
                "issue_type": ""
            }
            return LLMResponse(text=json.dumps(payload), mode="template")
            
        return LLMResponse(text="[Template fallback response]", mode="template")
