FROM python:3.11-slim

# uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (cached layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code
COPY agents/ agents/
COPY tools/ tools/
COPY app.py models.py storage.py ./

# State directory (mount as volume for persistence)
RUN mkdir -p /app/state

EXPOSE 8501

CMD ["uv", "run", "streamlit", "run", "app.py", \
     "--server.address", "0.0.0.0", \
     "--server.port", "8501", \
     "--server.headless", "true", \
     "--browser.gatherUsageStats", "false"]
