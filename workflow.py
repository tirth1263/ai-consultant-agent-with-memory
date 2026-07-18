"""Core consulting, research, and memory workflow for the Streamlit application."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CompanyProfile:
    """The business context collected by the readiness assessment."""

    company_name: str
    industry: str
    company_size: str
    region: str
    business_model: str
    goals: str
    constraints: str
    current_tools: str
    data_maturity: str
    ai_experience: str
    budget: str
    timeline: str
    risk_tolerance: str


@dataclass(frozen=True)
class ApiCredentials:
    """Runtime credentials. Values are never persisted by this application."""

    openai_api_key: str = ""
    tavily_api_key: str = ""
    memori_api_key: str = ""
    model: str = "gpt-5-mini"

    @property
    def live_ai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def live_research(self) -> bool:
        return bool(self.tavily_api_key)


def _workspace_scope(workspace_id: str) -> str:
    """Hash a human-entered workspace key before it reaches application storage."""

    return hashlib.sha256(workspace_id.strip().lower().encode("utf-8")).hexdigest()


class AssessmentStore:
    """Small application index stored alongside Memori's SQLite tables.

    Memori remains responsible for agent capture and semantic recall. These two
    tables provide an auditable list of assessments and chat turns for the UI.
    """

    def __init__(self, db_path: str | Path = "./memori.sqlite") -> None:
        self.db_path = str(db_path)
        path = Path(self.db_path)
        if path.parent != Path("."):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=20)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS app_assessments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    profile_json TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_app_assessments_workspace
                    ON app_assessments(workspace_id, id DESC);

                CREATE TABLE IF NOT EXISTS app_chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_app_chat_workspace
                    ON app_chat_messages(workspace_id, id ASC);
                """
            )

    def save_assessment(
        self, workspace_id: str, profile: CompanyProfile, result: dict[str, Any]
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO app_assessments
                    (workspace_id, company_name, created_at, profile_json, result_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    _workspace_scope(workspace_id),
                    profile.company_name,
                    datetime.now(UTC).isoformat(),
                    json.dumps(asdict(profile), ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid or 0)

    def list_assessments(self, workspace_id: str, limit: int = 12) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, company_name, created_at, profile_json, result_json
                FROM app_assessments
                WHERE workspace_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (_workspace_scope(workspace_id), limit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "company_name": row["company_name"],
                "created_at": row["created_at"],
                "profile": json.loads(row["profile_json"]),
                "result": json.loads(row["result_json"]),
            }
            for row in rows
        ]

    def save_message(self, workspace_id: str, role: str, content: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO app_chat_messages (workspace_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (_workspace_scope(workspace_id), role, content, datetime.now(UTC).isoformat()),
            )

    def list_messages(self, workspace_id: str, limit: int = 30) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content, created_at
                FROM (
                    SELECT id, role, content, created_at
                    FROM app_chat_messages
                    WHERE workspace_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                )
                ORDER BY id ASC
                """,
                (_workspace_scope(workspace_id), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def context_digest(self, workspace_id: str, limit: int = 3) -> str:
        assessments = self.list_assessments(workspace_id, limit=limit)
        if not assessments:
            return "No prior assessment is stored for this workspace."

        parts: list[str] = []
        for item in assessments:
            result = item["result"]
            use_cases = ", ".join(
                str(case.get("title", "Untitled")) for case in result.get("use_cases", [])[:3]
            )
            parts.append(
                f"{item['company_name']} ({item['created_at'][:10]}): "
                f"score {result.get('maturity_score', 'n/a')}/100; "
                f"decision {result.get('recommendation', 'n/a')}; "
                f"priorities: {use_cases or 'none recorded'}."
            )
        return "\n".join(parts)

    def clear_workspace(self, workspace_id: str) -> None:
        with self._connect() as connection:
            scope = _workspace_scope(workspace_id)
            connection.execute("DELETE FROM app_assessments WHERE workspace_id = ?", (scope,))
            connection.execute("DELETE FROM app_chat_messages WHERE workspace_id = ?", (scope,))


class ConsultantWorkflow:
    """Coordinates Tavily research, OpenAI reasoning, and Memori v3 recall."""

    def __init__(
        self,
        credentials: ApiCredentials,
        store: AssessmentStore,
        enable_research: bool = True,
    ) -> None:
        self.credentials = credentials
        self.store = store
        self.enable_research = enable_research

    def _memory_client(self, workspace_id: str):
        """Return an OpenAI client instrumented by Memori v3.

        Imports live here so preview mode remains fast and can run even when no
        external service is configured.
        """

        from memori import Memori
        from openai import OpenAI
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        client = OpenAI(api_key=self.credentials.openai_api_key, timeout=75.0)
        db_url = f"sqlite:///{Path(self.store.db_path).resolve().as_posix()}"
        engine = create_engine(db_url, connect_args={"check_same_thread": False})
        session_factory = sessionmaker(bind=engine)
        memori = Memori(
            conn=session_factory,
            api_key=self.credentials.memori_api_key or None,
        ).llm.register(client)
        memori.attribution(entity_id=_entity_id(workspace_id), process_id="ai-readiness-consultant")
        if memori.config.storage is not None:
            memori.config.storage.build()
        return client, memori

    def research(self, profile: CompanyProfile) -> list[dict[str, Any]]:
        if not (self.enable_research and self.credentials.live_research):
            return []

        from tavily import TavilyClient

        query = (
            f"Recent credible AI implementation case studies for {profile.industry} companies "
            f"of size {profile.company_size}, focused on {profile.goals}. Include measurable "
            "outcomes, implementation lessons, risks, and realistic adoption patterns."
        )
        response = TavilyClient(api_key=self.credentials.tavily_api_key).search(
            query=query,
            search_depth="advanced",
            topic="general",
            max_results=5,
            include_answer=False,
            include_raw_content=False,
        )
        return [
            {
                "title": item.get("title", "Source"),
                "url": item.get("url", ""),
                "content": item.get("content", "")[:1400],
                "score": round(float(item.get("score", 0)), 3),
            }
            for item in response.get("results", [])
            if item.get("url")
        ]

    def run_assessment(self, profile: CompanyProfile, workspace_id: str) -> dict[str, Any]:
        if not self.credentials.live_ai:
            result = build_preview_assessment(profile)
            self.store.save_assessment(workspace_id, profile, result)
            return result

        sources = self.research(profile)
        client, memori = self._memory_client(workspace_id)
        prior_context = self.store.context_digest(workspace_id)
        prompt = _assessment_prompt(profile, sources, prior_context)

        response = client.chat.completions.create(
            model=self.credentials.model,
            messages=[
                {
                    "role": "system",
                    "content": ASSESSMENT_SYSTEM_PROMPT,
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=7000,
        )
        raw = response.choices[0].message.content or "{}"
        result = _normalize_assessment(_parse_json(raw), profile)
        result["sources"] = sources
        result["mode"] = "live"
        self.store.save_assessment(workspace_id, profile, result)

        # Advanced augmentation is asynchronous. A short bounded wait makes a
        # just-completed assessment available to an immediate follow-up.
        try:
            memori.augmentation.wait(timeout=6)
        except Exception:
            pass
        finally:
            memori.close()
        return result

    def ask_memory(self, question: str, workspace_id: str) -> str:
        self.store.save_message(workspace_id, "user", question)
        context = self.store.context_digest(workspace_id, limit=5)

        if not self.credentials.live_ai:
            answer = _preview_memory_answer(question, context)
            self.store.save_message(workspace_id, "assistant", answer)
            return answer

        client, memori = self._memory_client(workspace_id)
        response = client.chat.completions.create(
            model=self.credentials.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the follow-up partner for an AI advisory engagement. Use memories "
                        "from earlier interactions and the compact assessment index below. Be candid "
                        "about uncertainty. Never invent a past recommendation. Give a direct answer, "
                        "then the implication or next action.\n\nAssessment index:\n" + context
                    ),
                },
                {"role": "user", "content": question},
            ],
            max_completion_tokens=1800,
        )
        answer = response.choices[0].message.content or "I could not produce an answer."
        self.store.save_message(workspace_id, "assistant", answer)
        try:
            memori.augmentation.wait(timeout=4)
        except Exception:
            pass
        finally:
            memori.close()
        return answer


ASSESSMENT_SYSTEM_PROMPT = """You are a pragmatic senior AI transformation consultant.
Evaluate readiness without hype. Recommend the smallest valuable portfolio, not a collection of
generic AI ideas. Use supplied web evidence only when it genuinely supports a claim. Cost bands are
directional USD implementation estimates, not quotes. Return valid JSON only with this schema:
{
  "maturity_score": 0-100,
  "recommendation": "Adopt AI now" | "Build foundations first" | "Explore selectively",
  "headline": "short decision headline",
  "executive_summary": "2-4 sentences",
  "dimensions": {"strategy": 0-100, "data": 0-100, "technology": 0-100, "people": 0-100},
  "use_cases": [{
    "title": "specific initiative", "rationale": "why it fits", "impact": "High|Medium|Low",
    "complexity": "High|Medium|Low", "cost_band": "$...", "time_to_value": "...",
    "kpi": "measurable success indicator", "first_step": "concrete first action"
  }],
  "roadmap": [{"phase": "Days 0–30", "title": "...", "action": "..."}],
  "risks": [{"risk": "...", "mitigation": "..."}],
  "research_takeaway": "one evidence synthesis sentence"
}
Return exactly 3 prioritized use cases, exactly 3 roadmap phases (0–30, 31–60, 61–90), and 3 risks.
"""


def _assessment_prompt(
    profile: CompanyProfile, sources: list[dict[str, Any]], prior_context: str
) -> str:
    research_text = (
        json.dumps(sources, ensure_ascii=False, indent=2)
        if sources
        else "No Tavily evidence was available. Do not claim external validation."
    )
    return (
        "Create an AI readiness assessment for this profile:\n"
        f"{json.dumps(asdict(profile), ensure_ascii=False, indent=2)}\n\n"
        f"Prior workspace context:\n{prior_context}\n\n"
        f"Tavily research results:\n{research_text}"
    )


def _entity_id(workspace_id: str) -> str:
    digest = hashlib.sha256(workspace_id.strip().lower().encode("utf-8")).hexdigest()[:24]
    return f"advisory-{digest}"


def _parse_json(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
        raise ValueError("The model returned an assessment that was not valid JSON.") from exc


def _clamp_score(value: Any, fallback: int) -> int:
    try:
        return max(0, min(100, int(float(value))))
    except (TypeError, ValueError):
        return fallback


def _normalize_assessment(result: dict[str, Any], profile: CompanyProfile) -> dict[str, Any]:
    fallback = build_preview_assessment(profile)
    normalized = {**fallback, **result}
    normalized["maturity_score"] = _clamp_score(result.get("maturity_score"), 55)
    dimensions = result.get("dimensions") if isinstance(result.get("dimensions"), dict) else {}
    normalized["dimensions"] = {
        key: _clamp_score(dimensions.get(key), fallback["dimensions"][key])
        for key in ("strategy", "data", "technology", "people")
    }
    for key in ("use_cases", "roadmap", "risks"):
        if not isinstance(normalized.get(key), list) or not normalized[key]:
            normalized[key] = fallback[key]
    return normalized


def build_preview_assessment(profile: CompanyProfile) -> dict[str, Any]:
    """Create a transparent, deterministic product preview without external API calls."""

    data_scores = {"Early": 32, "Developing": 52, "Established": 72, "Advanced": 88}
    ai_scores = {"None yet": 28, "Experiments": 48, "One live use case": 67, "Scaled program": 86}
    strategy = 72 if len(profile.goals.strip()) > 45 else 55
    data = data_scores.get(profile.data_maturity, 50)
    technology = ai_scores.get(profile.ai_experience, 48)
    people = 66 if profile.risk_tolerance in {"Balanced", "Bold"} else 52
    score = round(strategy * 0.3 + data * 0.3 + technology * 0.25 + people * 0.15)

    if score >= 68:
        decision = "Adopt AI now"
        headline = "You have enough foundation to move from ideas to a controlled pilot."
    elif score >= 48:
        decision = "Explore selectively"
        headline = "Start narrow, prove the workflow, and strengthen the foundation in parallel."
    else:
        decision = "Build foundations first"
        headline = "A short foundation sprint will create more value than rushing into automation."

    return {
        "maturity_score": score,
        "recommendation": decision,
        "headline": headline,
        "executive_summary": (
            f"{profile.company_name} shows the clearest near-term opportunity where repeatable work "
            "and decision support intersect. The portfolio below favors measurable pilots, human "
            "review, and reusable data foundations. This is a product preview generated from the "
            "profile—not a live model or researched recommendation."
        ),
        "dimensions": {
            "strategy": strategy,
            "data": data,
            "technology": technology,
            "people": people,
        },
        "use_cases": [
            {
                "title": "Knowledge copilot for frontline teams",
                "rationale": (
                    "Unify approved internal guidance and help staff find a grounded answer without "
                    "searching across disconnected tools."
                ),
                "impact": "High",
                "complexity": "Medium",
                "cost_band": "$35k–$90k",
                "time_to_value": "8–12 weeks",
                "kpi": "20% reduction in time-to-answer",
                "first_step": "Select one knowledge domain and evaluate 50 representative questions.",
            },
            {
                "title": "Workflow triage and drafting assistant",
                "rationale": (
                    "Classify incoming work, extract key details, and prepare a draft while keeping "
                    "final decisions with an accountable employee."
                ),
                "impact": "High",
                "complexity": "Medium",
                "cost_band": "$50k–$140k",
                "time_to_value": "10–16 weeks",
                "kpi": "30% lower handling time with stable quality",
                "first_step": "Baseline volume, handling time, rework, and exception rates.",
            },
            {
                "title": "Management insight brief",
                "rationale": (
                    "Turn recurring operating data into a concise weekly exception report with "
                    "traceable links back to source metrics."
                ),
                "impact": "Medium",
                "complexity": "Low",
                "cost_band": "$20k–$60k",
                "time_to_value": "4–8 weeks",
                "kpi": "50% less analyst preparation time",
                "first_step": "Define the five decisions the weekly brief must improve.",
            },
        ],
        "roadmap": [
            {
                "phase": "Days 0–30",
                "title": "Frame the value",
                "action": "Choose one workflow, name an owner, baseline KPIs, and define red lines.",
            },
            {
                "phase": "Days 31–60",
                "title": "Build the evidence",
                "action": "Prototype with a controlled dataset and evaluate quality with real users.",
            },
            {
                "phase": "Days 61–90",
                "title": "Pilot with guardrails",
                "action": "Launch to a small cohort, monitor exceptions, and decide scale or stop.",
            },
        ],
        "risks": [
            {
                "risk": "Unreliable or untraceable answers",
                "mitigation": "Ground outputs in approved sources and require citations for key claims.",
            },
            {
                "risk": "Automation before process clarity",
                "mitigation": "Map exceptions and redesign the workflow before adding an agent.",
            },
            {
                "risk": "Weak adoption",
                "mitigation": "Co-design with end users and measure usage alongside business outcomes.",
            },
        ],
        "research_takeaway": "Live Tavily evidence is disabled in preview mode.",
        "sources": [],
        "mode": "preview",
    }


def _preview_memory_answer(question: str, context: str) -> str:
    if context.startswith("No prior assessment"):
        return (
            "There is no earlier assessment in this workspace yet. Complete the Company Profile "
            "first, then I can reference its score, recommendation, priorities, and cost bands."
        )
    return (
        "In preview mode I can retrieve the saved assessment index, but a live OpenAI key is needed "
        "for a fully reasoned follow-up. Here is the relevant memory I found:\n\n"
        f"{context}\n\n"
        f"Your question was: “{question}”\n\n"
        "Next action: add an OpenAI key in the sidebar, then ask again for a tailored comparison or "
        "implementation decision."
    )
