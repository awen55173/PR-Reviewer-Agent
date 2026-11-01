"""Small OpenAI-compatible JSON client with auditable usage accounting."""
import json
import re
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .telemetry import ExecutionLedger


_FENCED_JSON = re.compile(r"\A```[A-Za-z0-9_-]*\s*\n?(.*?)\n?```\Z", re.DOTALL)
_BOM = chr(0xFEFF)


def parse_json_object(content: Any) -> Dict[str, Any]:
    """Return the first JSON object found in a model response.

    Providers sometimes wrap JSON in markdown fences, surround it with prose,
    or emit a second value despite the requested JSON response format. Accept
    the first decodable object so one stray character does not discard an
    otherwise usable review.
    """
    if not isinstance(content, str):
        raise ValueError("model response content is not text")
    text = content.strip().removeprefix(_BOM).strip()
    if not text:
        raise ValueError("model returned an empty response")
    fenced = _FENCED_JSON.match(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = None
    if isinstance(value, dict):
        return value
    start = text.find("{")
    if start >= 0:
        try:
            value, _ = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict):
            return value
    raise ValueError("model response did not contain a JSON object")


class JsonChatClient:
    def __init__(
        self, base_url: str, api_key: str, model: str,
        provider: str = "openai-compatible", timeout: int = 60,
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.provider = provider
        self.timeout = timeout
        self.extra_headers = dict(extra_headers or {})

    def complete_json(
        self, role: str, system: str, user: str,
        ledger: Optional[ExecutionLedger] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        payload: Dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)
        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        headers.update(self.extra_headers)
        message = ""
        for attempt in range(2):
            request_payload = dict(payload)
            if attempt:
                # A malformed answer is often transient. Ask once more while
                # keeping the same conversation so the model can repair it.
                request_payload["messages"] = messages + [{
                    "role": "user",
                    "content": (
                        "Your previous response was not valid JSON (%s). "
                        "Return exactly one compact JSON object with no markdown "
                        "fences, comments, or text outside the object." % message
                    ),
                }]
            request = urllib.request.Request(
                self.base_url + "/chat/completions",
                data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
                headers=headers, method="POST",
            )
            started = time.monotonic()
            usage: Dict[str, Any] = {}
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = json.loads(response.read().decode("utf-8"))
                usage = body.get("usage") or {}
                content = body["choices"][0]["message"]["content"]
                result = parse_json_object(content)
                if ledger:
                    ledger.record_model(
                        role, self.provider, self.model, usage,
                        int((time.monotonic() - started) * 1000), True,
                    )
                return result
            except urllib.error.HTTPError as exc:
                detail = exc.read(1000).decode("utf-8", errors="replace")
                message = "%s API returned HTTP %d: %s" % (
                    self.provider, exc.code, detail,
                )
                if ledger:
                    ledger.record_model(
                        role, self.provider, self.model, usage,
                        int((time.monotonic() - started) * 1000), False, message,
                    )
                raise RuntimeError(message) from exc
            except (urllib.error.URLError, socket.timeout) as exc:
                message = "%s request failed: %s" % (self.provider, exc)
                if ledger:
                    ledger.record_model(
                        role, self.provider, self.model, usage,
                        int((time.monotonic() - started) * 1000), False, message,
                    )
                raise RuntimeError(message) from exc
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                message = "%s JSON request failed: %s" % (self.provider, exc)
                if ledger:
                    ledger.record_model(
                        role, self.provider, self.model, usage,
                        int((time.monotonic() - started) * 1000), False, message,
                    )
        raise RuntimeError(message)
