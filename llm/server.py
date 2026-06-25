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

DEFAULT_MODEL = "qwen2.5:3b"
OLLAMA_URL = "http://localhost:11434"


def model_name() -> str:
    return os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)


def is_running() -> bool:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def start() -> None:
    """Start the Ollama daemon if it isn't already running."""
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
            subprocess.run(["ollama", "pull", model], check=True)
    except Exception as e:
        print(f"   Warning: could not verify model presence: {e}")


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

    response = ollama.chat(**kwargs)
    return response["message"]["content"]
