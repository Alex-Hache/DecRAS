"""LLM interface — supports ollama and mlx-lm backends."""

import logging
from llm_controller.config import LLM_BACKEND, OLLAMA_BASE_URL, OLLAMA_MODEL, MLX_MODEL

logger = logging.getLogger(__name__)


class LLM:
    def __init__(self, backend: str | None = None):
        self._backend = backend or LLM_BACKEND
        self._model = None
        self._tokenizer = None
        self._init_backend()

    def _init_backend(self):
        if self._backend == "ollama":
            logger.info("Using ollama backend with model %s", OLLAMA_MODEL)
        elif self._backend == "mlx":
            logger.info("Loading mlx-lm model %s...", MLX_MODEL)
            from mlx_lm import load
            self._model, self._tokenizer = load(MLX_MODEL)
            logger.info("mlx-lm model loaded")
        else:
            raise ValueError(f"Unknown LLM backend: {self._backend}")

    def generate(self, messages: list[dict[str, str]]) -> str:
        """Generate a response from the LLM.

        Args:
            messages: List of {"role": "system"|"user"|"assistant", "content": str}

        Returns:
            The assistant's response text.
        """
        if self._backend == "ollama":
            return self._generate_ollama(messages)
        elif self._backend == "mlx":
            return self._generate_mlx(messages)

    def _generate_ollama(self, messages: list[dict[str, str]]) -> str:
        import requests
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 256,
                },
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    def _generate_mlx(self, messages: list[dict[str, str]]) -> str:
        from mlx_lm import generate
        # Format messages into a single prompt using chat template
        prompt = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        response = generate(
            self._model,
            self._tokenizer,
            prompt=prompt,
            max_tokens=256,
            temp=0.3,
        )
        return response
