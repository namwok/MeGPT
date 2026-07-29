from __future__ import annotations

import json
from typing import Any

from common import GITHUB_MODELS_URL, Http, PipelineError, text
from fieldy import summary

MEETING_TYPES = ["Internal", "Member", "Candidate", "Partner", "Company Attraction", "Other"]
LANES = ["Ready Talent", "Talent Attraction", "Company Attraction", "Member Engagement", "Partnerships", "Relocation Pilot", "AI Enablement", "Operations"]
ACTION_STATUS = ["New", "Next", "Waiting", "Delegated"]
PRIORITY = ["P1", "P2", "P3", "P4"]
ACTION_CATEGORY = ["Follow-up", "Decision Needed", "Research", "Outreach", "Tracker Update", "Document Prep", "Scheduling", "Other"]
SIGNAL_TYPE = ["Company Opportunity", "Talent Lead", "Member Need", "Partnership Opportunity", "Program Insight", "Risk / Barrier", "Decision", "KPI Evidence"]
IMPORTANCE = ["Critical", "High", "Medium", "Low"]
SIGNAL_STATUS = ["New", "Qualified", "In Progress"]

PROMPT = """You process Fieldy meetings for Chris Cowan, Talent and Companies Attraction Manager at techNL.
Use only supplied evidence. Never invent people, companies, decisions, owners, commitments, dates, opportunities, or risks. Leave uncertain text empty and flag it for Chris.

Lanes: Ready Talent = employer talent supports, workshops, mentorship, peer groups and labour-market programming. Talent Attraction = senior/specialized candidates, diaspora, remote workers, relocation and immigration-supported attraction. Company Attraction = companies considering an NL presence, expansion, investment or market entry. Member Engagement = member needs, navigation, visibility, introductions and retention. Partnerships = government, ecosystem, post-secondary, workforce, immigration and delivery partners. Relocation Pilot = participating companies, relocated employees, settlement, ecosystem hours, reimbursement, evaluation and retention. AI Enablement = responsible AI, tools, governance and learning. Operations = coordination, scheduling, reporting, trackers and documentation.

Create actions only for explicit commitments, clear next steps, necessary decisions, or strongly supported follow-up. P1 is urgent/consequential; P2 high leverage; P3 normal; P4 optional. Create signals only when they could change a decision, priority, relationship, program, pipeline, report or risk posture. Return only through the function tool."""


def schema() -> dict[str, Any]:
    action = {
        "action": {"type": "string"}, "status": {"type": "string", "enum": ACTION_STATUS},
        "priority": {"type": "string", "enum": PRIORITY}, "owner": {"type": "string"},
        "due_date": {"type": "string"}, "category": {"type": "string", "enum": ACTION_CATEGORY},
        "organization": {"type": "string"}, "person": {"type": "string"},
        "exact_next_action": {"type": "string"}, "evidence_context": {"type": "string"},
        "needs_chris": {"type": "boolean"},
    }
    signal = {
        "signal": {"type": "string"}, "signal_type": {"type": "string", "enum": SIGNAL_TYPE},
        "importance": {"type": "string", "enum": IMPORTANCE},
        "strategic_lanes": {"type": "array", "items": {"type": "string", "enum": LANES}},
        "organization": {"type": "string"}, "person": {"type": "string"},
        "status": {"type": "string", "enum": SIGNAL_STATUS}, "why_it_matters": {"type": "string"},
        "recommended_move": {"type": "string"}, "needs_chris": {"type": "boolean"},
    }
    props = {
        "meeting_type": {"type": "string", "enum": MEETING_TYPES},
        "tags": {"type": "array", "items": {"type": "string", "enum": LANES}},
        "summary": {"type": "string"}, "key_decisions": {"type": "array", "items": {"type": "string"}},
        "participants": {"type": "array", "items": {"type": "string"}},
        "organizations": {"type": "array", "items": {"type": "string"}},
        "needs_chris_review": {"type": "boolean"},
        "actions": {"type": "array", "items": {"type": "object", "properties": action, "required": list(action), "additionalProperties": False}},
        "signals": {"type": "array", "items": {"type": "object", "properties": signal, "required": list(signal), "additionalProperties": False}},
    }
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


