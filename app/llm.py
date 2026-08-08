"""Optional OpenAI-compatible JSON client.

AI is deliberately opt-in.  Without ``AI_ENABLED=1`` or a key, the workflow
uses deterministic checks and remains fully usable for ingest and drafts.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from .config import Settings


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings: Settings):
        if not settings.llm_api_key:
            raise LLMError("未配置 LLM_API_KEY")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LLMError("未安装 openai，无法启用 AI") from exc
        self.settings = settings
        self.client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
        )

    def chat_json(self, prompt: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(max(1, self.settings.llm_request_retries)):
            try:
                kwargs: dict[str, Any] = {
                    "model": self.settings.llm_model,
                    "messages": [
                        {"role": "system", "content": "只输出合法 JSON，不要 Markdown。"},
                        {"role": "user", "content": prompt},
                    ],
                }
                if not self.settings.llm_model.lower().startswith("gpt-5"):
                    kwargs["temperature"] = 0.1
                response = self.client.chat.completions.create(**kwargs)
                raw = response.choices[0].message.content or ""
                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                return json.loads(match.group(0) if match else raw)
            except Exception as exc:
                last_error = exc
                if attempt < self.settings.llm_request_retries - 1:
                    time.sleep(2 ** attempt)
        raise LLMError(f"AI 请求失败: {str(last_error)[:500]}") from last_error

