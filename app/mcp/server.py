"""
暴露标准 MCP (Model Context Protocol) JSON-RPC 接口
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.tools.registry import registry

mcp_router = APIRouter(prefix="/mcp",tags=["MCP-Tools"])

# MCP标准JSON-RPC请求体
class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Any] = None
    method: str
    params: Optional[Dict[str, Any]] = None



@mcp_router.post("")
async def handle_mcp_jsonrpc(request: JsonRpcRequest):
    """
    处理标准 MCP JSON-RPC 请求：
    - tools/list: 列出所有可用工具及 JSON Schema
    - tools/call: 执行指定工具并返回 MCP 格式内容
    """
    method = request.method
    params = request.params or {}
        # 0. 协议握手
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request.id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": False}
                },
                "serverInfo": {
                    "name": "agent-backend-mcp",
                    "version": "0.1.0"
                }
            }
        }
    elif method == "notifications/initialized":
        # 客户端确认就绪通知，无需返回响应
        return {"jsonrpc": "2.0", "result": {}}

    # 1. 处理 tools/list
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request.id,
            "result": {
                "tools": registry.to_mcp_tools()
            },
        }
    # 2. 处理 tools/call
    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if not tool_name:
            return {
                "jsonrpc": "2.0",
                "id": request.id,
                "error": {"code": -32602, "message": "Missing tool 'name' in params."},
            }
        tool = registry.get(tool_name)
        if not tool:
            return {
                "jsonrpc": "2.0",
                "id": request.id,
                "error": {"code": -32601, "message": f"Tool '{tool_name}' not found."},
            }
        # 沙箱调用工具
        result = await tool.execute(arguments)
        return {
            "jsonrpc": "2.0",
            "id": request.id,
            "result": result.to_mcp_content(),
        }
    # 3. 处理不支持的方法
    return {
        "jsonrpc": "2.0",
        "id": request.id,
        "error": {"code": -32601, "message": f"Unsupported MCP method: '{method}'."},
    }