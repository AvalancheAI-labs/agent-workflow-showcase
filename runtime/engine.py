"""Small offline workflow engine; no customer code, connectors, or model SDKs."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import yaml

PROJECT = Path(__file__).resolve().parent.parent


class WorkflowError(ValueError):
    pass


class Engine:
    def __init__(self, root=None, project=PROJECT):
        self.project = Path(project)
        self.root = Path(root or os.environ.get("BRAIN_ROOT", self.project / "data")).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "workflow.sqlite"
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, state TEXT NOT NULL, report TEXT, created TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, agent TEXT NOT NULL,
                    status TEXT NOT NULL, dependencies TEXT NOT NULL, result TEXT, error TEXT,
                    definition TEXT NOT NULL, FOREIGN KEY(run_id) REFERENCES runs(id)
                );
                CREATE TABLE IF NOT EXISTS audit (
                    seq INTEGER PRIMARY KEY, ts TEXT NOT NULL, run_id TEXT NOT NULL,
                    kind TEXT NOT NULL, detail TEXT NOT NULL, previous TEXT NOT NULL, digest TEXT NOT NULL
                );
            """)
        self.workspace = self.load_yaml("tenants/demo/departments/research/workspaces/sales_review.yaml")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def load_yaml(self, name):
        document = yaml.safe_load((self.project / name).read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise WorkflowError("Definition must be a YAML mapping")
        return document

    def compose(self, name):
        agents = self.workspace.get("agents", {})
        if name not in agents:
            raise WorkflowError("Agent is not in this workspace")
        specification = agents[name]
        role_name, version = specification["role"].split("@v")
        role = self.load_yaml(f"roles/{role_name}.yaml")
        if role["version"] != int(version):
            raise WorkflowError("Role version mismatch")
        skills = []
        for reference in specification.get("skills", []):
            skill_name, skill_version = reference.split("@v")
            skill = self.load_yaml(f"skills/shared/{skill_name}.yaml")
            if skill["version"] != int(skill_version) or role_name not in skill["compatible_with_roles"]:
                raise WorkflowError("Skill version or role compatibility mismatch")
            skills.append(skill)
        bindings = specification.get("tool_bindings", {})
        for tool, binding in bindings.items():
            if tool != "synthetic_sales" or any(verb != "summarize" for verb in binding["verbs"]):
                raise WorkflowError("Tool or verb is not in the local allowlist")
        return {"role": role, "skills": skills, "tools": bindings,
                "system": "\n\n".join([role["system"], *[s["system"] for s in skills]])}

    @staticmethod
    def _timestamp():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _digest(payload):
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def emit(self, connection, run_id, kind, detail):
        # The caller holds a write transaction: sequence allocation and state change are atomic.
        last = connection.execute("SELECT seq,digest FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        seq, previous = (last["seq"] + 1, last["digest"]) if last else (1, "")
        payload = {"seq": seq, "ts": self._timestamp(), "run_id": run_id, "kind": kind,
                   "detail": json.dumps(detail, sort_keys=True), "previous": previous}
        connection.execute("INSERT INTO audit VALUES(?,?,?,?,?,?,?)", (
            payload["seq"], payload["ts"], run_id, kind, payload["detail"], previous, self._digest(payload)))

    def verify(self):
        previous = ""
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM audit ORDER BY seq").fetchall()
        for expected_seq, row in enumerate(rows, 1):
            payload = dict(row)
            digest = payload.pop("digest")
            if row["seq"] != expected_seq or row["previous"] != previous or digest != self._digest(payload):
                return {"ok": False, "total": len(rows), "broken_at": row["seq"]}
            previous = digest
        return {"ok": True, "total": len(rows)}

    def tasks(self, run_id=None):
        with self.connect() as connection:
            if run_id:
                rows = connection.execute("SELECT * FROM tasks WHERE run_id=? ORDER BY rowid", (run_id,)).fetchall()
            else:
                rows = connection.execute("SELECT * FROM tasks ORDER BY rowid DESC LIMIT 100").fetchall()
        return [{"id": r["id"], "run_id": r["run_id"], "agent": r["agent"], "status": r["status"],
                 "result": r["result"], "error": r["error"], "cost_usd": 0,
                 "depends_on": json.loads(r["dependencies"])} for r in rows]

    def summary_tool(self, composed):
        tier = composed["tools"].get("synthetic_sales", {}).get("verbs", {}).get("summarize")
        if tier != "T0":
            raise WorkflowError("Local summarizer requires an explicit T0 binding")
        records = json.loads((self.project / "examples/sales.json").read_text(encoding="utf-8"))
        if not isinstance(records, list) or not records:
            raise WorkflowError("Expected a non-empty synthetic records list")
        for record in records:
            if not isinstance(record, dict) or record.get("stage") not in ("won", "proposal"):
                raise WorkflowError("Invalid synthetic record stage")
            amount = record.get("amount")
            if type(amount) is not int or amount < 0:
                raise WorkflowError("Amounts must be non-negative integer USD values")
        return {"synthetic": True, "records": len(records), "currency": "USD",
                "total_amount": sum(r["amount"] for r in records),
                "won_amount": sum(r["amount"] for r in records if r["stage"] == "won")}

    def start(self):
        run_id = str(uuid.uuid4())
        ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        definitions = [self.compose(name) for name in ("analyst", "reviewer")]
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("INSERT INTO runs VALUES(?,?,?,?)", (run_id, "running", None, self._timestamp()))
            for index, name in enumerate(("analyst", "reviewer")):
                connection.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)", (ids[index], run_id, name,
                    "pending" if index == 0 else "queued", json.dumps([] if index == 0 else [ids[0]]),
                    None, None, json.dumps(definitions[index])))
            self.emit(connection, run_id, "workflow_started", {"tasks": ids, "provider": "offline-fixture"})
        self.advance(run_id)
        return {"run_id": run_id, "tasks": self.tasks(run_id), "audit": self.verify(),
                "state": self.run(run_id)["state"], "synthetic": True}

    def advance(self, run_id):
        # Deliberately sequential deterministic scheduler for this two-node example.
        for task in self.tasks(run_id):
            with self.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute("SELECT * FROM tasks WHERE id=?", (task["id"],)).fetchone()
                if current["status"] not in ("pending", "queued"):
                    continue
                dependencies = json.loads(current["dependencies"])
                if dependencies:
                    upstream = [connection.execute("SELECT status FROM tasks WHERE id=? AND run_id=?",
                        (dependency, run_id)).fetchone() for dependency in dependencies]
                    if any(row is None or row["status"] != "completed" for row in upstream):
                        if any(row is not None and row["status"] == "failed" for row in upstream):
                            connection.execute("UPDATE tasks SET status='blocked',error=? WHERE id=?",
                                               ("upstream task failed", task["id"]))
                            self.emit(connection, run_id, "task_blocked", {"task_id": task["id"]})
                        continue
                connection.execute("UPDATE tasks SET status='running' WHERE id=?", (task["id"],))
                self.emit(connection, run_id, "task_started", {"task_id": task["id"]})
                try:
                    definition = json.loads(current["definition"])
                    if task["agent"] == "analyst":
                        # A scripted agent protocol: request one allowed tool, then format its output.
                        result = self.summary_tool(definition)
                        self.emit(connection, run_id, "tool_completed", {"name": "synthetic_sales.summarize", "result": result})
                        text = "Synthetic sales summary\n" + json.dumps(result, indent=2)
                    else:
                        # Review is a deterministic state check, not an LLM quality evaluation.
                        text = "Dependency check passed. Synthetic summary is ready for human review."
                    connection.execute("UPDATE tasks SET status='completed',result=? WHERE id=?", (text, task["id"]))
                    self.emit(connection, run_id, "task_completed", {"task_id": task["id"]})
                except (WorkflowError, ValueError, KeyError, OSError) as error:
                    connection.execute("UPDATE tasks SET status='failed',error=? WHERE id=?", (str(error), task["id"]))
                    connection.execute("UPDATE runs SET state='failed' WHERE id=?", (run_id,))
                    self.emit(connection, run_id, "task_failed", {"task_id": task["id"], "error": str(error)})
        if all(task["status"] == "completed" for task in self.tasks(run_id)):
            with self.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                changed = connection.execute("UPDATE runs SET state='awaiting_review' WHERE id=? AND state='running'", (run_id,))
                if changed.rowcount:
                    self.emit(connection, run_id, "review_requested", {"operation": "save_local_report"})

    def run(self, run_id):
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise WorkflowError("Unknown workflow run")
        return dict(row)

    def decide(self, run_id, approve):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None or row["state"] != "awaiting_review":
                raise WorkflowError("Run is not awaiting human review")
            state = "approved" if approve else "rejected"
            # Store the authoritative artifact in the same transaction as the decision.
            report = None
            if approve:
                results = connection.execute("SELECT result FROM tasks WHERE run_id=? ORDER BY rowid", (run_id,)).fetchall()
                report = "# Synthetic workflow report\n\n" + "\n\n".join(result["result"] for result in results)
            connection.execute("UPDATE runs SET state=?,report=? WHERE id=?", (state, report, run_id))
            self.emit(connection, run_id, "review_" + state, {"operation": "save_local_report"})
        return self.run(run_id)
