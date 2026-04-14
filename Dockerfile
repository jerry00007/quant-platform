# ==============================
# QuantWeave 量化交易平台 - 多阶段构建
# ==============================
FROM python:3.11-slim AS base

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安装 Python 依赖
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- 开发阶段 ----
FROM base AS development
COPY backend/ .
COPY frontend/ /app/frontend/
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---- 生产阶段 ----
FROM base AS production
COPY backend/ .
COPY frontend/ /app/frontend/

# 创建非 root 用户
RUN useradd -m -s /bin/bash quantweave && \
    mkdir -p /app/exports /app/logs /app/data_cache && \
    chown -R quantweave:quantweave /app

USER quantweave

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/system/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
