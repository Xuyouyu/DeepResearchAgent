"""
FastAPI 主入口
提供 REST API 和 SSE 流式接口

面试考点：为什么选 FastAPI 而不是 Flask/Django？
答：FastAPI 原生支持异步（async/await），基于 Starlette 和 Pydantic，
    自动 API 文档（Swagger/ReDoc），类型提示友好，性能接近 Go/Node.js
"""
import json
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.models.schemas import ResearchRequest, ResearchReport, ResearchStatus
from backend.agent.react_loop import ReActResearchAgent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    启动时预加载资源，关闭时清理连接
    """
    print("🚀 DeepResearchAgent 启动中...")
    yield
    print("🛑 DeepResearchAgent 已关闭")


app = FastAPI(
    title="DeepResearchAgent",
    description="基于 ReAct 架构的深度调研 Agent，支持自适应规划、冲突检测与溯源报告",
    version="1.0.0",
    lifespan=lifespan
)

# CORS：允许前端（localhost 或任意域名）访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health_check():
    """健康检查端点，部署监控用"""
    return {"status": "ok", "service": "deep-research-agent"}


@app.post("/api/research", response_model=ResearchReport)
async def create_research(request: ResearchRequest):
    """
    非流式调研接口
    适合后台任务或不需要实时看进度的场景
    响应时间：30s - 120s（取决于深度）
    """
    task_id = str(uuid.uuid4())[:8]
    agent = ReActResearchAgent()

    try:
        report = await agent.run(request, task_id=task_id)
        if report.status == ResearchStatus.FAILED:
            raise HTTPException(status_code=500, detail=report.content)
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/research/stream")
async def create_research_stream(request: ResearchRequest):
    """
    流式调研接口（SSE）
    前端通过 EventSource 接收实时进度
    Content-Type: text/event-stream

    面试考点：SSE 的数据格式是什么样的？
    答：每条消息以 "data: {...}\n\n" 格式发送，浏览器 EventSource 自动解析
    """
    task_id = str(uuid.uuid4())[:8]
    agent = ReActResearchAgent()

    async def event_generator():
        try:
            async for update in agent.run_stream(request, task_id=task_id):
                # SSE 格式要求 data: 开头，两个换行结束
                yield f"data: {json.dumps(update.model_dump(), default=str, ensure_ascii=False)}\n\n"
        except Exception as e:
            error_data = {"status": "failed", "message": str(e), "task_id": task_id}
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # 禁用 Nginx 缓冲，确保实时推送
        }
    )


# 挂载前端静态文件（如果前端构建为静态文件）
# 开发时前端用 Live Server 单独跑，这里预留
import os
frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(os.path.join(frontend_path, "index.html")):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    # 开发模式：hot reload；生产用 gunicorn + uvicorn.workers.UvicornWorker
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
