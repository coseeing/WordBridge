FROM python:3.14-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# requirements.txt is compiled with hashes from requirements.in (see there).
# uv is mounted for this step only, so it does not stay in the image; it
# checks every hash, and --require-hashes also rejects an entry without one.
# install (not sync) puts in exactly the locked, hash-checked set and never
# uninstalls anything, so the image's own pip stays whatever the base image
# holds (decided by the user, 2026-11-07).
# --mount needs BuildKit (the default builder in current Docker).
COPY requirements.txt ./
RUN --mount=from=ghcr.io/astral-sh/uv:0.13.5,source=/uv,target=/bin/uv \
    uv pip install --system --require-hashes --no-cache -r requirements.txt

RUN groupadd --system --gid 10001 app && \
    useradd --system --uid 10001 --gid app --create-home --home-dir /home/app app

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

USER app

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
