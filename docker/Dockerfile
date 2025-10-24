FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \ 
    && apt-get install -y --no-install-recommends \
        build-essential \
        gdal-bin \
        libgdal-dev \
        libgl1 \
        git \
        curl \ 
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY config /app/config

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install "torch==2.7.0" "torchvision==0.22.0" "torchaudio==2.7.0" \
    && python -m pip install -e .

COPY . /app

ENTRYPOINT ["uummannaq-ice"]
CMD ["--config-file", "config/single_tile_debug.yaml"]
