from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Iterable

from common import ACTIONS_DS, BRIEFS_DS, MEETINGS_DS, NOTION_BASE, NOTION_VERSION, SIGNALS_DS, VERSION, Http, chunks, text
from fieldy import conversation_id, start_time


class Notion:
    def __init__(self, http: Http, key: str):
        self.http = http
        self.h = {"Authorization": f"Bearer {key}", "Notion-Version": NOTION_VERSION, "Content-Type": "application/json"}

    def verify(self) -> None:
        self.http.json("GET", f"{NOTION_BASE}/data_sources/{MEETINGS_DS}", headers=self.h)

    def meeting_exists(self, cid: str) -> bool:
        data = self.http.json("POST", f"{NOTION_BASE}/data_sources/{MEETINGS_DS}/query", headers=self.h, body={
            "page_size": 1, "filter": {"property": "Fieldy Conversation ID", "rich_text": {"equals": cid}}
        })
        return bool(data.get("results"))

    def brief_exists(self, title: str) -> bool:
        data = self.http.json("POST", f"{NOTION_BASE}/data_sources/{BRIEFS_DS}/query", headers=self.h, body={
            "page_size": 1, "filter": {"property": "Brief", "title": {"equals": title}}
        })
        return bool(data.get("results"))

    def meeting(self, conversation: dict[str, Any], intel: dict[str, Any], transcript: str, tasks: list[str]) -> dict[str, Any]:
        cid = conversation_id(conversation)
        title = text(conversation.get("title") or conversation.get("name") or conversation.get("subject")) or f"Fieldy meeting {cid}"
        fieldy_url = text(conversation.get("url") or conversation.get("webUrl") or conversation.get("shareUrl"))
        props = {
            "Meeting": title_prop(title), "Meeting Date": date_prop(start_time(conversation)),
            "Participants": rich_prop(", ".join(intel["participants"])), "Organizations": rich_prop(", ".join(intel["organizations"])),
            "Meeting Type": select_prop(intel["meeting_type"]), "Tags": multi_prop(intel["tags"]),
            "Summary": rich_prop(intel["summary"]), "Key Decisions": rich_prop("\n".join(intel["key_decisions"])),
            "Processing Status": select_prop("Processed"), "Source": select_prop("Fieldy"),
            "Needs Chris Review": check_prop(intel["needs_chris_review"]), "Processed At": date_prop(datetime.now().astimezone()),
            "Fieldy Conversation ID": rich_prop(cid), "Automation Version": rich_prop(VERSION),
        }
        if fieldy_url.startswith("http"):
            props["Fieldy URL"] = {"url": fieldy_url}
            props["Transcript Archive URL"] = {"url": fieldy_url}
        blocks = meeting_blocks(cid, intel, tasks, transcript)
        page = self._page(MEETINGS_DS, props, blocks[:100])
        for i in range(100, len(blocks), 100):
            self.http.json("PATCH", f"{NOTION_BASE}/blocks/{page['id']}/children", headers=self.h, body={"children": blocks[i:i+100]})
            time.sleep(0.35)
        if page.get("url"):
            self.http.json("PATCH", f"{NOTION_BASE}/pages/{page['id']}", headers=self.h, body={"properties": {"Transcript Archive URL": {"url": page["url"]}}})
        for action in intel["actions"]:
            self.action(action, page["id"])
        for signal in intel["signals"]:
            self.signal(signal, page["id"])
        return page

    def action(self, a: dict[str, Any], meeting_id: str) -> None:
        props = {
            "Action": title_prop(a["action"]), "Status": select_prop(a["status"]), "Priority": select_prop(a["priority"]),
            "Owner": rich_prop(a["owner"]), "Category": select_prop(a["category"]), "Organization": rich_prop(a["organization"]),
            "Person": rich_prop(a["person"]), "Source Meeting": relation_prop(meeting_id),
            "Exact Next Action": rich_prop(a["exact_next_action"]), "Evidence / Context": rich_prop(a["evidence_context"]),
            "Needs Chris": check_prop(a["needs_chris"]), "Created From AI": check_prop(True),
        }
        if due := iso_date(a.get("due_date", "")):
            props["Due Date"] = {"date": {"start": due}}
        self._page(ACTIONS_DS, props)

    def signal(self, s: dict[str, Any], meeting_id: str) -> None:
        self._page(SIGNALS_DS, {
            "Signal": title_prop(s["signal"]), "Signal Type": select_prop(s["signal_type"]), "Importance": select_prop(s["importance"]),
            "Strategic Lane": multi_prop(s["strategic_lanes"]), "Organization": rich_prop(s["organization"]), "Person": rich_prop(s["person"]),
            "Status": select_prop(s["status"]), "Why It Matters": rich_prop(s["why_it_matters"]),
            "Recommended Move": rich_prop(s["recommended_move"]), "Needs Chris": check_prop(s["needs_chris"]),
            "Source Meeting": relation_prop(meeting_id),
        })

    def brief(self, run: str, local_now: datetime, processed: list[dict[str, Any]], notices: list[str]) -> None:
        title = f"{local_now.date().isoformat()} — {run} Fieldy Brief"
        if self.brief_exists(title):
            return
        actions = [a for x in processed for a in x["intel"]["actions"]]
        signals = [s for x in processed for s in x["intel"]["signals"]]
        top = top_move(actions, signals)
        needs = sum(int(x["intel"]["needs_chris_review"]) for x in processed) + sum(int(a["needs_chris"]) for a in actions) + sum(int(s["needs_chris"]) for s in signals)
        status = "Delivered" if processed else ("Error" if notices else "No New Meetings")
        summary = f"Processed {len(processed)} new Fieldy meeting(s)." if processed else "No new Fieldy conversations were available."
        if notices:
            summary += f" {len(notices)} automation notice(s) were recorded."
        self._page(BRIEFS_DS, {
            "Brief": title_prop(title), "Brief Date": date_prop(local_now), "Run": select_prop(run), "Status": select_prop(status),
            "Meetings Processed": num_prop(len(processed)), "New Actions": num_prop(len(actions)), "New Signals": num_prop(len(signals)),
            "P1 Items": num_prop(sum(a["priority"] == "P1" for a in actions)), "Needs Chris": num_prop(needs),
            "Executive Summary": rich_prop(summary), "Top Move": rich_prop(top),
        }, brief_blocks(processed, notices, top))

    def _page(self, ds: str, props: dict[str, Any], children: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"parent": {"type": "data_source_id", "data_source_id": ds}, "properties": props}
        if children:
            body["children"] = children
        return self.http.json("POST", f"{NOTION_BASE}/pages", headers=self.h, body=body)


