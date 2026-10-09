"""Public interface for LLM module."""
import abc
from enum import Enum
from typing import List, Dict
from pydantic import BaseModel

class ModelTier(str, Enum):
    PRIMARY = "primary"
    FAST = "fast"

class LLMResponse(BaseModel):
    text: str
    mode: str  # 'llm' or 'template'

class LLMPort(abc.ABC):
    @abc.abstractmethod
    async def complete(self, messages: List[Dict[str, str]], tier: ModelTier, json_mode: bool = False, timeout: float = 8.0) -> LLMResponse:
        pass

def get_llm(session) -> LLMPort:
    from sqlalchemy import select
    from app.core.models import SystemSetting
    from app.core.config import get_settings
    from app.llm.mistral import MistralAdapter
    from app.llm.template import TemplateAdapter

    kill_switch = session.execute(
        select(SystemSetting.value).where(SystemSetting.key == 'llm_enabled')
    ).scalar_one_or_none()
    
    is_enabled = True
    if kill_switch is not None and kill_switch.lower() == 'false':
        is_enabled = False
        
    settings = get_settings()
    if settings.LLM_PROVIDER == 'template' or not is_enabled:
        return TemplateAdapter()
        
    return MistralAdapter()
