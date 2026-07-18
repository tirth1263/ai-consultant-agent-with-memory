"""Streamlit interface for the AI Consultant Agent with Memori."""

from __future__ import annotations

import base64
import html
import json
import os
import secrets
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from workflow import ApiCredentials, AssessmentStore, CompanyProfile, ConsultantWorkflow

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

st.set_page_config(
    page_title="Northstar — AI Readiness Advisor",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": "https://github.com/tirth1263/ai-consultant-agent-with-memory#readme",
        "Report a bug": "https://github.com/tirth1263/ai-consultant-agent-with-memory/issues",
        "About": "Northstar is an AI readiness consultant powered by OpenAI, Tavily, and Memori v3.",
    },
)


def _asset_text(name: str) -> str:
    return (ROOT / "assets" / name).read_text(encoding="utf-8")


st.markdown(f"<style>{_asset_text('styles.css')}</style>", unsafe_allow_html=True)


def _logo_uri() -> str:
    encoded = base64.b64encode(_asset_text("logo.svg").encode()).decode()
    return f"data:image/svg+xml;base64,{encoded}"


def _secret(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value:
        return value
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return default


def _safe(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


DB_PATH = _secret("SQLITE_DB_PATH", "./memori.sqlite")
MODEL = _secret("OPENAI_MODEL", "gpt-5-mini")
STORE = AssessmentStore(DB_PATH)

if "latest_assessment" not in st.session_state:
    st.session_state.latest_assessment = None
if "latest_company" not in st.session_state:
    st.session_state.latest_company = ""
if "workspace_default" not in st.session_state:
    st.session_state.workspace_default = f"workspace-{secrets.token_hex(4)}"


with st.sidebar:
    st.markdown(
        f"""
        <div class="brand">
          <img src="{_logo_uri()}" alt="Northstar mark" />
          <div><div class="brand-name">Northstar</div><div class="brand-sub">AI ADVISORY SYSTEM</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("#### Engagement workspace")
    workspace_id = st.text_input(
        "Workspace key",
        value=st.session_state.workspace_default,
        help="Use the same private workspace key later to retrieve prior assessments.",
    ).strip()
    if not workspace_id:
        workspace_id = "strategy-team"

    st.markdown("---")
    st.markdown("#### Intelligence services")
    with st.expander("API keys", expanded=False):
        st.caption("Keys are held only for this session and are never written to the database.")
        openai_input = st.text_input(
            "OpenAI API key",
            type="password",
            placeholder="Configured in environment" if _secret("OPENAI_API_KEY") else "sk-…",
        )
        tavily_input = st.text_input(
            "Tavily API key",
            type="password",
            placeholder="Configured in environment" if _secret("TAVILY_API_KEY") else "tvly-…",
        )
        memori_input = st.text_input(
            "Memori API key",
            type="password",
            placeholder="Configured in environment" if _secret("MEMORI_API_KEY") else "memori-…",
        )

    credentials = ApiCredentials(
        openai_api_key=openai_input or _secret("OPENAI_API_KEY"),
        tavily_api_key=tavily_input or _secret("TAVILY_API_KEY"),
        memori_api_key=memori_input or _secret("MEMORI_API_KEY"),
        model=MODEL,
    )
    research_enabled = st.toggle("Use live case-study research", value=True)

    def _status_card(label: str, enabled: bool, note: str) -> None:
        state = "on" if enabled else ""
        st.markdown(
            f"""
            <div class="status-card">
              <div class="status-top"><span class="status-label">{_safe(label)}</span><span class="dot {state}"></span></div>
              <div class="status-note">{_safe(note)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    _status_card("OpenAI reasoning", credentials.live_ai, "Live" if credentials.live_ai else "Preview mode")
    _status_card(
        "Tavily research",
        credentials.live_research and research_enabled,
        "Evidence enabled" if credentials.live_research and research_enabled else "No live sources",
    )
    _status_card("Memori v3", True, "SQLite memory ready")
    st.caption("Cost bands are directional estimates—not vendor quotes.")


workflow = ConsultantWorkflow(credentials, STORE, enable_research=research_enabled)


def section_intro(label: str, title: str, copy: str) -> None:
    st.markdown(
        f"""
        <div class="section-label">{_safe(label)}</div>
        <div class="section-title">{_safe(title)}</div>
        <div class="section-copy">{_safe(copy)}</div>
        """,
        unsafe_allow_html=True,
    )


def render_assessment(result: dict[str, Any], company_name: str) -> None:
    score = int(result.get("maturity_score", 0))
    st.markdown(
        f"""
        <div class="result-hero">
          <div class="result-grid">
            <div class="score-ring" style="--score:{score}"><div class="score-number">{score}<small>/100</small></div></div>
            <div>
              <div class="decision">{_safe(result.get('recommendation'))}</div>
              <h2>{_safe(result.get('headline'))}</h2>
              <p>{_safe(result.get('executive_summary'))}</p>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    dimensions = result.get("dimensions", {})
    cards = "".join(
        f"""
        <div class="metric-card">
          <div class="metric-name">{_safe(name)}</div>
          <div class="metric-value">{int(dimensions.get(name, 0))}</div>
          <div class="metric-bar"><div class="metric-fill" style="width:{int(dimensions.get(name, 0))}%"></div></div>
        </div>
        """
        for name in ("strategy", "data", "technology", "people")
    )
    st.markdown(f'<div class="metric-grid">{cards}</div>', unsafe_allow_html=True)

    section_intro(
        "Priority portfolio",
        "Three moves worth testing",
        "Ranked for fit, achievable value, and an honest path to implementation.",
    )
    use_cases = result.get("use_cases", [])[:3]
    columns = st.columns(3)
    for index, (column, case) in enumerate(zip(columns, use_cases, strict=False), start=1):
        with column:
            st.markdown(
                f"""
                <div class="use-case">
                  <div class="use-case-rank">0{index}</div>
                  <h3>{_safe(case.get('title'))}</h3>
                  <p>{_safe(case.get('rationale'))}</p>
                  <span class="tag green">{_safe(case.get('impact'))} impact</span>
                  <span class="tag">{_safe(case.get('complexity'))} complexity</span>
                  <span class="tag">{_safe(case.get('cost_band'))}</span>
                  <p><strong>Time to value:</strong> {_safe(case.get('time_to_value'))}<br/>
                  <strong>Success:</strong> {_safe(case.get('kpi'))}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            with st.expander("First move"):
                st.write(case.get("first_step", "Define the pilot and its owner."))

    section_intro(
        "90-day activation",
        "From decision to evidence",
        "A staged plan designed to earn the right to scale.",
    )
    roadmap_rows = "".join(
        f"""
        <div class="roadmap-row">
          <div class="roadmap-day">{_safe(item.get('phase'))}</div>
          <div><h4>{_safe(item.get('title'))}</h4><p>{_safe(item.get('action'))}</p></div>
        </div>
        """
        for item in result.get("roadmap", [])[:3]
    )
    st.markdown(f'<div class="roadmap">{roadmap_rows}</div>', unsafe_allow_html=True)

    left, right = st.columns([1, 1])
    with left:
        st.markdown("#### Risks to manage")
        for item in result.get("risks", [])[:3]:
            with st.expander(str(item.get("risk", "Delivery risk"))):
                st.write(item.get("mitigation", "Assign an owner and monitor the risk."))
    with right:
        st.markdown("#### Research signal")
        st.write(result.get("research_takeaway", "No research synthesis was returned."))
        sources = result.get("sources", [])
        if sources:
            for source in sources[:4]:
                st.markdown(
                    f"""
                    <div class="source-card">
                      <a href="{_safe(source.get('url'))}" target="_blank">{_safe(source.get('title'))} ↗</a>
                      <p>{_safe(source.get('content'))}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.caption("No live Tavily sources were used for this preview.")

    payload = json.dumps(
        {"company": company_name, "generated_by": "Northstar", "assessment": result},
        indent=2,
        ensure_ascii=False,
    )
    st.download_button(
        "Download assessment (JSON)",
        payload,
        file_name=f"{company_name.lower().replace(' ', '-')}-ai-readiness.json",
        mime="application/json",
        use_container_width=False,
    )


st.markdown(
    """
    <div class="hero">
      <div class="eyebrow">Decision intelligence for practical AI adoption</div>
      <h1>Turn AI ambition into an <span class="accent">executable portfolio.</span></h1>
      <p>Assess readiness, pressure-test use cases, bring in relevant market evidence, and keep the engagement context alive across every follow-up.</p>
      <div class="pill-row"><span class="pill dark">AI readiness</span><span class="pill">Use-case economics</span><span class="pill">Live research</span><span class="pill">Long-term memory</span></div>
    </div>
    """,
    unsafe_allow_html=True,
)

if not credentials.live_ai:
    st.markdown(
        """
        <div class="mode-banner"><div class="mode-icon">✦</div><div><strong>Interactive preview is on.</strong><br/>You can complete the full experience with deterministic sample analysis. Add your keys in the sidebar to activate live OpenAI reasoning, Tavily research, and Memori augmentation.</div></div>
        """,
        unsafe_allow_html=True,
    )

assessment_tab, memory_tab, about_tab = st.tabs(["01  Assessment", "02  Memory room", "03  How it works"])

with assessment_tab:
    section_intro(
        "Company profile",
        "Give the advisor enough context to be useful",
        "Specific operating constraints produce better recommendations than broad innovation goals.",
    )

    with st.form("assessment_form"):
        col1, col2 = st.columns(2)
        with col1:
            company_name = st.text_input("Company name", placeholder="e.g. Acme Manufacturing")
            industry = st.selectbox(
                "Industry",
                [
                    "Technology",
                    "Financial services",
                    "Healthcare",
                    "Retail & e-commerce",
                    "Manufacturing",
                    "Professional services",
                    "Media & entertainment",
                    "Public sector",
                    "Other",
                ],
            )
            company_size = st.selectbox(
                "Company size",
                ["1–50 employees", "51–200 employees", "201–1,000 employees", "1,001–5,000 employees", "5,000+ employees"],
            )
            region = st.text_input("Primary region", value="North America")
            business_model = st.text_area(
                "Business model",
                placeholder="What do you sell, to whom, and how do you make money?",
                height=105,
            )
        with col2:
            goals = st.text_area(
                "Top business goals",
                placeholder="What outcomes should AI help improve over the next 12 months?",
                height=105,
            )
            constraints = st.text_area(
                "Constraints & non-negotiables",
                placeholder="Budget, regulation, security, capacity, change fatigue…",
                height=105,
            )
            current_tools = st.text_area(
                "Current data & software stack",
                placeholder="CRM, ERP, data warehouse, collaboration tools…",
                height=105,
            )

        st.markdown("##### Readiness signals")
        a, b, c = st.columns(3)
        with a:
            data_maturity = st.select_slider(
                "Data maturity", ["Early", "Developing", "Established", "Advanced"], value="Developing"
            )
            budget = st.selectbox("Indicative pilot budget", ["Under $50k", "$50k–$100k", "$100k–$250k", "$250k+"])
        with b:
            ai_experience = st.select_slider(
                "AI experience", ["None yet", "Experiments", "One live use case", "Scaled program"], value="Experiments"
            )
            timeline = st.selectbox("Desired start", ["This month", "This quarter", "Within 6 months", "Exploring only"])
        with c:
            risk_tolerance = st.select_slider(
                "Change appetite", ["Conservative", "Balanced", "Bold"], value="Balanced"
            )
            st.write("")
            st.caption("You will receive a score, priority portfolio, cost bands, risks, and a 90-day plan.")

        submitted = st.form_submit_button("Build my AI readiness brief  →", use_container_width=True)

    if submitted:
        if not company_name.strip() or not goals.strip():
            st.error("Add a company name and at least one business goal to continue.")
        else:
            profile = CompanyProfile(
                company_name=company_name.strip(),
                industry=industry,
                company_size=company_size,
                region=region.strip() or "Not specified",
                business_model=business_model.strip() or "Not specified",
                goals=goals.strip(),
                constraints=constraints.strip() or "Not specified",
                current_tools=current_tools.strip() or "Not specified",
                data_maturity=data_maturity,
                ai_experience=ai_experience,
                budget=budget,
                timeline=timeline,
                risk_tolerance=risk_tolerance,
            )
            try:
                with st.spinner("Synthesizing readiness, economics, evidence, and next moves…"):
                    result = workflow.run_assessment(profile, workspace_id)
                st.session_state.latest_assessment = result
                st.session_state.latest_company = profile.company_name
            except Exception as exc:
                st.error(f"The live assessment could not complete: {exc}")
                st.info("Check the sidebar keys, or remove the OpenAI key to explore preview mode.")

    if st.session_state.latest_assessment:
        render_assessment(st.session_state.latest_assessment, st.session_state.latest_company)
    else:
        st.markdown(
            """
            <div class="empty-state"><div class="symbol">⌁</div><h3>Your decision brief will appear here</h3><div>Complete the profile to generate a focused portfolio and 90-day activation plan.</div></div>
            """,
            unsafe_allow_html=True,
        )

with memory_tab:
    section_intro(
        "Memori v3 workspace",
        "Continue the engagement without starting over",
        "Ask about earlier recommendations, compare cost bands, or test how a new constraint changes the plan.",
    )
    history = STORE.list_assessments(workspace_id)
    if history:
        st.markdown(f"**{len(history)} saved assessment{'s' if len(history) != 1 else ''} in this workspace**")
        for item in history[:5]:
            result = item["result"]
            with st.expander(
                f"{item['company_name']} · {result.get('maturity_score', '—')}/100 · {item['created_at'][:10]}"
            ):
                st.write(result.get("headline", "No summary available."))
                st.caption("Priority use cases")
                for case in result.get("use_cases", [])[:3]:
                    st.write(f"• {case.get('title')} — {case.get('cost_band')}")
    else:
        st.info("No assessment is stored under this workspace key yet.")

    st.markdown("#### Ask the engagement memory")
    for message in STORE.list_messages(workspace_id):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if question := st.chat_input("What did we recommend, and what should we do first?"):
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            try:
                with st.spinner("Recalling the engagement…"):
                    answer = workflow.ask_memory(question, workspace_id)
                st.markdown(answer)
            except Exception as exc:
                st.error(f"Memory follow-up failed: {exc}")

with about_tab:
    section_intro(
        "System design",
        "Research, reasoning, and memory—each with a clear job",
        "Northstar is intentionally small enough to understand and extend.",
    )
    one, two, three = st.columns(3)
    with one:
        st.markdown("### 01 · Research")
        st.write("Tavily retrieves recent case studies and implementation evidence tailored to the company profile.")
    with two:
        st.markdown("### 02 · Reasoning")
        st.write("OpenAI turns company context and evidence into a structured readiness decision and portfolio.")
    with three:
        st.markdown("### 03 · Memory")
        st.write("Memori v3 instruments the model client; SQLite keeps a durable local engagement record.")
    st.markdown("---")
    st.markdown("#### Privacy and operating notes")
    st.write(
        "API keys entered in the sidebar stay in the current Streamlit session and are not saved by the app. "
        "Assessment content is stored in the configured SQLite database under a hashed workspace identity. "
        "For a multi-tenant production deployment, replace local SQLite with a managed database and add authentication."
    )
    st.link_button(
        "View the source on GitHub ↗",
        "https://github.com/tirth1263/ai-consultant-agent-with-memory",
    )
