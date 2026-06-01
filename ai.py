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


def _auth_headers() -> dict[str, str]:
    """Authorization header for a password-protected (reverse-proxied) server.
    Empty when no key is configured (plain local Ollama needs none)."""
    key = (user_settings.get("ai_api_key") or "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _verify_tls() -> bool:
    """Whether to verify TLS certs. Users with a self-signed cert (Caddy
    'tls internal') turn this off in Settings."""
    return bool(user_settings.get("ai_verify_ssl"))


def _request(method: str, path: str, **kwargs) -> requests.Response:
    """Wrapper that injects auth headers + TLS-verify setting on every call."""
    headers = {**_auth_headers(), **kwargs.pop("headers", {})}
    verify = _verify_tls()
    if not verify:
        # Self-signed cert is expected — silence the noisy urllib3 warning.
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
    return requests.request(
        method, f"{get_base_url()}{path}", headers=headers, verify=verify, **kwargs
    )


def ping() -> tuple[bool, str]:
    """Quick connectivity check. Returns (ok, message)."""
    base = get_base_url()
    try:
        r = _request("GET", "/api/tags", timeout=4)
        if r.status_code == 200:
            return True, "Connected."
        if r.status_code in (401, 403):
            return False, (
                f"Server rejected the password (HTTP {r.status_code}). "
                "Check the API key / password in Settings."
            )
        return False, f"Server returned HTTP {r.status_code}."
    except requests.ConnectionError:
        return False, f"Couldn't reach {base}. Is the server running and reachable?"
    except requests.Timeout:
        return False, f"Timed out reaching {base}."
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def list_models() -> list[str]:
    """Return model names available on the configured Ollama server."""
    try:
        r = _request("GET", "/api/tags", timeout=5)
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
    payload: dict[str, Any] = {
        "model": get_model(),
        "messages": messages,
        "stream": True,
    }
    try:
        with _request("POST", "/api/chat", json=payload, stream=True, timeout=timeout) as r:
            if r.status_code in (401, 403):
                on_done(
                    f"Server rejected the password (HTTP {r.status_code}). "
                    "Check the API key / password in Settings."
                )
                return
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