class Sorter:
    def __init__(self, http: Http, token: str, model: str):
        self.http, self.token, self.model = http, token, model

    def analyse(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": json.dumps(record, ensure_ascii=False)}],
            "tools": [{"type": "function", "function": {"name": "record_meeting_intelligence", "description": "Return structured meeting intelligence.", "parameters": schema()}}],
            "tool_choice": "required",
            "temperature": 0.1,
        }
        data = self.http.json("POST", GITHUB_MODELS_URL, headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
            "Content-Type": "application/json", "X-GitHub-Api-Version": "2026-03-10",
        }, body=payload)
        try:
            msg = data["choices"][0]["message"]
            calls = msg.get("tool_calls") or []
            raw = json.loads(calls[0]["function"]["arguments"]) if calls else json.loads(msg["content"])
            return normalise(raw)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            raise PipelineError("GitHub Models returned an unexpected response") from e


def pick(value: Any, allowed: list[str], default: str) -> str:
    value = text(value)
    return value if value in allowed else default


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else ([] if value in (None, "") else [value])


def normalise(raw: dict[str, Any]) -> dict[str, Any]:
    actions = []
    for a in as_list(raw.get("actions")):
        if not isinstance(a, dict) or not text(a.get("action")):
            continue
        actions.append({
            "action": text(a["action"]), "status": pick(a.get("status"), ACTION_STATUS, "New"),
            "priority": pick(a.get("priority"), PRIORITY, "P3"), "owner": text(a.get("owner")),
            "due_date": text(a.get("due_date")), "category": pick(a.get("category"), ACTION_CATEGORY, "Follow-up"),
            "organization": text(a.get("organization")), "person": text(a.get("person")),
            "exact_next_action": text(a.get("exact_next_action")) or text(a["action"]),
            "evidence_context": text(a.get("evidence_context")), "needs_chris": bool(a.get("needs_chris")),
        })
    signals = []
    for s in as_list(raw.get("signals")):
        if not isinstance(s, dict) or not text(s.get("signal")):
            continue
        lanes = [x for x in as_list(s.get("strategic_lanes")) if x in LANES]
        signals.append({
            "signal": text(s["signal"]), "signal_type": pick(s.get("signal_type"), SIGNAL_TYPE, "Program Insight"),
            "importance": pick(s.get("importance"), IMPORTANCE, "Medium"), "strategic_lanes": lanes or ["Operations"],
            "organization": text(s.get("organization")), "person": text(s.get("person")),
            "status": pick(s.get("status"), SIGNAL_STATUS, "New"), "why_it_matters": text(s.get("why_it_matters")),
            "recommended_move": text(s.get("recommended_move")), "needs_chris": bool(s.get("needs_chris")),
        })
    tags = [x for x in as_list(raw.get("tags")) if x in LANES]
    return {
        "meeting_type": pick(raw.get("meeting_type"), MEETING_TYPES, "Other"), "tags": tags or ["Operations"],
        "summary": text(raw.get("summary")) or "No reliable summary generated.",
        "key_decisions": [text(x) for x in as_list(raw.get("key_decisions")) if text(x)],
        "participants": [text(x) for x in as_list(raw.get("participants")) if text(x)],
        "organizations": [text(x) for x in as_list(raw.get("organizations")) if text(x)],
        "needs_chris_review": bool(raw.get("needs_chris_review")), "actions": actions, "signals": signals,
    }


def fallback(conversation: dict[str, Any], transcript: str, tasks: list[str]) -> dict[str, Any]:
    return {
        "meeting_type": "Other", "tags": ["Operations"],
        "summary": summary(conversation) or transcript[:1800] or "Fieldy conversation imported without a summary.",
        "key_decisions": [], "participants": [], "organizations": [], "needs_chris_review": True,
        "actions": [{"action": t, "status": "New", "priority": "P3", "owner": "", "due_date": "", "category": "Follow-up", "organization": "", "person": "", "exact_next_action": t, "evidence_context": "Imported from Fieldy tasks.", "needs_chris": False} for t in tasks],
        "signals": [],
    }
