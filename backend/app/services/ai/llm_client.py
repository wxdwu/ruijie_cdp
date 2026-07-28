"""
统一的 LLM 调用封装，供各 service 复用，避免散落多处重复实现。

设计要点：
- 读取 app.config.settings 中的 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL_NAME（默认模型 ray 智能推荐(默认)）
- 仅暴露 chat_completion()，失败时返回 None 并由调用方降级，不抛异常
- 构造时可传入 api_key / base_url 覆盖默认值（兼容去重等独立配置场景）
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx
from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# 默认 AI 模型（可在 .env 中通过 LLM_MODEL_NAME 覆盖，兜底取 settings.LLM_MODEL_NAME）
DEFAULT_MODEL_NAME = settings.LLM_MODEL_NAME


class LLMClient:
    """LLM 调用抽象封装，所有 AI 模型调用通过此类进行。"""

    def __init__(
        self,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.model_name = model_name or DEFAULT_MODEL_NAME
        # 显式传入 httpx.Client 以绕过 openai 1.47 + httpx 0.28 的 proxies 参数兼容 bug
        self._client = OpenAI(
            api_key=api_key or settings.LLM_API_KEY,
            base_url=base_url or settings.LLM_BASE_URL,
            http_client=httpx.Client(),
        )

    @property
    def is_available(self) -> bool:
        """检查 LLM 是否已配置。"""
        return bool(self._client.api_key and self._client.base_url)

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 800,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        调用 LLM 完成对话。

        Args:
            messages: 对话消息列表
            temperature: 温度参数
            max_tokens: 最大 token 数
            response_format: 输出格式（如 {"type": "json_object"}）

        Returns:
            LLM 返回的文本内容，失败返回 None
        """
        if not self.is_available:
            logger.warning("LLM 未配置，跳过 AI 调用")
            return None

        try:
            kwargs: Dict[str, Any] = {
                "model": self.model_name,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if response_format:
                kwargs["response_format"] = response_format

            response = self._client.chat.completions.create(**kwargs)
            return response.choices[0].message.content

        except Exception as e:
            logger.warning("LLM 调用失败: %s", e)
            return None
