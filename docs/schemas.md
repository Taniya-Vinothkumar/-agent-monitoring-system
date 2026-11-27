# GuardianLoop M0-A schemas

M0-A freezes versioned contracts without wiring them into the running
application. The active API models, shared schemas, database models, reviewer,
canary runner, and frontend are unchanged in this phase.

Every new persisted domain record uses `schema_version: "1.0"`. The
`execution_trace_v1.json` and `evidence_summary_v1.json` contracts preserve
legacy field names alongside normalized names. Producers must keep the aliases
equal; consumers must prefer the normalized fields when present. The existing
unversioned records remain valid under their existing schemas.

## Reviewer finding and result

`ReviewerFinding` is one individual reviewer's structured finding. It carries
the reviewer identity, role, model and prompt versions, verdict, cited trace
step, evidence quote, and confidence.

`ReviewerResult` is one aggregate result for an execution. It contains zero or
more individual findings, a separate deterministic-verifier result, the
aggregate verdict, execution score, disagreement state, and escalation state.
The verifier is not represented as an AI reviewer finding. Reviewer trust is
not part of this score; it is represented separately by
`reviewer_trust_profile.json`.

The currently persisted reviewer result has a legacy shape. The new
`reviewer_result_v1.json` is the target aggregate contract; no conversion or
API change is performed in M0-A.

## Failure categories and current canary mutations

The five canonical categories are `wrong_tool`, `wrong_calculation`,
`skipped_step`, `invented_fact`, and `safety`.

The mapping for `wrong_arguments` is provisional until the deterministic
oracle validates its task-level ground truth in M2. `incomplete_answer` is
unresolved: its current mutation replaces the final answer text but does not
omit a trace step. A reviewer can identify an incomplete answer, but that alone
does not establish that the failure is a skipped execution step.

The active canary runner currently has five mutation types and no safety
mutation. M0-A defines the `safety` category but does not add or run mutations.
Canary behavior, mapping validation, and isolation tests are deferred to their
implementation milestones.

## Canary source and isolation

A canary record distinguishes:

- `injected_fault`: a mutation applied to a copied source trace;
- `clean_control`: an unmutated copy with no failure category; and
- `replayed_real_failure`: a copy of a stored real failure with its known
  category when ground truth is available.

Each record references both its source trace and its canary-scoped copy. The
copy belongs to the `reviewer_canaries` storage scope and is never a live
execution record. Canary/source metadata belongs to the canary record, not the
trace supplied to a reviewer.

## Patch and configuration boundaries

An agent configuration is versioned and hashed from canonical JSON: UTF-8 JSON
with sorted keys and fixed separators. The hash excludes the `content_hash`
field itself.

A patch contract contains measurable objectives, latency and cost limits,
rollback conditions, affected-task tags, and structured operations restricted
to `instructions`, `tool_routing_rules`, `guardrails`, and
`retrieval_settings`. It cannot contain executable generated code; no generated
code is executed.

The adapter contract is:

- `run_task(task, context=None)`
- `get_config()`
- `apply_config(config_copy)`

`apply_config` may validate or create a candidate configuration only. It must
never activate the candidate or modify the currently active configuration.
Activation and rollback are outside this interface and are deferred to M6.

## Record-to-storage mapping

| Record | Storage |
|---|---|
| Execution trace | Existing `executions.trace` JSON and existing execution JSON artifact. |
| Evidence summary | Existing `executions.evidence` JSON. |
| Legacy reviewer result | Existing `reviews.review` JSON and evaluation JSON artifact. |
| Canonical `ReviewerResult` | Same `reviews.review` JSON when aggregate implementation begins; legacy records are not rewritten in M0-A. |
| `ReviewerFinding` | Nested in its aggregate `ReviewerResult`; no per-finding table. |
| Task | A `tasks` table, created with task-record implementation. |
| Agent config | Versioned JSON artifact; immutable version metadata in `agent_versions`. |
| Version record | An `agent_versions` table, linked to the config artifact and hash. |
| Canary record and copied trace/evidence | A separate `reviewer_canaries` table; never `executions`. |
| Patch contract | A `patch_contracts` table or versioned artifact; no table is created in M0-A. |
| Reviewer trust profile | Dedicated `reviewer_trust_profiles` storage, created with trust-profile implementation. |
| Failure-category mapping | Shared contract only; no runtime record or table. |
| Adapter | Interface only; no persistence. |
| Agent Evolution Log event | Deferred to M6; no M0-A schema or storage. |

These are storage decisions, not M0-A migrations. Tables and artifacts are
created only in their respective implementation milestones. Existing
`executions` and `reviews` columns are not altered.

## Explicitly out of scope

The current task API accepts the `fault_injection` field despite describing it
as test-only. M0-A only documents this behavior; it does not gate, remove, or
otherwise change it. Any change to that behavior requires separate approval.

No runtime schemas, API responses, database tables, sample data, frontend files,
or existing tests are modified by M0-A. M0-B requires separate approval.
