import os

# LLM settings
LLM_BACKEND = os.environ.get("LLM_BACKEND", "ollama")  # "ollama" or "mlx"

# Ollama settings
OLLAMA_BASE_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

# mlx-lm settings
MLX_MODEL = "mlx-community/Qwen2.5-7B-Instruct-4bit"

# MCP server command (spawned as subprocess via stdio)
MCP_SERVER_CMD = ["python", "-m", "mcp_server.server"]

# Reasoning loop
MAX_STEPS = int(os.environ.get("MAX_STEPS", "30"))
HISTORY_WINDOW = 5  # number of recent turns to include in prompt
