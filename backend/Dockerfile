FROM ghcr.io/astral-sh/uv:0.12.7 AS uv
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PATH="/app/backend/.venv/bin:$PATH" \
    SERVICE_HOST=0.0.0.0 \
    SERVICE_PORT=8000

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app/backend

# 의존성 선언이 같으면 설치 계층을 재사용하고 소스만 다시 복사한다.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

RUN useradd --create-home --uid 10001 app
COPY --chown=app:app backend/ ./
USER app

EXPOSE 8000
CMD ["python", "serve.py"]
