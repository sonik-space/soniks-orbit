FROM python:3.12.11-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.9.13 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ENV UV_PROJECT_ENVIRONMENT=/usr/local

# Корень импортов плоский: `from domain...`, а не `from src....`
ENV PYTHONPATH=/app/src

# UID пользователя, от которого запускается целевой процесс. Выбираем подальше,
# чтобы не было коллизии с существующими на хосте пользователями.
ARG uid=5055
ARG WORKDIR=/app

WORKDIR $WORKDIR

# если зависимости менялись, обновление образа начнётся с этого слоя
COPY pyproject.toml uv.lock alembic.ini ./

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Кеш водопадов: файлы неизменяемы, без кеша нагрузка на S3 избыточна
# (decisions/009).
RUN mkdir -p /var/cache/soniks-orbit/waterfalls && \
    chown -R $uid:$uid /var/cache/soniks-orbit

COPY src ./src/

USER $uid
