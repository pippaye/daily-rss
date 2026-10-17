# ==============================================================================
# 阶段 1: 构建阶段 (Builder)
# 负责在 /app 路径下安装依赖并打包生产环境的 .venv 虚拟环境
# ==============================================================================
FROM python:3.12-slim-bookworm AS builder

# 安装临时构建工具 uv
RUN pip install --no-cache-dir uv

WORKDIR /app

# 利用层缓存：先安装第三方依赖到 /app/.venv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# 复制源码并完成项目自身打包安装（生成 /app/.venv/bin/daily-rss）
COPY README.md ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev

# ==============================================================================
# 阶段 2: 纯净运行阶段 (Runner)
# 生产镜像中没有任何 uv、pip 等构建工具，仅保留 Python 运行时与虚拟环境
# ==============================================================================
FROM python:3.12-slim-bookworm AS runner

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# 安装必要的基础依赖（时区支持与 SSL 根证书）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 从构建阶段仅仅复制虚拟环境与代码
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# 创建持久化挂载目录
RUN mkdir -p /app/data /app/reports

VOLUME ["/app/data", "/app/reports"]

# 直接运行 Python 原生入口命令，彻底脱离 uv 依赖
CMD ["daily-rss", "daemon"]
