FROM python:3.14-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# requirements.txt is compiled with hashes from requirements.in (see there).
# uv is mounted for this step only, so it does not stay in the image; it
# checks every hash, and --require-hashes also rejects an entry without one.
# sync removes every installed package the list does not name, except pip,
# which stays for operators (python -m pip list).
# --mount needs BuildKit (the default builder in current Docker).
COPY requirements.txt ./
RUN --mount=from=ghcr.io/astral-sh/uv:0.13.5,source=/uv,target=/bin/uv \
    uv pip sync --system --require-hashes --no-cache requirements.txt

RUN groupadd --system --gid 10001 app && \
    useradd --system --uid 10001 --gid app --create-home --home-dir /home/app app

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

USER app

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
