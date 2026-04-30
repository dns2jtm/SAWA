FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    wget \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install TA-Lib C library
RUN cd /tmp && \
    wget -q https://sourceforge.net/projects/ta-lib/files/ta-lib/0.4.0/ta-lib-0.4.0-src.tar.gz && \
    tar -xzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib && \
    ./configure --prefix=/usr --build=x86_64-linux-gnu && \
    make -j$(nproc) && \
    make install && \
    cd / && rm -rf /tmp/ta-lib*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . /app/

# Run the live trader by default
# Note: To run the cTrader version instead, change this to: ["python", "execution/live.py", "--live", "--confirmed"]
CMD ["python", "execution/live_trader.py"]