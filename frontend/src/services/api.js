// API client (Person 2). Contract: docs/api_contract.md
// Also bundles the shared sample data so the dashboard works with no backend.
import sampleExecution from "@shared/sample_data/sample_execution.json";
import sampleReview from "@shared/sample_data/sample_review.json";
import sampleExecutionFaulty from "@shared/sample_data/sample_execution_faulty.json";
import sampleReviewFaulty from "@shared/sample_data/sample_review_faulty.json";

const BASE = import.meta.env.VITE_API_BASE_URL || "/api";

async function request(path, options) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

export const api = {
  health: () => request("/health"),
  listExecutions: () => request("/executions"),
  getExecution: (id) => request(`/executions/${encodeURIComponent(id)}`),
  getReview: (id) => request(`/executions/${encodeURIComponent(id)}/review`),
  submitTask: (task, faultInjection) =>
    request("/tasks", {
      method: "POST",
      body: JSON.stringify({ task, fault_injection: faultInjection || null }),
    }),
};

// ---- Sample data ----------------------------------------------------------
const SAMPLES = [
  { execution: sampleExecution, review: sampleReview },
  { execution: sampleExecutionFaulty, review: sampleReviewFaulty },
];

const sampleListItems = () =>
  SAMPLES.map(({ execution, review }) => ({
    execution_id: execution.execution_id,
    task: execution.task,
    status: execution.status,
    created_at: execution.started_at,
    total_duration_ms: execution.total_duration_ms,
    fault_injection: execution.fault_injection ?? null,
    verdict: review.verdict,
    trust_score: review.trust.score,
    is_sample: true,
  }));

/** Live runs if the backend has any; otherwise the bundled samples (and say why). */
export async function loadExecutions() {
  try {
    const items = await api.listExecutions();
    if (items.length > 0) return { items, source: "backend", error: null };
    return { items: sampleListItems(), source: "sample-empty", error: null };
  } catch (err) {
    return { items: sampleListItems(), source: "sample-offline", error: err.message };
  }
}

/** Trace + review for one run, from the samples or the backend. */
export async function loadBundle(id) {
  const sample = SAMPLES.find((s) => s.execution.execution_id === id);
  if (sample) return sample;
  const [execution, review] = await Promise.all([api.getExecution(id), api.getReview(id)]);
  return { execution, review };
}
