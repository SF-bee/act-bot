# syntax=docker/dockerfile:1
# ACT Bot 业务层镜像（协议端 NapCat 是独立容器，见同目录 docker-compose.yml）
#
# 构建（在仓库根执行）：
#   docker build -f deploy/docker/Dockerfile -t act-bot:local .
# 约定：本文件不含任何 QQ 号 / 凭据 / 机器绝对路径；凭据全部经 .env 注入。
FROM python:3.13-slim

# uv 官方推荐：直接从发行镜像复制二进制（无需 pip 安装）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 先只复制依赖描述文件，最大化层缓存
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

# 再复制业务代码（.dockerignore 已排除 .venv / data / .env 等）
COPY . .

# 数据目录：compose 中挂卷持久化；SQLite 不要放网络盘 / 网盘同步目录
ENV ACTBOT_DATA_DIR=/app/data
VOLUME ["/app/data"]

EXPOSE 8080

# 健康检查：TCP 探活 8080（不依赖 curl / wget，保持镜像精简）
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8080), 3).close()"

CMD ["python", "bot.py"]
