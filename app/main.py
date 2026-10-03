import uuid, time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.config import get_settings
from app.llm import gateway

settings = get_settings()
app = FastAPI(title=settings.AGENT_NAME, version=settings.VERSION)

@app.middleware("http")
async def add_trace(request: Request, call_next):
    trace_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
    t0 = time.perf_counter()
    resp = await call_next(request)
    resp.headers["X-Request-ID"] = trace_id
    resp.headers["X-Cost-Ms"] = str(int((time.perf_counter()-t0)*1000))
    return resp

class chatRequest(BaseModel):
    message: str
    scene: str = 'chat' # 'chat' | 'plan' | 'qa'

@app.get("/api/health")
async def health():
    return { "status": "ok" , "model" : settings.LLM_MODEL }

@app.post("/api/chat")
async def chat(req: chatRequest):
    if not req.message.strip():
        return JSONResponse({"error": "message empty"}, status_code=400)
    out = await gateway.chat(
        [{"role": "user", "content": req.message}],
        scene=req.scene,
    )
    return {"answer": out["content"], "usage": out["usage"]}

# SSE预留给P2的ReAct思考链，P0先跑通took透
@app.post("/api/chat/stream")
async def chat_stream(req: chatRequest):
    async def gen():
        out = await gateway.chat([{"role": "user", "content": req.message}])
        yield {"event": "answer", "data": out["content"]}
        yield {"event": "done", "data": "[DONE]"}
    return EventSourceResponse(gen())
