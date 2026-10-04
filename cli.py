import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from app.llm.gateway import chat

async def main():
    print("=" * 10)
    print(f"🔗 模型: {os.getenv('LLM_MODEL', 'Unknown Model')}")
    print(f" 提示: 输入 'exit' 或 'quit' 退出")
    print("=" * 10)
    
    hist=[]
    while True:
        q=input("\n你: ").strip()
        if q in ("exit","quit"): break
        hist.append({"role":"user","content":q})
        out=await chat(hist, scene="chat")
        print(f"\nAI: {out['content']}")
        hist.append({"role":"assistant","content":out['content']})
asyncio.run(main())
