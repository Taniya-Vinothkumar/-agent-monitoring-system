import { useEffect, useMemo, useState } from "react";
import ExecutionTrace from "../components/ExecutionTrace.jsx";
import ReviewerResults from "../components/ReviewerResults.jsx";
import TrustScore from "../components/TrustScore.jsx";
import EvidenceSummary from "../components/EvidenceSummary.jsx";
import StatusBadge from "../components/common/StatusBadge.jsx";
import { api, loadBundle } from "../services/api.js";

function classifyExecution(evidence) {
  const kinds = (evidence?.verifiable_claims || []).map((claim) => claim.kind);
  if (evidence?.tools_used?.includes("factual_qa") || evidence?.factual_evidence?.length > 0) return "factual";
  if (kinds.includes("arithmetic")) return "arithmetic";
  if (kinds.includes("word_count")) return "general";
  return "other";
}

export default function Approvals({ items }) {
  const [evidenceMap, setEvidenceMap] = useState({});
  const [evidenceErrors, setEvidenceErrors] = useState({});
  const [filter, setFilter] = useState("all");
  const [selectedIds, setSelectedIds] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [bundle, setBundle] = useState(null);
  const [detailError, setDetailError] = useState(null);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [loadingEvidence, setLoadingEvidence] = useState(true);
  const [authorizing, setAuthorizing] = useState(false);
  const [authorization, setAuthorization] = useState(null);
  const [authorizationError, setAuthorizationError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchEvidence() {
      setLoadingEvidence(true);

      const results = await Promise.all(
        items.filter((item) => !item.is_sample).map(async (item) => {
          try {
            const evidence = await api.getEvidence(item.execution_id);
            return [item.execution_id, evidence, null];
          } catch (error) {
            return [item.execution_id, null, error.message];
          }
        })
      );

      if (cancelled) return;

      const nextEvidence = {};
      const nextErrors = {};

      results.forEach(([id, evidence, error]) => {
        if (evidence) nextEvidence[id] = evidence;
        if (error) nextErrors[id] = error;
      });

      setEvidenceMap(nextEvidence);
      setEvidenceErrors(nextErrors);
      setLoadingEvidence(false);
    }

    fetchEvidence();
    return () => { cancelled = true; };
  }, [items]);

  const categorizedItems = useMemo(() => items.map((item) => {
    const evidence = evidenceMap[item.execution_id];
    const category = classifyExecution(evidence);
    const claims = evidence?.verifiable_claims || [];

    const arithmeticCandidate =
      category === "arithmetic" &&
      item.status === "completed" &&
      item.fault_injection == null &&
      !item.is_sample &&
      claims.length === 1 &&
      evidence?.tools_used?.includes("calculator") &&
      evidence?.has_final_answer === true;

    return { ...item, evidence, category, arithmeticCandidate };
  }), [items, evidenceMap]);

  const visibleItems = categorizedItems.filter(
    (item) => filter === "all" || item.category === filter
  );

  useEffect(() => {
    if (!visibleItems.some((item) => item.execution_id === activeId)) {
      setActiveId(visibleItems[0]?.execution_id || null);
    }
  }, [filter, items, activeId, visibleItems]);

  useEffect(() => {
    if (!activeId) {
      setBundle(null);
      return;
    }

    let cancelled = false;
    setBundle(null);
    setDetailError(null);
    setLoadingDetails(true);

    loadBundle(activeId)
      .then((result) => {
        if (!cancelled) setBundle(result);
      })
      .catch((error) => {
        if (!cancelled) setDetailError(error.message);
      })
      .finally(() => {
        if (!cancelled) setLoadingDetails(false);
      });

    return () => { cancelled = true; };
  }, [activeId]);

  const activeEvidence = activeId ? evidenceMap[activeId] : null;

  const eligibleSelected = selectedIds.filter((id) =>
    categorizedItems.some(
      (item) => item.execution_id === id && item.arithmeticCandidate
    )
  );

  function inspectExecution(id) {
    setActiveId(id);
    document.getElementById("execution-inspection")?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  }

  function toggleSelection(id) {
    setSelectedIds((current) =>
      current.includes(id)
        ? current.filter((value) => value !== id)
        : [...current, id]
    );
    setAuthorization(null);
    setAuthorizationError(null);
  }

  async function authorize() {
    if (eligibleSelected.length < 10 || eligibleSelected.length > 100) return;

    setAuthorizing(true);
    setAuthorization(null);
    setAuthorizationError(null);

    try {
      const result = await api.authorizeReviewers({
        execution_ids: eligibleSelected,
        include_specialists: false,
      });
      setAuthorization(result);
    } catch (error) {
      setAuthorizationError(error.message);
    } finally {
      setAuthorizing(false);
    }
  }

  const categoryLabel = {
    arithmetic: "Arithmetic",
    factual: "Factual QA",
    general: "Text analysis (word count)",
    other: "Other / unclassified",
  };

  if (!items.length) {
    return <p className="muted">No executions available.</p>;
  }

  return (
    <div className="approvals-page">
      <section className="panel">
        <h2>Execution Approvals</h2>
        <p className="muted small">
          Inspect execution categories, evidence and reviewer decisions.
        </p>

        <div className="stats-grid">
          <div>
            <strong>{items.length}</strong>
            <p className="muted small">All executions</p>
          </div>
          <div>
            <strong>{categorizedItems.filter((i) => i.category === "arithmetic").length}</strong>
            <p className="muted small">Arithmetic</p>
          </div>
          <div>
            <strong>{categorizedItems.filter((i) => i.category === "general").length}</strong>
            <p className="muted small">Text analysis</p>
          </div>
          <div>
            <strong>{categorizedItems.filter((i) => i.category === "factual").length}</strong>
            <p className="muted small">Factual QA</p>
          </div>
          <div>
            <strong>{categorizedItems.filter((i) => i.arithmeticCandidate).length}</strong>
            <p className="muted small">Preliminary arithmetic candidates</p>
          </div>
        </div>

        <div className="approval-filters">
          {[
            ["all", "All"],
            ["arithmetic", "Arithmetic"],
            ["factual", "Factual QA"],
            ["general", "Text analysis"],
            ["other", "Other"],
          ].map(([value, label]) => (
            <button
              type="button"
              key={value}
              className={filter === value ? "filter-button active" : "filter-button"}
              onClick={() => setFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>

        {loadingEvidence && (
          <p className="muted">Classifying executions using their evidence...</p>
        )}

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Select</th>
                <th>Execution and task</th>
                <th>Category</th>
                <th>Status</th>
                <th>Verdict</th>
                <th>Eligibility</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {visibleItems.map((item) => (
                <tr key={item.execution_id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(item.execution_id)}
                      disabled={!item.arithmeticCandidate}
                      onChange={() => toggleSelection(item.execution_id)}
                    />
                  </td>
                  <td>
                    <strong>{item.execution_id}</strong>
                    <div className="muted small">{item.task}</div>
                  </td>
                  <td>{categoryLabel[item.category]}</td>
                  <td><StatusBadge status={item.status} /></td>
                  <td><StatusBadge status={item.verdict} /></td>
                  <td>
                    {item.arithmeticCandidate
                      ? "Preliminary candidate"
                      : item.category === "general"
                        ? "Inspection only"
                        : "Not eligible"}
                  </td>
                  <td>
                    <button type="button" onClick={() => inspectExecution(item.execution_id)}>
                      Inspect
                    </button>
                  </td>
                </tr>
              ))}
              {!visibleItems.length && (
                <tr><td colSpan="7">No executions in this category.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <p className="muted small">
          Candidate checks are preliminary. The backend performs strict validation
          before authorization.
        </p>
      </section>

      <section className="panel">
        <h2>Reviewer Authorization</h2>
        <p>
          Selected arithmetic candidates: <strong>{eligibleSelected.length}</strong>
          {" "}/ 10 minimum, 100 maximum.
        </p>

        <button
          type="button"
          onClick={authorize}
          disabled={authorizing || eligibleSelected.length < 10 || eligibleSelected.length > 100}
        >
          {authorizing ? "Authorizing..." : "Run reviewer authorization"}
        </button>

        {eligibleSelected.length < 10 && (
          <p className="muted small">
            At least {10 - eligibleSelected.length} more preliminary arithmetic
            candidates are needed.
          </p>
        )}

        <p className="muted small">
          Text-analysis executions can be inspected, but the current backend
          authorization endpoint accepts clean arithmetic evidence only.
          Word-count evidence does not establish factual correctness.
        </p>

        {authorizationError && (
          <p className="warn-text" role="alert">{authorizationError}</p>
        )}

        {authorization && (
          <div>
            <h3>Authorization response</h3>
            <p>Status: <strong>{authorization.status}</strong></p>
            <p>Source executions: {authorization.source_execution_count}</p>
            <p>Unique source cases: {authorization.unique_source_cases}</p>
            <h3>Canary summary</h3>
            <pre>{JSON.stringify(authorization.canary_summary, null, 2)}</pre>
            <h3>Reliability</h3>
            <pre>{JSON.stringify(authorization.reliability, null, 2)}</pre>
            <h3>Authorization decisions</h3>
            <pre>{JSON.stringify(authorization.authorization_decisions, null, 2)}</pre>
          </div>
        )}
      </section>

      <section className="panel" id="execution-inspection">
        <h2>Execution Inspection</h2>

        <select
          value={activeId || ""}
          onChange={(event) => setActiveId(event.target.value)}
          aria-label="Choose execution to inspect"
        >
          {visibleItems.map((item) => (
            <option key={item.execution_id} value={item.execution_id}>
              {item.execution_id} | {item.task}
            </option>
          ))}
        </select>

        {activeId && evidenceErrors[activeId] && (
          <p className="warn-text" role="alert">
            Evidence unavailable: {evidenceErrors[activeId]}
          </p>
        )}
        {detailError && (
          <p className="warn-text" role="alert">
            Could not load execution: {detailError}
          </p>
        )}
        {loadingDetails && <p className="muted">Loading execution details...</p>}

        {bundle && (
          <>
            <p className="muted small">
              Category: {categoryLabel[classifyExecution(activeEvidence)]}
            </p>
            {bundle.review?.trust && <TrustScore trust={bundle.review.trust} />}
            {bundle.review && <ReviewerResults review={bundle.review} />}
            <EvidenceSummary evidence={activeEvidence} />
            <ExecutionTrace execution={bundle.execution} />
          </>
        )}

        {!activeEvidence && !loadingEvidence && activeId && !evidenceErrors[activeId] && (
          <p className="muted">No evidence available for this execution.</p>
        )}

        {activeEvidence?.verifiable_claims?.some(
          (claim) => claim.kind === "word_count"
        ) && (
          <p className="muted small">
            Word-count evidence verifies text statistics, not the factual correctness
            of a factual answer.
          </p>
        )}
      </section>
    </div>
  );
}

