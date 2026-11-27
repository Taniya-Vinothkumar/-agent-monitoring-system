# GuardianLoop M1 agent and world

The M1 runtime loads `backend/app/agent/config/guardian_agent_v1.json` and
validates it against the frozen `shared/schemas/agent_config.json` contract.
Its `content_hash` is SHA-256 over canonical UTF-8 JSON with sorted keys,
separators `,` and `:`, and the `content_hash` field omitted. `apply_config`
validates and stores a candidate only; it never changes the active config.

The trusted tool registry contains exactly six tools:

1. Business database query
2. Policy document search
3. Calculator/date operations
4. Text extraction
5. Notes and memory
6. Protected-record access

Each tool has its own deterministic checker. Protected-record access checks the
principal roles inside the tool and returns no record when the required role is
absent. The planner is not an authorization boundary.

Unsupported tasks complete with an explicit `UNVERIFIED:` answer and a
`verification_status: "unverified"` plan-step output. The current reviewer
continues to receive and score the run using its existing behavior. Starting
in M2, task-set benchmark aggregation must exclude tasks tagged `unsupported`
from benchmark score denominators and report them separately. Reviewer scores
are not benchmark denominators and are not changed by this rule.

The adapter emits an M0-A v1 trace containing the legacy step fields and their
normalized aliases. The existing API/database trace is reconstructed from
those legacy fields without changing its schema. When JSON persistence is
enabled, the legacy artifact remains at its existing location and a separate
v1 artifact is written under `executions_v1/`.

The six-tool mock world is deterministic static data. No model-generated code
is produced or executed; an Ollama response can only select a registered tool
and provide validated JSON arguments.
