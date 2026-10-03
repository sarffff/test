import time
import logging
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from app.config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()

#单例client
_client = AsyncOpenAI(
  base_url=settings.LLM_BASE_URL,
  api_key=settings.LLM_API_KEY,
  timeout=settings.LLM_TIMEOUT
)

# 温度分场景：问答要稳，对话可活，规划要确定
TEMPS = {
  'qa': 0.3,
  'chat': 0.7,
  'plan': 0
}

async def chat(messages: list[ChatCompletionMessageParam], scene: str = 'chat', model: str| None = None)-> dict:
  """统一出口：重试+计时+用量打点，后面所有Agent都走这里。"""
  model = model or settings.LLM_MODEL
  last_err = None | BaseException
  for attempt in (1,2,3):
    t0 = time.perf_counter()
    try:
      resp = await _client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=TEMPS[scene]
      )
      cost_time = int((time.perf_counter() - t0) * 1000)
      usage = resp.usage
      log.info(
          "llm_ok model=%s scene=%s ms=%d prompt=%s completion=%s",
          model, scene, cost_time,
          getattr(usage, "prompt_tokens", 0),
          getattr(usage, "completion_tokens", 0),
      )
      return {
        "content": resp.choices[0].message.content,
        "usage": usage.model_dump() if usage else {},
        "cost_time":cost_time
      }
    except Exception as e:
      last_err = e
      log.warning("llm_retry attempt=%d, err=%s",attempt, e)
      await __import__("asyncio").sleep(2 ** attempt)

  raise last_err