def rt(s: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": part}} for part in chunks(s, 1900)]

def title_prop(s: str) -> dict[str, Any]: return {"title": rt(s[:1900])}
def rich_prop(s: str) -> dict[str, Any]: return {"rich_text": rt(s[:1900])}
def date_prop(dt: datetime) -> dict[str, Any]: return {"date": {"start": dt.isoformat()}}
def select_prop(s: str) -> dict[str, Any]: return {"select": {"name": s}}
def multi_prop(values: Iterable[str]) -> dict[str, Any]: return {"multi_select": [{"name": x} for x in values]}
def check_prop(v: bool) -> dict[str, Any]: return {"checkbox": bool(v)}
def num_prop(v: int | float) -> dict[str, Any]: return {"number": v}
def relation_prop(pid: str) -> dict[str, Any]: return {"relation": [{"id": pid}]}

def iso_date(value: str) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None

def paragraph(s: str) -> dict[str, Any]: return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt(s)}}
def heading(s: str, n: int = 2) -> dict[str, Any]:
    t = f"heading_{n}"
    return {"object": "block", "type": t, t: {"rich_text": rt(s)}}
def bullet(s: str) -> dict[str, Any]: return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": rt(s)}}

def meeting_blocks(cid: str, intel: dict[str, Any], tasks: list[str], transcript: str) -> list[dict[str, Any]]:
    out = [heading("Executive Summary"), paragraph(intel["summary"]), heading("Key Decisions")]
    out += [bullet(x) for x in intel["key_decisions"]] or [paragraph("No explicit decision was confidently identified.")]
    out += [heading("Fieldy Tasks")]
    out += [bullet(x) for x in tasks] or [paragraph("No Fieldy task was attached to this conversation.")]
    out += [heading("Source Metadata"), paragraph(f"Fieldy conversation ID: {cid}"), heading("Raw Transcript")]
    out += [paragraph(x) for x in chunks(transcript, 1800)] or [paragraph("No transcription segments were returned by Fieldy.")]
    return out

def top_move(actions: list[dict[str, Any]], signals: list[dict[str, Any]]) -> str:
    if actions:
        order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
        return sorted(actions, key=lambda a: (order.get(a["priority"], 9), not a["needs_chris"]))[0]["exact_next_action"]
    if signals:
        order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        s = sorted(signals, key=lambda x: order.get(x["importance"], 9))[0]
        return s["recommended_move"] or s["signal"]
    return ""

def brief_blocks(processed: list[dict[str, Any]], notices: list[str], top: str) -> list[dict[str, Any]]:
    out = [heading("Highest-Leverage Move"), paragraph(top or "No new move identified."), heading("Meetings Processed")]
    for x in processed:
        out += [heading(x["title"], 3), paragraph(x["intel"]["summary"])]
        out += [bullet(f"{a['priority']} — {a['exact_next_action']}") for a in x["intel"]["actions"]]
    if not processed:
        out.append(paragraph("No new Fieldy conversations were found in this run."))
    if notices:
        out.append(heading("Automation Notices"))
        out += [bullet(x) for x in notices]
    return out[:100]
