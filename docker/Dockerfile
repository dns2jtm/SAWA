# ─────────────────────────────────────────────────────────────────────────────
# FTMO-EURGBP Training Image
# Base: PyTorch 2.4.0 + CUDA 12.4 (RunPod GPU compatible — A100/H100/4090)
# Build:  docker build -f docker/Dockerfile -t ftmo-eurgbp .
# Push:   docker tag ftmo-eurgbp <your-dockerhub>/ftmo-eurgbp:latest
#         docker push <your-dockerhub>/ftmo-eurgbp:latest
# ─────────────────────────────────────────────────────────────────────────────
FROM pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        git \
        wget \
        rsync \
        openssh-client \
        build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/ftmo-eurgbp

# Install Python dependencies first (cached layer — only rebuilds on requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy project source
COPY . .

# Create runtime directories (data/raw etc. will be mounted or populated at runtime)
RUN mkdir -p data/raw data/features data/cache \
             models/best models/eval models/checkpoints models/logs \
             scripts

# Make entrypoint executable
RUN chmod +x docker/entrypoint.sh

ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["train"]
