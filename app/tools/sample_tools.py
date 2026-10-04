"""
3 个标准样板工具：get_time、http_fetch、echo
"""

from datetime import datetime, timezone as dt_timezone
from typing import Optional
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field, HttpUrl
import httpx
from app.tools.registry import registry


# ==================== Tool 1: get_time ====================

class GetTimeArgs(BaseModel):
    timezone: str = Field(
        default="Asia/Shanghai",
        description="IANA 时区名称，例如 'Asia/Shanghai', 'UTC', 'America/New_York'。",
    )

GET_TIME_DESCRIPTION = """
获取指定时区的当前系统时间和日期。
- 适用场景：需要获取当前时间、计算相对日期、确定今天星期几。
- 正确示例：{"timezone": "Asia/Shanghai"}
- 错误反例：不要用该工具进行通用数学计算或推算未来无规律节假日。
""".strip()

@registry.register(
    name="get_time",
    description=GET_TIME_DESCRIPTION,
    args_schema=GetTimeArgs,
    timeout_seconds=3.0,
)
async def get_time(timezone: str = "Asia/Shanghai") -> str:
    try:
        tz = ZoneInfo(timezone)
        now = datetime.now(tz)
        return now.strftime(f"%Y-%m-%d %H:%M:%S %Z ({timezone})")
    except Exception:
        # 使用 Python 内置的 UTC 兜底，绝不在 Windows 上抛 ZoneInfoNotFoundError
        now = datetime.now(dt_timezone.utc)
        return now.strftime("%Y-%m-%d %H:%M:%S UTC (fallback)")


# ==================== Tool 2: http_fetch ====================

class HttpFetchArgs(BaseModel):
    url: HttpUrl = Field(description="需要请求的目标 HTTP/HTTPS URL 地址。")
    max_length: int = Field(default=3000, description="返回内容最大截断字符数，防止上下文爆炸。")

HTTP_FETCH_DESCRIPTION = """
发送 HTTP GET 请求获取网页或接口的纯文本内容。
- 适用场景：读取指定公开 API、抓取轻量文本或 JSON 数据。
- 正确示例：{"url": "https://api.github.com/zen", "max_length": 1000}
- 错误反例：禁止访问内网 IP（如 127.0.0.1、192.168.x.x）或请求包含二进制文件（如 zip、exe）。
""".strip()

@registry.register(
    name="http_fetch",
    description=HTTP_FETCH_DESCRIPTION,
    args_schema=HttpFetchArgs,
    timeout_seconds=10.0,
)
async def http_fetch(url: HttpUrl, max_length: int = 3000) -> str:
    url_str = str(url)
    # 简易 SSRF 基础防护
    if any(h in url_str for h in ["localhost", "127.0.0.1", "0.0.0.0"]):
        raise ValueError("Fetching internal/localhost addresses is prohibited.")

    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
        response = await client.get(url_str, headers={"User-Agent": "AgentBackend-MCP/1.0"})
        response.raise_for_status()
        text = response.text
        if len(text) > max_length:
            text = text[:max_length] + f"\n... [Truncated: exceeded {max_length} characters]"
        return text


# ==================== Tool 3: echo ====================

class EchoArgs(BaseModel):
    message: str = Field(description="需要原样返回的输入文本。")
    prefix: Optional[str] = Field(default=None, description="可选前缀修饰。")

ECHO_DESCRIPTION = """
原样回显输入的测试工具。
- 适用场景：链路健康检查、MCP 协议握手回环测试、验证参数序列化完整性。
- 正确示例：{"message": "ping"}
""".strip()

@registry.register(
    name="echo",
    description=ECHO_DESCRIPTION,
    args_schema=EchoArgs,
    timeout_seconds=2.0,
)
async def echo(message: str, prefix: Optional[str] = None) -> str:
    if prefix:
        return f"{prefix}: {message}"
    return message
