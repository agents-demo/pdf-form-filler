"""LLM access built on the openJiuwen agent-core foundation.

Wraps ``openjiuwen.core.foundation.llm.Model`` (the library's unified LLM
invocation layer) so the rest of the application never talks to a provider
SDK directly. Text and multimodal (image) calls are both supported.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Optional

from openjiuwen.core.foundation.llm import (
    Model,
    ModelClientConfig,
    ModelRequestConfig,
)

from .config import LLMConfig, ensure_direct_connection
from .logging_setup import mask_key

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Raised when the LLM cannot produce a usable result."""


class LLMService:
    """A thin, lazily-initialized wrapper around an openJiuwen ``Model``."""

    def __init__(self, config: LLMConfig):
        if not config.api_key.strip():
            raise LLMError(
                "No API key configured. Set DEEPSEEK_API_KEY in .env or the "
                "settings dialog."
            )
        self.config = config
        self._model: Optional[Model] = None
        # The connection is always direct: clear inherited proxy env vars
        # before the HTTP client is created.
        ensure_direct_connection()

    @property
    def model(self) -> Model:
        if self._model is None:
            client = ModelClientConfig(
                client_provider=self.config.provider,
                api_key=self.config.api_key,
                api_base=self.config.api_base,
                verify_ssl=self.config.verify_ssl,
                timeout=self.config.timeout,
            )
            request = ModelRequestConfig(
                model=self.config.model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
            self._model = Model(
                model_client_config=client,
                model_config=request,
            )
        return self._model

    async def complete(
        self,
        system: str,
        user: str,
        images: Optional[list[bytes]] = None,
    ) -> str:
        """Send a (possibly multimodal) completion and return the text."""
        messages: list[dict] = [{"role": "system", "content": system}]
        image_bytes = sum(len(img) for img in (images or []))
        log.debug(
            "LLM request: provider=%s model=%s base=%s key=%s images=%d "
            "image_bytes=%d system_len=%d user_len=%d timeout=%ss",
            self.config.provider,
            self.config.model,
            self.config.api_base,
            mask_key(self.config.api_key),
            len(images or []),
            image_bytes,
            len(system),
            len(user),
            self.config.timeout,
        )
        if images:
            parts: list[dict] = [{"type": "text", "text": user}]
            for img in images:
                encoded = base64.b64encode(img).decode("ascii")
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{encoded}"},
                    }
                )
            messages.append({"role": "user", "content": parts})
        else:
            messages.append({"role": "user", "content": user})

        try:
            result = await self.model.invoke(messages)
        except BaseException:
            log.exception(
                "LLM invoke failed (provider=%s model=%s base=%s)",
                self.config.provider,
                self.config.model,
                self.config.api_base,
            )
            raise
        return result.content or ""


def extract_json(text: str) -> dict:
    """Extract a JSON object from a (possibly fenced) LLM response."""
    text = text.strip()
    # Strip ```json ... ``` fences if present.
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to the first balanced {...} block.
    start = text.find("{")
    if start == -1:
        raise LLMError(f"LLM did not return JSON: {text[:300]!r}")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError as exc:
                    raise LLMError(f"Invalid JSON from LLM: {exc}") from exc
    raise LLMError("Unbalanced JSON from LLM response")
