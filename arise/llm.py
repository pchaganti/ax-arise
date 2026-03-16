from __future__ import annotations

import json
import os
import sys
import time


def llm_call(
    messages: list[dict],
    model: str = "gpt-4o-mini",
    temperature: float = 0.0,
    max_tokens: int = 4096,
    max_retries: int = 3,
) -> str:
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            return _llm_call_once(messages, model, temperature, max_tokens)
        except Exception as e:
            last_error = e
            if not _is_retryable(e):
                raise
            wait = min(2 ** attempt, 10)
            print(f"[ARISE:llm] Retry {attempt + 1}/{max_retries} after {wait}s: {e}", file=sys.stderr)
            time.sleep(wait)
    raise last_error  # type: ignore[misc]


def _llm_call_once(
    messages: list[dict],
    model: str,
    temperature: float,
    max_tokens: int,
) -> str:
    try:
        import litellm
        response = litellm.completion(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=120,
        )
        return response.choices[0].message.content
    except ImportError:
        pass

    return _raw_openai_call(messages, model, temperature, max_tokens)


def _is_retryable(error: Exception) -> bool:
    error_str = str(error).lower()
    # Rate limits, timeouts, server errors
    for pattern in ["429", "rate limit", "timeout", "timed out", "502", "503", "504", "connection"]:
        if pattern in error_str:
            return True
    return False


def llm_call_structured(
    messages: list[dict],
    model: str = "gpt-4o-mini",
    temperature: float = 0.0,
    max_tokens: int = 4096,
    max_retries: int = 3,
) -> dict:
    text = llm_call(messages, model, temperature, max_tokens, max_retries)
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines[1:] if not l.strip() == "```"]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {text[:200]}") from e


def _raw_openai_call(
    messages: list[dict],
    model: str,
    temperature: float,
    max_tokens: int,
) -> str:
    import urllib.request
    import urllib.error

    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        raise RuntimeError(f"OpenAI API error {e.code}: {body[:200]}") from e
