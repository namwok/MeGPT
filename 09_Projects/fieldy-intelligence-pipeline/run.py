#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ai_sorter import Sorter, fallback
from common import Http, LOG, PipelineError, Settings, first, iso_z, text
from fieldy import Fieldy, conversation_id, end_time, start_time, summary, task_texts, transcript
from notion_sink import Notion

TZ = ZoneInfo("America/St_Johns")
TARGETS = {"Morning": (8, 0), "Midday": (12, 30), "Evening": (20, 0)}


def run_slot(now: datetime) -> str | None:
    for name, (hour, minute) in TARGETS.items():
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if timedelta(0) <= now - target < timedelta(minutes=45):
            return name
    return None


def execute(settings: Settings, force: bool = False) -> int:
    now = datetime.now(timezone.utc)
    local = now.astimezone(TZ)
    slot = run_slot(local)
    if not force and not slot:
        LOG.info("Outside configured Newfoundland run window; exiting")
        return 0
    slot = slot or "Morning"

    http = Http()
    fieldy = Fieldy(http, settings.fieldy_key)
    notion = Notion(http, settings.notion_key)
    sorter = Sorter(http, settings.github_token, settings.model)
    notion.verify()

    conversations = fieldy.conversations(now - timedelta(hours=settings.lookback_hours), now)
    LOG.info("Fieldy returned %d conversation record(s)", len(conversations))
    processed: list[dict] = []
    notices: list[str] = []

    for c in sorted(conversations, key=start_time):
        cid = conversation_id(c)
        if not cid:
            notices.append("A Fieldy conversation without a stable ID was skipped")
            continue
        if notion.meeting_exists(cid):
            LOG.info("Skipping previously processed Fieldy conversation %s", cid)
            continue
        try:
            c_start = start_time(c)
            c_end = end_time(c, c_start)
            raw_transcript = transcript(fieldy.transcriptions(c_start - timedelta(minutes=2), c_end + timedelta(minutes=2)), cid)
            tasks = task_texts(fieldy.tasks(c_start - timedelta(minutes=2), c_end + timedelta(minutes=2)), cid)
            record = {
                "fieldy_conversation_id": cid,
                "title": text(first(c, "title", "name", "subject")),
                "start_time": iso_z(c_start),
                "fieldy_summary": summary(c),
                "fieldy_tasks": tasks,
                "keywords": c.get("keywords") or [],
                "quotes": c.get("quotes") or [],
                "location": c.get("location") or c.get("locationMetadata") or {},
                "transcript_excerpt": raw_transcript[:8000],
            }
            try:
                intel = sorter.analyse(record)
            except Exception as exc:
                LOG.warning("AI sorter fallback used for %s", cid)
                intel = fallback(c, raw_transcript, tasks)
                notices.append(f"AI fallback used for {cid}: {type(exc).__name__}")
            page = notion.meeting(c, intel, raw_transcript, tasks)
            title = text(first(c, "title", "name", "subject")) or cid
            processed.append({"title": title, "url": page.get("url", ""), "intel": intel})
            LOG.info("Processed Fieldy conversation %s", cid)
        except Exception as exc:
            LOG.exception("Failed to process Fieldy conversation %s", cid)
            notices.append(f"{cid}: {type(exc).__name__}")

    notion.brief(slot, local, processed, notices)
    LOG.info("Run complete: %d meeting(s), %d notice(s)", len(processed), len(notices))
    return 1 if notices and not processed else 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--lookback-hours", type=int)
    p.add_argument("--force", action="store_true")
    p.add_argument("--validate-only", action="store_true")
    args = p.parse_args()
    try:
        settings = Settings.load(args.lookback_hours)
        if args.validate_only:
            Notion(Http(), settings.notion_key).verify()
            LOG.info("Configuration validation passed")
            return 0
        return execute(settings, args.force)
    except PipelineError as exc:
        LOG.error("Pipeline error: %s", exc)
        return 2
    except Exception:
        LOG.exception("Unexpected pipeline failure")
        return 3


if __name__ == "__main__":
    sys.exit(main())
