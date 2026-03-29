FROM python:3.12-slim-bookworm

WORKDIR /app

# Build tools for pybullet compilation + cleanup after
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends \
    g++ \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y g++ && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Copy project
COPY mcp_server/ mcp_server/
COPY llm_controller/ llm_controller/
COPY scripts/ scripts/

# Create episodes output dir (will be mounted as volume)
RUN mkdir -p /app/episodes

# Env defaults
ENV PYTHONUNBUFFERED=1
ENV SIMULATE=true
ENV DECRAS_GUI=false
ENV OLLAMA_HOST=http://ollama:11434

# Default: run the LLM controller loop
CMD ["python", "-m", "llm_controller"]
