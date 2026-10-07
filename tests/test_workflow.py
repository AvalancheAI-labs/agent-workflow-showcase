import json
import shutil
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from runtime.engine import Engine, PROJECT, WorkflowError


@pytest.fixture
def engine(tmp_path):
    return Engine(tmp_path / "state")


def test_synthetic_flow_and_review_gate(engine):
    result = engine.start()
    assert result["state"] == "awaiting_review"
    analyst, reviewer = result["tasks"]
    assert analyst["status"] == reviewer["status"] == "completed"
    assert reviewer["depends_on"] == [analyst["id"]]
    summary = json.loads(analyst["result"].split("\n", 1)[1])
    assert summary == {"synthetic": True, "records": 3, "currency": "USD", "total_amount": 2500, "won_amount": 1700}
    assert engine.run(result["run_id"])["report"] is None
    approved = engine.decide(result["run_id"], True)
    assert approved["state"] == "approved"
    assert "1700" in approved["report"]
    assert engine.verify()["ok"]
    with pytest.raises(WorkflowError):
        engine.decide(result["run_id"], True)


def test_rejection_produces_no_report(engine):
    run = engine.start()
    assert engine.decide(run["run_id"], False)["report"] is None
    with pytest.raises(WorkflowError):
        engine.decide(run["run_id"], True)


def test_tampering_is_detected(engine):
    engine.start()
    with engine.connect() as connection:
        connection.execute("UPDATE audit SET kind='altered' WHERE seq=2")
    assert engine.verify()["broken_at"] == 2


def test_dependency_failure_blocks_reviewer(engine, monkeypatch):
    def broken_tool(_):
        raise WorkflowError("Synthetic tool failure")
    monkeypatch.setattr(engine, "summary_tool", broken_tool)
    result = engine.start()
    assert result["state"] == "failed"
    assert [t["status"] for t in result["tasks"]] == ["failed", "blocked"]
    with pytest.raises(WorkflowError):
        engine.decide(result["run_id"], True)
    assert engine.verify()["ok"]


def test_missing_dependency_does_not_execute(engine):
    run = engine.start()
    with engine.connect() as connection:
        connection.execute("UPDATE tasks SET status='queued', dependencies='[\"absent\"]',result=NULL WHERE run_id=? AND agent='reviewer'", (run["run_id"],))
    engine.advance(run["run_id"])
    assert engine.tasks(run["run_id"])[1]["status"] == "queued"


def test_tool_allowlist_and_tiers(engine):
    definition = engine.compose("analyst")
    definition["tools"]["synthetic_sales"]["verbs"]["summarize"] = "T2"
    with pytest.raises(WorkflowError, match="T0"):
        engine.summary_tool(definition)
    engine.workspace["agents"]["analyst"]["tool_bindings"] = {"external": {"verbs": {"send": "T0"}}}
    with pytest.raises(WorkflowError, match="allowlist"):
        engine.compose("analyst")


@pytest.mark.parametrize("amount", [-1, 2.5, True, "1200"])
def test_invalid_records_fail_without_downstream_execution(tmp_path, amount):
    project = tmp_path / "project"
    for directory in ("examples", "roles", "skills", "tenants"):
        shutil.copytree(PROJECT / directory, project / directory)
    (project / "examples/sales.json").write_text(json.dumps([{"stage": "won", "amount": amount}]))
    engine = Engine(tmp_path / "state", project)
    run = engine.start()
    assert [task["status"] for task in run["tasks"]] == ["failed", "blocked"]


def test_state_persists_and_concurrent_runs_keep_chain_intact(engine):
    with ThreadPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(lambda _: engine.start(), range(4)))
    assert len({run["run_id"] for run in runs}) == 4
    fresh = Engine(engine.root)
    assert len(fresh.tasks()) == 8
    assert fresh.verify()["ok"]


def test_unknown_agent_and_version_mismatch(engine):
    with pytest.raises(WorkflowError):
        engine.compose("not-installed")
    engine.workspace["agents"]["analyst"]["role"] = "analyst@v999"
    with pytest.raises(WorkflowError, match="version"):
        engine.compose("analyst")


def test_http_contract_and_report_requires_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_ROOT", str(tmp_path / "http-state"))
    from app import app
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/health").json()["network_models"] is False
        result = client.post("/api/demo/run").json()
        run_id = result["run_id"]
        assert client.get(f"/api/runs/{run_id}/report").status_code == 409
        assert client.post(f"/api/runs/{run_id}/review", json={"approve": True}).json()["state"] == "approved"
        report = client.get(f"/api/runs/{run_id}/report")
        assert report.status_code == 200 and "1700" in report.text
        assert client.get("/api/audit/verify").json()["ok"]
        assert client.post("/api/runs/unknown/review", json={"approve": True}).status_code == 409
        assert client.get("/api/runs/unknown").status_code == 404
