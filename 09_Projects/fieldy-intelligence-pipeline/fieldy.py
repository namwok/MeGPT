from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from common import FIELDY_BASE, Http, LOG, PipelineError, first, iso_z, parse_dt, text


class Fieldy:
    def __init__(self, http: Http, api_key: str):
        self.http = http
        self.headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

    def conversations(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return self._pages("conversations", start, end)

    def transcriptions(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return self._pages("transcriptions", start, end, optional=True)

    def tasks(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return self._pages("tasks", start, end, optional=True)

    def _pages(self, resource: str, start: datetime, end: datetime, optional: bool = False) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        seen: set[str] = set()
        for _ in range(50):
            params: dict[str, Any] = {
                "startTime": iso_z(start),
                "endTime": iso_z(end),
                "pageSize": 100,
            }
            if cursor:
                params["pageToken"] = cursor
                params["cursor"] = cursor
            try:
                payload = self.http.json("GET", f"{FIELDY_BASE}/{resource}", headers=self.headers, params=params)
            except PipelineError:
                if optional:
                    LOG.warning("Optional Fieldy resource unavailable: %s", resource)
                    return []
                raise
            items.extend(x for x in item_list(payload, resource) if isinstance(x, dict))
            cursor = next_cursor(payload)
            if not cursor or cursor in seen:
                break
            seen.add(cursor)
        return items


def item_list(payload: dict[str, Any], resource: str) -> list[Any]:
    singular = resource.rstrip("s")
    for key in (resource, "items", "results", "data", "content", singular):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for nested in (resource, "items", "results", "data"):
                if isinstance(value.get(nested), list):
                    return value[nested]
    return []


def next_cursor(payload: dict[str, Any]) -> str | None:
    for key in ("nextPageToken", "next_page_token", "nextCursor", "next_cursor", "cursor"):
        if isinstance(payload.get(key), str) and payload[key]:
            return payload[key]
    return next_cursor(payload["pagination"]) if isinstance(payload.get("pagination"), dict) else None


def conversation_id(c: dict[str, Any]) -> str:
    return text(first(c, "id", "conversationId", "conversation_id", "uuid"))


def start_time(c: dict[str, Any]) -> datetime:
    for key in ("startTime", "startedAt", "start_time", "createdAt", "created_at", "timestamp", "date"):
        if dt := parse_dt(c.get(key)):
            return dt
    from datetime import timezone
    return datetime.now(timezone.utc) - timedelta(hours=1)


def end_time(c: dict[str, Any], start: datetime) -> datetime:
    for key in ("endTime", "endedAt", "end_time", "updatedAt", "updated_at"):
        if (dt := parse_dt(c.get(key))) and dt >= start:
            return dt
    try:
        seconds = float(first(c, "durationSeconds", "duration", "durationMs"))
        if seconds > 100_000:
            seconds /= 1000
        if 0 < seconds <= 21600:
            return start + timedelta(seconds=seconds)
    except (TypeError, ValueError):
        pass
    return start + timedelta(hours=3)


def summary(c: dict[str, Any]) -> str:
    for key in ("detailedSummary", "shortSummary", "summary", "summaries", "content", "description"):
        if v := text(c.get(key)):
            return v
    return ""


def transcript(segments: list[dict[str, Any]], cid: str) -> str:
    lines: list[str] = []
    for seg in segments:
        seg_cid = text(first(seg, "conversationId", "conversation_id", "parentId"))
        if seg_cid and seg_cid != cid:
            continue
        speaker = text(first(seg, "speakerName", "speaker", "speakerLabel", "speakerId")) or "Unknown"
        body = text(first(seg, "text", "content", "transcript", "utterance"))
        if body:
            lines.append(f"{speaker}: {body}")
    return "\n".join(lines)


def task_texts(records: list[dict[str, Any]], cid: str) -> list[str]:
    out: list[str] = []
    for task in records:
        task_cid = text(first(task, "conversationId", "conversation_id", "parentId"))
        if task_cid and task_cid != cid:
            continue
        body = text(first(task, "title", "text", "content", "task", "description"))
        if body:
            due = text(first(task, "dueDate", "due_date", "deadline"))
            out.append(f"{body}{f' (due {due})' if due else ''}")
    return out
