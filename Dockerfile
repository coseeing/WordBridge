FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        python3.14 \
        python3.14-venv \
        python3-pip \
        build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && ln -sf /usr/bin/python3.14 /usr/local/bin/python3 \
    && ln -sf /usr/bin/python3.14 /usr/local/bin/python \
    && python3.14 -m venv "${VIRTUAL_ENV}" \
    && python -m pip install --upgrade pip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY workspace/evals/requirements.txt /tmp/evals-requirements.txt

RUN python -m pip install \
        -r /tmp/evals-requirements.txt \
        python-dotenv \
    && npm install --global promptfoo@0.120.19 \
    && rm /tmp/evals-requirements.txt

COPY . .
