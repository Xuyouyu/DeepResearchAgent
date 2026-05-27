"""
LLM 客户端封装
支持多厂商 API（Moonshot/智谱/OpenAI 兼容格式）
关键设计：统一接口，方便切换模型；支持异步流式输出
"""
import httpx
import json
from typing import AsyncIterator, Optional, List, Dict, Any
from backend.core.config import get_settings


class LLMClient:
    """
    大模型调用客户端
    为什么不直接用 openai 包？因为我们要展示自己封装 HTTP 请求的能力，
    且更容易控制重试、日志、多厂商适配等细节。
    """

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.LLM_API_KEY
        self.base_url = settings.LLM_BASE_URL.rstrip("/")
        self.model = settings.LLM_MODEL
        self.client = httpx.AsyncClient(timeout=60.0)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        stream: bool = False
    ) -> str:
        """
        非流式对话接口
        temperature 设低（0.3）保证 Agent 决策稳定，不易发散
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        try:
            response = await self.client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            error_body = e.response.text
            raise RuntimeError(f"LLM API 错误: {error_body}") from e
        except Exception as e:
            raise RuntimeError(f"LLM 请求异常: {str(e)}") from e

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3
    ) -> AsyncIterator[str]:
        """
        流式对话接口（SSE 用）
        面试常考点：流式输出如何减少用户等待时间？
        答：首字延迟（TTFT）远小于整段生成时间，用户感知更快
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True
        }

        async with self.client.stream(
            "POST", url, headers=headers, json=payload, timeout=120.0
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    async def close(self):
        await self.client.aclose()


# 全局单例，避免重复创建 HTTP 连接池
_llm_client: Optional[LLMClient] = None


async def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
