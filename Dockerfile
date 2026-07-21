FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
        chrony \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY config ./config
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

RUN useradd --create-home polybot && mkdir -p /app/data && chown -R polybot:polybot /app
USER polybot

EXPOSE 9109

ENTRYPOINT ["polybot"]
CMD ["run", "--mode", "observe", "--no-tui"]
