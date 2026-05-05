# Default GPU experiment-runner base image.
#
# Used by DockerRunner when an experiment spec doesn't bring its own
# `build_recipe.dockerfile_content`. Specs that need extra packages can
# extend this image or supply their own dockerfile_content; this image is
# only the floor.
#
# Build (gated by the gpu compose profile so it doesn't run on default `up`):
#   docker compose --profile gpu build experiment-runner
#
# Tagged synthetos-experiment-runner:latest. The worker references images
# by tag from inside the spec; defaulting to this tag is downstream code's
# responsibility.

FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

# Avoid tzdata interactive prompts.
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        software-properties-common \
        gnupg \
        ca-certificates \
        curl \
        git \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        python3.12 \
        python3.12-venv \
        python3.12-dev \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Make python/pip point at 3.12.
RUN ln -sf /usr/bin/python3.12 /usr/local/bin/python \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python3 \
    && python -m ensurepip --upgrade

# Standard ML stack. PyTorch CUDA wheels (cu124) match the base image.
RUN python -m pip install --upgrade pip \
    && python -m pip install \
        --extra-index-url https://download.pytorch.org/whl/cu124 \
        "torch>=2.4,<3" \
        "torchvision>=0.19,<1" \
        "torchaudio>=2.4,<3" \
    && python -m pip install \
        "numpy>=2,<3" \
        "pandas>=2.2,<3" \
        "scipy>=1.13,<2" \
        "scikit-learn>=1.5,<2" \
        "matplotlib>=3.9,<4" \
        "transformers>=4.45,<5" \
        "datasets>=3,<4" \
        "accelerate>=1,<2"

WORKDIR /workspace

# No CMD — the spec's command (set by the worker) runs from /workspace.
