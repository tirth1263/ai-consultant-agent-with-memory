import sqlite3

from workflow import (
    ApiCredentials,
    AssessmentStore,
    CompanyProfile,
    ConsultantWorkflow,
    _entity_id,
    build_preview_assessment,
)


def profile() -> CompanyProfile:
    return CompanyProfile(
        company_name="Acme Health",
        industry="Healthcare",
        company_size="201–1,000 employees",
        region="North America",
        business_model="B2B services",
        goals="Reduce administrative work and improve customer response time.",
        constraints="Protected data and a small transformation team.",
        current_tools="Microsoft 365, Salesforce, Snowflake",
        data_maturity="Established",
        ai_experience="Experiments",
        budget="$100k–$250k",
        timeline="This quarter",
        risk_tolerance="Balanced",
    )


def test_preview_assessment_has_complete_portfolio():
    result = build_preview_assessment(profile())

    assert 0 <= result["maturity_score"] <= 100
    assert len(result["use_cases"]) == 3
    assert len(result["roadmap"]) == 3
    assert result["mode"] == "preview"


def test_preview_workflow_persists_and_retrieves_context(tmp_path):
    store = AssessmentStore(tmp_path / "memory.sqlite")
    workflow = ConsultantWorkflow(ApiCredentials(), store)

    result = workflow.run_assessment(profile(), "acme-workspace")
    history = store.list_assessments("acme-workspace")
    answer = workflow.ask_memory("What did we prioritize?", "acme-workspace")

    assert result["recommendation"] in answer
    assert history[0]["company_name"] == "Acme Health"
    assert len(store.list_messages("acme-workspace")) == 2
    with sqlite3.connect(store.db_path) as connection:
        stored_scope = connection.execute(
            "SELECT workspace_id FROM app_assessments LIMIT 1"
        ).fetchone()[0]
    assert stored_scope != "acme-workspace"


def test_entity_id_is_private_stable_and_scoped():
    first = _entity_id("Strategy Team")
    second = _entity_id("strategy team")

    assert first == second
    assert "strategy" not in first
    assert first.startswith("advisory-")
