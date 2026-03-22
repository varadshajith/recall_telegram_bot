    FROM python:3.11-slim

    WORKDIR /app

    # Install system dependencies (ffmpeg is required, build-essential/git for Whisper build)
    RUN apt-get update && apt-get install -y \
        ffmpeg \
        build-essential \
        python3-dev \
        && rm -rf /var/lib/apt/lists/*

    # Upgrade pip and install build helpers
    RUN pip install --no-cache-dir --upgrade pip setuptools wheel

    # 1. Install heavy dependencies separately so they are cached!
    # torch is the big one that takes the most time and is a sub-dependency of whisper
    RUN pip install --no-cache-dir torch

    # 2. Install openai-whisper separately
    RUN pip install --no-cache-dir openai-whisper

    # 3. Copy requirements and install the rest
    COPY requirements.txt .
    # We use grep -v to skip openai-whisper since we already installed it
    RUN pip install --no-cache-dir $(grep -v pytest requirements.txt | tr '\n' ' ')
    RUN pip install pytest==7.4.4 pytest-asyncio==0.23.4

    # Pre-download the model (cached in the image)
    RUN python -c "import whisper; whisper.load_model('base')"

    # Copy code
    COPY . .

    CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
