# 多阶段构建：减少最终镜像体积
# 面试考点：为什么用多阶段构建？答：分离编译环境和运行环境，减少镜像体积和攻击面

# 阶段1：依赖安装
FROM python:3.11-slim as builder

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# 阶段2：运行环境
FROM python:3.11-slim

WORKDIR /app

# 只复制已安装的依赖（从 builder 阶段）
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# 复制应用代码
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# 暴露端口
EXPOSE 8000

# 生产环境用 uvicorn 直接启动（不用 reload）
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
