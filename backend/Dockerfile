FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen

COPY backend /app/backend

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8001

ENTRYPOINT ["/app/backend/entrypoint.sh"]

