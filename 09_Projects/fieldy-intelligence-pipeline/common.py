from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

import requests

FIELDY_BASE = "https://api.fieldy.ai/api/public/v2"
GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"
NOTION_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"
VERSION = "1.0.0"

MEETINGS_DS = "96e3ccdd-ece1-4b30-a159-db860c4d4a76"
ACTIONS_DS = "9be2b7c6-6bcc-4a72-b0b1-1460a76535d3"
SIGNALS_DS = "1e4fb2a3-12af-4386-a2ef-635269d97f8c"
BRIEFS_DS = "12da2525-6d9d-4496-a585-25bda3b26686"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("fieldy-pipeline")


class PipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    fieldy_key: str
    notion_key: str
    github_token: str
    model: str = "openai/gpt-4.1"
    lookback_hours: int = 36

    @classmethod
    def load(cls, lookback_hours: int | None = None) -> "Settings":
        values = {
            "FIELDY_API_KEY": os.getenv("FIELDY_API_KEY", "").strip(),
            "NOTION_API_KEY": os.getenv("NOTION_API_KEY", "").strip(),
            "GITHUB_TOKEN": os.getenv("GITHUB_TOKEN", "").strip(),
        }
        missing = [k for k, v in values.items() if not v]
        if missing:
            raise PipelineError("Missing required secrets: " + ", ".join(missing))
        return cls(
            fieldy_key=values["FIELDY_API_KEY"],
            notion_key=values["NOTION_API_KEY"],
            github_token=values["GITHUB_TOKEN"],
            model=os.getenv("GITHUB_MODEL", "openai/gpt-4.1"),
            lookback_hours=lookback_hours or int(os.getenv("LOOKBACK_HOURS", "36")),
        )


class Http:
    def __init__(self, timeout: int = 45):
        self.s = requests.Session()
        self.timeout = timeout

    def json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        expected: Sequence[int] = (200,),
        retries: int = 4,
    ) -> dict[str, Any]:
        delay = 1.0
        for attempt in range(retries):
            r = self.s.request(method, url, headers=headers, params=params, json=body, timeout=self.timeout)
            if r.status_code in expected:
                if not r.content:
                    return {}
                data = r.json()
                return data if isinstance(data, dict) else {"data": data}
            if r.status_code in {408, 425, 429, 500, 502, 503, 504} and attempt + 1 < retries:
                retry_after = r.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    delay = max(delay, float(retry_after))
                time.sleep(delay)
                delay = min(delay * 2, 20)
                continue
            safe = r.text[:400].replace("\n", " ")
            raise PipelineError(f"HTTP {r.status_code} from {url}: {safe}")
        raise PipelineError(f"Request failed after retries: {url}")


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(v for item in value if (v := text(item)))
    if isinstance(value, dict):
        for key in ("text", "content", "value", "summary", "title", "name"):
            if key in value and (v := text(value[key])):
                return v
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def first(d: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in d and d[key] not in (None, "", [], {}):
            return d[key]
    return None


def parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        n = float(value)
        if n > 10_000_000_000:
            n /= 1000
        return datetime.fromtimestamp(n, tz=timezone.utc)
    s = str(value).strip()
    if s.isdigit():
        return parse_dt(int(s))
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def chunks(s: str, size: int = 1800) -> list[str]:
    out: list[str] = []
    s = s or ""
    while s:
        if len(s) <= size:
            out.append(s)
            break
        cut = s.rfind("\n", 0, size)
        if cut < size // 2:
            cut = s.rfind(" ", 0, size)
        if cut < size // 2:
            cut = size
        out.append(s[:cut].strip())
        s = s[cut:].lstrip()
    return [x for x in out if x]
