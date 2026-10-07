# Architecture and boundaries

## Components

| Component | Responsibility | Boundary |
| --- | --- | --- |
| `app.py` | Local FastAPI routes and report access | No auth; run on loopback |
| `runtime/engine.py` | Composition, execution, state, approval, audit | Fixed sequential workflow, no model SDK |
| `roles/`, `skills/`, `tenants/` | Versioned definitions and tool bindings | Trusted local files, not untrusted uploads |
| `examples/sales.json` | Three invented records | Non-negative integer USD amounts |
| `ui.html` | Inspect results, decide, download | Text rendered through `textContent` |
| `tests/` | Reproducible behavioral checks | No external model or service dependencies |

The YAML layout illustrates organization/department/workspace scoping; the engine
loads one fixed workspace. It does not provide multi-tenant authorization.
Role and skill prompts are composed and snapshotted to show where a future model
adapter could receive instructions. The scripted fixture does not interpret them.
Definitions and records are operator-controlled, local inputs.

## Execution and state

1. Load the analyst and reviewer definitions; reject missing agents, wrong versions,
   incompatible skills, or tools outside the local allowlist.
2. Create a run and two tasks in SQLite. The analyst starts pending and the reviewer
   starts queued with the analyst task ID as its dependency.
3. Transition the analyst to running; execute the local allowed summarizer; persist
   its result and completion event in a write transaction.
4. Release the reviewer only when its dependency is completed. This stage checks
   dependency state, not content accuracy or model quality.
5. Set the run to `awaiting_review`. Approval stores a Markdown report in SQLite;
   rejection keeps the report empty. The API rejects repeated decisions.

Tasks follow `pending/queued -> running -> completed/failed`; a failed upstream task
causes its downstream task to become `blocked`. Runs follow
`running -> awaiting_review -> approved/rejected`, or `running -> failed`.

The approved report is an artifact stored in the same database transaction as its
approval. Downloading produces a Markdown file; no external publication occurs.
The database is the source of truth after page reload or process restart.

## Failure behavior

Malformed record stages, invalid amounts, missing files, and tool errors are
recorded as task failures. A reviewer cannot run after an upstream failure, and
a failed run cannot be approved. Unknown runs and premature report downloads
produce explicit HTTP errors. Missing dependencies stay queued.

The sequential workflow runs synchronously within one request. Each task update
and its audit events commit together. A process crash between tasks can leave a
run unfinished; this prototype has no automatic recovery, retry, or resume route.
Start a new synthetic run after a crash. It has no SLA, distributed locks, general
cycle detection, background queue, or exactly-once external side effects.

Concurrent demonstration runs use SQLite write transactions to serialize state
updates and audit sequence allocation. This does not establish scale readiness.

## Agent versus deterministic logic

The agent fixture makes a predeclared tool request and formats a known result.
The tool calculates totals deterministically. The reviewer checks a dependency
deterministically. The user supplies the actual human decision. There is no live
LLM, autonomous plan generation, learned behavior, or model-quality benchmark.

Adding a real model later would require a separate adapter, explicit data handling,
budget and timeout controls, provider failure tests, and a quality evaluation set.
These are possible extensions, not implemented capabilities.

## Audit limits

Each row hashes canonical serialized fields plus the previous row's digest.
Verification checks sequence continuity, previous-digest linkage, and each digest.
It detects edits to retained rows and internal deletion. There is no signing key,
immutable storage, external checkpoint, or independent timestamp authority.
Complete rewriting and tail truncation cannot be reliably detected by this design.

No secrets, model credentials, remote database addresses, email sending, CRM calls,
or customer identity are required by this example.
