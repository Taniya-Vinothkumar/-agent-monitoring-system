import { useEffect, useState } from "react";
import ExecutionTrace from "../components/ExecutionTrace.jsx";
import ReviewerResults from "../components/ReviewerResults.jsx";
import TrustScore from "../components/TrustScore.jsx";
import { VerdictBadge } from "../components/Dashboard.jsx";
import { loadBundle } from "../services/api.js";

export default function Monitoring({ items, selectedId, onSelect }) {
  const activeId = selectedId && items.some((i) => i.execution_id === selectedId)
    ? selectedId
    : items[0]?.execution_id;
  const [bundle, setBundle] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!activeId) return;
    let cancelled = false;
    setBundle(null);
    setError(null);
    loadBundle(activeId)
      .then((b) => !cancelled && setBundle(b))
      .catch((e) => !cancelled && setError(e.message));
    return () => { cancelled = true; };
  }, [activeId]);

  if (!items.length) return <p className="muted">No runs to show yet.</p>;

  return (
    <div className="monitoring">
      <aside aria-label="Runs">
        <ul className="run-list">
          {items.map((i) => (
            <li key={i.execution_id}>
              <button
                className={i.execution_id === activeId ? "run active" : "run"}
                onClick={() => onSelect(i.execution_id)}
                aria-current={i.execution_id === activeId}
              >
                <span className="run-task">{i.task}</span>
                {i.fault_injection && <span className="muted small">test fault: {i.fault_injection}</span>}
                <VerdictBadge verdict={i.verdict} />
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <div className="detail">
        {error && <p className="warn-text" role="alert">Could not load this run: {error}</p>}
        {!bundle && !error && <p className="muted">Loading…</p>}
        {bundle && (
          <>
            <TrustScore trust={bundle.review.trust} />
            <ReviewerResults review={bundle.review} />
            <ExecutionTrace execution={bundle.execution} />
          </>
        )}
      </div>
    </div>
  );
}
