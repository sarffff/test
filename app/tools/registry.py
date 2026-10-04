"""
MCP 与 OpenAI 双兼容的工具注册表与安全执行器
"""
import asyncio
import inspect
from typing import Any, Callable, Coroutine, Dict, List, Optional, Type
from pydantic import BaseModel, ValidationError, create_model

class ToolResult(BaseModel):
    success: bool
    output: Optional[Any] = None
    error_message: Optional[str] = None

    def to_mcp_content(self) -> Dict[str,Any]:
        """序列化为mcp tools/call响应格式"""
        text = str(self.output) if self.success else f"Error: {self.error_message}"
        return {
            "content": [
                {
                    "type": "text",
                    "text":text
                }
            ],
            "isError": not self.success
        }

class Tool:
    """标准Tool对象"""

    def __init__(
        self,
        name:str,                                                                   #工具名称
        handler:Callable[...,Coroutine[Any, Any, ToolResult]],                       #工具执行器
        description: str,                                                           #工具描述
        args_schema: Type[BaseModel],                                                  #参数校验模型
        timeout_seconds: float = 15.0                                               #超时时间
    ):
      self.name = name
      self.handler = handler
      self.description = description
      self.args_schema = args_schema
      self.timeout_seconds = timeout_seconds

    def to_mcp_spec(self) -> Dict[str,Any]:
        """导出为Mcp tools/list规范"""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.args_schema.model_json_schema() #Pydantic转openapi schema
        }
      
    def to_openai_spec(self) -> Dict[str,Any]:
        """导出为 OpenAI Function Call 规范（供 P2 ReAct 循环使用）"""
        return {
            "type":"function",
            "function":{
                "name":self.name,
                "description":self.description,
                "parameters":self.args_schema.model_json_schema()
            }
        }
    
    async def execute(self, arguments: Dict[str,Any]) -> ToolResult:
        """
        沙箱执行：参数校验 -> 超时控制 -> 面向 LLM 的结构化错误捕获
        """
        #参数校验
        try:
            validated_args = self.args_schema.model_validate(arguments)
        except ValidationError as ve:
            # 格式化校验失败原因，引导 LLM 纠正入参
            err_details = [f"Field '{e['loc'][0]}': {e['msg']}" for e in ve.errors()]
            return ToolResult(
                success=False,
                output=None,
                error_message=f"Invalid arguments for tool '{self.name}': {'; '.join(err_details)}. Please check the parameter schema and try again.",
            )

        #超时与执行异常控制
        try:
            coro = self.handler(**validated_args.model_dump())  # Pydantic 模型转 dict
            result = await asyncio.wait_for(
                coro,
                timeout=self.timeout_seconds,
            )    
            return ToolResult(success=True, output=result)
        except TimeoutError:
            return ToolResult(
                success=False,
                output=None,
                error_message=f"Tool '{self.name}' timed out after {self.timeout_seconds}s.",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output=None,
                error_message=f"Execution error in tool `{self.name}`: {str(e)}",
            )
        

class ToolRegistry:
    """全局工具注册表单例"""
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        args_schema: Optional[Type[BaseModel]] = None,
        timeout_seconds: float = 15.0,
    ):
        """装饰器：注册一个异步工具函数"""
        def decorator(func: Callable[..., Coroutine[Any, Any, Any]]):
            tool_name = name or func.__name__
            tool_desc = (description or func.__doc__ or "").strip()
            schema = args_schema
            if schema is None:
                # 若未显式传入 BaseModel，通过函数参数类型注解自动构造 Pydantic Schema
                fields = {}
                sig = inspect.signature(func)
                for param_name, param in sig.parameters.items():
                    if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                        continue
                    annotation = param.default if param.annotation == inspect.Parameter.empty else param.annotation
                    default = ... if param.default == inspect.Parameter.empty else param.default
                    fields[param_name] = (annotation if annotation != inspect.Parameter.empty else Any, default)
                schema = create_model(f"{tool_name}_Args", **fields)
            tool = Tool(
                name=tool_name,
                description=tool_desc,
                args_schema=schema,
                handler=func,
                timeout_seconds=timeout_seconds,
            )
            self._tools[tool_name] = tool
            return func
        return decorator
        
    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        return list(self._tools.values())

    def to_mcp_tools(self) -> List[Dict[str, Any]]:
        return [tool.to_mcp_spec() for tool in self._tools.values()]

    def to_openai_tools(self) -> List[Dict[str, Any]]:
        return [tool.to_openai_spec() for tool in self._tools.values()]

# 全局单例
registry = ToolRegistry()

    
      