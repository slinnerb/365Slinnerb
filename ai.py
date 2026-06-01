"""Local AI integration — talks to an Ollama HTTP API on the user's network.

Ollama's /api/chat endpoint accepts:
  POST {base_url}/api/chat
  { "model": "llama3", "messages": [{"role": "user", "content": "..."}], "stream": true }

When stream=True, the server returns NDJSON: one JSON object per line, each with
`message.content` as an incremental chunk. The final chunk has `done: true`."""

from __future__ import annotations

import json
from typing import Any, Callable

import requests

import settings as user_settings

DEFAULT_BASE_URL = "http://10.0.0.54:11434"
DEFAULT_MODEL = "qwen2.5:7b"


def get_base_url() -> str:
    return (user_settings.get("ai_base_url") or DEFAULT_BASE_URL).rstrip("/")


def get_model() -> str:
    return user_settings.get("ai_model") or DEFAULT_MODEL


def ping() -> tuple[bool, str]:
    """Quick connectivity check. Returns (ok, message)."""
    base = get_base_url()
    try:
        r = requests.get(f"{base}/api/tags", timeout=3)
        if r.status_code == 200:
            return True, "Connected."
        return False, f"Server returned HTTP {r.status_code}."
    except requests.ConnectionError:
        return False, f"Couldn't reach {base}. Is Ollama running and reachable on this network?"
    except requests.Timeout:
        return False, f"Timed out reaching {base}."
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def list_models() -> list[str]:
    """Return model names available on the configured Ollama server."""
    try:
        r = requests.get(f"{get_base_url()}/api/tags", timeout=5)
        r.raise_for_status()
        data = r.json()
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except Exception:
        return []


def stream_chat(
    messages: list[dict[str, str]],
    on_chunk: Callable[[str], None],
    on_done: Callable[[str | None], None],
    stop_flag: Callable[[], bool] = lambda: False,
    timeout: int = 180,
) -> None:
    """Stream a chat completion. Calls on_chunk(text) for each incremental piece
    of the assistant's reply, then on_done(error_message_or_None) when finished.

    Designed to run inside a background thread — UI updates from on_chunk should
    be scheduled back onto the Tk main loop with widget.after()."""
    url = f"{get_base_url()}/api/chat"
    payload: dict[str, Any] = {
        "model": get_model(),
        "messages": messages,
        "stream": True,
    }
    try:
        with requests.post(url, json=payload, stream=True, timeout=timeout) as r:
            if r.status_code != 200:
                body = r.text[:300]
                # 404 from Ollama almost always means the model isn't installed.
                # Pull the available model list and surface it in the error so the
                # user can fix it without leaving the chat.
                if r.status_code == 404 and "not found" in body.lower():
                    available = list_models()
                    model = get_model()
                    hint = (
                        f"Model '{model}' is not installed on the Ollama server."
                    )
                    if available:
                        hint += (
                            f"\n\nAvailable models on this server:\n  • "
                            + "\n  • ".join(available)
                            + f"\n\nFix: open Settings → change the Model field to one of the above, "
                            f"OR run `ollama pull {model}` on the server."
                        )
                    else:
                        hint += (
                            "\n\nNo models are installed yet. On the server, run:\n"
                            f"  ollama pull {model}"
                        )
                    on_done(hint)
                    return
                on_done(f"AI server returned HTTP {r.status_code}: {body}")
                return
            for line in r.iter_lines(decode_unicode=True):
                if stop_flag():
                    break
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("error"):
                    on_done(str(obj["error"]))
                    return
                msg = obj.get("message") or {}
                chunk = msg.get("content") or ""
                if chunk:
                    on_chunk(chunk)
                if obj.get("done"):
                    break
        on_done(None)
    except requests.ConnectionError:
        on_done(f"Couldn't reach AI server at {get_base_url()}. Is Ollama running?")
    except requests.Timeout:
        on_done("AI server timed out. The model may still be loading — try again.")
    except Exception as e:
        on_done(f"{type(e).__name__}: {e}")
