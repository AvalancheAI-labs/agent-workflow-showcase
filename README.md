# Brain Workflow Showcase

A small, runnable demonstration of an inspectable workflow: compose a task from
versioned roles and skills, dispatch an allowed tool, wait for dependencies,
and require human review before exposing a report.

This edition is independently authored around common workflow concepts. It contains
invented records, a scripted agent fixture, and a local deterministic engine.
It does not contain customer code, customer documents, private integrations,
or original repository history. It is employer-neutral.

## Try it locally

Requires Python 3.12. Run these commands from the repository root:

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt -c constraints.txt
python -m pytest -q
python scripts/check_export.py
python -m uvicorn app:app --host 127.0.0.1 --port 8095
```

Open <http://127.0.0.1:8095> and click **Run synthetic workflow**. Inspect the
two completed task results, then approve or reject the local report.
Approval enables **Download report**. Rejection produces no report.
No credentials or model calls are needed; model cost is zero because no model runs.

The `.env.example` file documents optional settings; the app does not automatically
load it. The default state location is `data/`. Set `BRAIN_ROOT` in your shell to
choose another writable directory.

Expected analyst result:

```json
{"synthetic": true, "records": 3, "currency": "USD", "total_amount": 2500, "won_amount": 1700}
```

Expected workflow state after running: `awaiting_review`. After approval:
`approved`, with a downloadable Markdown report. All examples are fictional.

## Architecture

```text
Versioned role + compatible skill + workspace verb bindings
                         |
                         v
   Analyst fixture ---> local synthetic_sales.summarize (T0)
          |
          | completed task dependency
          v
   Deterministic reviewer checks dependency completion
          |
          v
   Human approves / rejects ---> approved report in SQLite

   Each state change ---> chained SHA-256 audit rows
```

The analyst is a scripted stand-in for an agent tool-use loop. It requests one
allowed tool and formats that tool's output. It does not reason, select tools
autonomously, or assess the business. The reviewer stage is a deterministic
dependency check; the person using the UI makes the approval decision.

See [ARCHITECTURE.md](ARCHITECTURE.md) for boundaries, state transitions, failure
handling, and limitations.

## What is implemented

- YAML role/skill composition with version and role compatibility checks.
- Explicit tool allowlist and a required T0 binding for the local summarizer.
- A fixed, sequential two-node dependency workflow with blocked downstream tasks on failure.
- SQLite state, task definition snapshots, persisted results, and transactional audit events.
- Approval/rejection before report access, with duplicate decisions rejected.
- Audit verification that detects changed retained rows and missing rows within the chain.
- English UI, local API, and synthetic test data.

This is a compact prototype, not the full private platform. It does not implement
live model routing, arbitrary DAG planning, concurrent agent execution, tenant
security, document ingestion, customer knowledge retrieval, production deployment,
or model-quality evaluation. Those are outside this showcase's scope.

## Verification

`python -m pytest -q` exercises behavior, including exact expected totals,
approval and rejection, invalid inputs, failed dependencies, unknown references,
restricted tools, persistence, concurrent requests, audit tampering, and HTTP behavior.
`python scripts/check_export.py` runs a heuristic hygiene scan and parses Python files.
Neither is evidence of model quality or production reliability.

An API-only walkthrough is in [examples/walkthrough.py](examples/walkthrough.py).
It uses the in-process API, blocks external sockets, prints expected totals and
review state, and verifies the audit chain.

## Local use and publication

Bind to loopback. This demo has no authentication, rate limiting, or tenant isolation.
Reports and examples remain local. Audit hashes have no external trust anchor:
an administrator can rewrite the entire chain or truncate its tail undetected.
Do not treat the chain as a security or compliance guarantee.

No open-source license has been selected. Dependency licenses are separate from
the code in this repository. Public visibility alone does not grant a reuse license.
There are no claims about production adoption, cost savings, business impact,
foundation-model training, or executive leadership experience.
