"""Local demonstration API. No network connectors or model calls."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel
from runtime.engine import Engine, WorkflowError


@asynccontextmanager
async def lifespan(application):
    application.state.engine = Engine()
    yield


app = FastAPI(title="Brain Workflow Showcase", lifespan=lifespan)


class Decision(BaseModel):
    approve: bool


@app.get("/")
def home():
    return FileResponse(Path(__file__).parent / "ui.html")


@app.get("/api/health")
def health():
    return {"ok": True, "provider": "offline-fixture", "network_models": False}


@app.get("/api/tasks")
def tasks():
    return app.state.engine.tasks()


@app.get("/api/audit/verify")
def verify():
    return app.state.engine.verify()


@app.get("/api/audit")
def events():
    with app.state.engine.connect() as connection:
        return [dict(row) for row in connection.execute("SELECT seq, ts, kind, run_id FROM audit ORDER BY seq DESC LIMIT 100")]


@app.post("/api/demo/run")
def run_demo():
    try:
        return app.state.engine.start()
    except WorkflowError as error:
        raise HTTPException(400, str(error)) from error


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    try:
        run = app.state.engine.run(run_id)
        return {"run_id": run_id, "state": run["state"], "tasks": app.state.engine.tasks(run_id)}
    except WorkflowError as error:
        raise HTTPException(404, str(error)) from error


@app.post("/api/runs/{run_id}/review")
def review(run_id: str, decision: Decision):
    try:
        run = app.state.engine.decide(run_id, decision.approve)
        return {"run_id": run_id, "state": run["state"], "report_available": run["report"] is not None}
    except WorkflowError as error:
        raise HTTPException(409, str(error)) from error


@app.get("/api/runs/{run_id}/report", response_class=PlainTextResponse)
def report(run_id: str):
    try:
        run = app.state.engine.run(run_id)
    except WorkflowError as error:
        raise HTTPException(404, str(error)) from error
    if run["state"] != "approved" or run["report"] is None:
        raise HTTPException(409, "Report requires human approval")
    return PlainTextResponse(run["report"], headers={"Content-Disposition": 'attachment; filename="synthetic-report.md"'})
