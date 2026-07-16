"""
Local LLM server management via Ollama.

Handles starting the Ollama daemon, pulling the model on first run,
and providing a single generate() entry point used by all agents.

Model selection (in priority order):
  1. OLLAMA_MODEL env var
  2. DEFAULT_MODEL constant below

qwen2.5:3b is the default: ~2 GB RAM, strong JSON output, fast on Apple
Silicon via Metal GPU offload. Override with OLLAMA_MODEL=qwen2.5:7b for
better reasoning at the cost of ~2x slower generation.
"""

import os
import subprocess
import sys
import time

import ollama
import requests
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

import observability

DEFAULT_MODEL = "qwen2.5:3b"
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

logger = structlog.get_logger(__name__)
tracer = observability.get_tracer(__name__)


def model_name() -> str:
    return os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)


def is_running() -> bool:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def has_model(model: str) -> bool:
    """Used by the readiness probe — is `model` actually pulled and available?"""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        local = [m["name"] for m in r.json().get("models", [])]
        return model in local
    except Exception:
        return False


def start() -> None:
    """Start the Ollama daemon if it isn't already running."""
    if os.environ.get("OLLAMA_HOST"):
        # Running in a container — Ollama is a separate service, not a subprocess
        return

    if is_running():
        return

    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        print("✗  Ollama not found. Install from https://ollama.com and re-run.")
        sys.exit(1)

    for _ in range(20):
        time.sleep(0.5)
        if is_running():
            return

    print("✗  Ollama failed to start within 10 s.")
    sys.exit(1)


def ensure_model(model: str | None = None) -> None:
    """Pull the model if it is not already present locally."""
    model = model or model_name()
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        local = [m["name"] for m in r.json().get("models", [])]
        if model not in local:
            print(f"   Pulling {model} (first run only, ~2 GB) …")
            ollama.pull(model)
    except Exception as e:
        print(f"   Warning: could not verify model presence: {e}")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((requests.exceptions.RequestException, ollama.ResponseError, ConnectionError)),
    reraise=True,
)
def _chat(**kwargs) -> dict:
    return ollama.chat(**kwargs)


def generate(
    prompt: str,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 2000,
    json_mode: bool = True,
) -> str:
    """
    Run a single inference call and return the response text.

    json_mode=True tells Ollama to constrain output to valid JSON, which
    dramatically improves reliability for structured-output tasks.

    Transient failures (connection errors, Ollama restarts mid-request) are
    retried up to 3x with exponential backoff before propagating.
    """
    model = model or model_name()
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "options": {"num_predict": max_tokens, "temperature": 0.1},
    }
    if json_mode:
        kwargs["format"] = "json"

    with tracer.start_as_current_span("llm.generate") as span:
        span.set_attribute("llm.model", model)
        span.set_attribute("llm.max_tokens", max_tokens)
        span.set_attribute("llm.json_mode", json_mode)

        start = time.time()
        try:
            response = _chat(**kwargs)
        except Exception as e:
            duration = time.time() - start
            observability.LLM_CALLS.labels(model=model, outcome="error").inc()
            observability.LLM_CALL_DURATION.labels(model=model).observe(duration)
            logger.error("llm_call_failed", model=model, duration_s=round(duration, 2), error=str(e))
            observability.capture_exception(e, model=model, max_tokens=max_tokens)
            raise
        duration = time.time() - start

        prompt_tokens = response.get("prompt_eval_count", 0)
        completion_tokens = response.get("eval_count", 0)
        observability.LLM_CALLS.labels(model=model, outcome="success").inc()
        observability.LLM_CALL_DURATION.labels(model=model).observe(duration)
        observability.LLM_TOKENS.labels(model=model, kind="prompt").inc(prompt_tokens)
        observability.LLM_TOKENS.labels(model=model, kind="completion").inc(completion_tokens)
        span.set_attribute("llm.prompt_tokens", prompt_tokens)
        span.set_attribute("llm.completion_tokens", completion_tokens)
        span.set_attribute("llm.duration_s", duration)

        logger.info(
            "llm_call_completed",
            model=model,
            duration_s=round(duration, 2),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        return response["message"]["content"]
