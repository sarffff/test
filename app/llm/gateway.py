"""P0 LLM 网关：业务代码唯一允许调模型的地方。

职责：超时 / 重试 / 用量回传 / 场景温度预设。
不做：prompt 模板、工具调用、多模型路由（那是 P2/P5 的事）。
"""
import asyncio
import time
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.config import get_settings

# 场景温度预设：问答要稳，对话可活，规划要死（确定性）
TEMPERATURE_PRESETS = {"qa": 0.3, "chat": 0.7, "planner": 0.0}


@dataclass
class ChatResult:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0


class LLMGateway:
    def __init__(self) -> None:
        s = get_settings()
        self._model = s.llm_model
        self._timeout = s.llm_timeout
        self._max_retries = s.llm_max_retries
        self._chat_client = AsyncOpenAI(
            base_url=s.llm_base_url, api_key=s.llm_api_key, timeout=s.llm_timeout
        )
        emb_base = s.embedding_base_url or s.llm_base_url
        emb_key = s.embedding_api_key or s.llm_api_key
        self._emb_client = AsyncOpenAI(base_url=emb_base, api_key=emb_key, timeout=s.llm_timeout)
        self._emb_model = s.embedding_model

    @property
    def model(self) -> str:
        return self._model

    async def _sleep_backoff(self, attempt: int) -> None:
        await asyncio.sleep(2**attempt)  # 2s、4s

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> ChatResult:
        """非流式对话，失败自动重试。"""
        last_err: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            t0 = time.perf_counter()
            try:
                resp = await self._chat_client.chat.completions.create(
                    model=self._model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                msg = resp.choices[0].message.content or ""
                usage = resp.usage
                return ChatResult(
                    content=msg.strip(),
                    model=self._model,
                    prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                    total_tokens=getattr(usage, "total_tokens", 0) or 0,
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
            except Exception as e:  # 超时 / 限流 / 5xx 统一重试
                last_err = e
                if attempt < self._max_retries:
                    await self._sleep_backoff(attempt)
        raise RuntimeError(f"LLM 调用失败（重试 {self._max_retries} 次）：{last_err}")

    async def chat_stream(self, messages: list[dict], temperature: float = 0.3):
        """流式对话：逐块 yield 文本，调用方拼 SSE。"""
        resp = await self._chat_client.chat.completions.create(
            model=self._model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            stream=True,
        )
        async for chunk in resp:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """向量化（P3 检索用，P0 先备好接口）。"""
        if not texts:
            return []
        resp = await self._emb_client.embeddings.create(model=self._emb_model, input=texts)
        return [d.embedding for d in resp.data]


_gateway: LLMGateway | None = None


def get_gateway() -> LLMGateway:
    """单例：整进程复用连接池。"""
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
