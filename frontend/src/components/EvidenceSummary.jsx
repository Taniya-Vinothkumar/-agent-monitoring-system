export default function EvidenceSummary({ evidence }) {
  if (!evidence) return null;

  return (
    <section className="panel" aria-labelledby="evidence-h">
      <h2 id="evidence-h">Evidence Summary</h2>

      <div className="stats-grid">
        <div>
          <strong>{evidence.total_steps}</strong>
          <p className="muted small">Total Steps</p>
        </div>

        <div>
          <strong>{evidence.tool_call_count}</strong>
          <p className="muted small">Tool Calls</p>
        </div>

        <div>
          <strong>{evidence.error_count}</strong>
          <p className="muted small">Errors</p>
        </div>

        <div>
          <strong>
            {Number(evidence.total_duration_ms).toFixed(2)} ms
          </strong>
          <p className="muted small">Duration</p>
        </div>
      </div>

      <h3>Step Type Counts</h3>

      <ul>
        {Object.entries(evidence.step_type_counts || {}).map(
          ([type, count]) => (
            <li key={type}>
              {type}: {count}
            </li>
          )
        )}
      </ul>

      <h3>Tools Used</h3>

      {evidence.tools_used?.length > 0 ? (
        <ul>
          {evidence.tools_used.map((tool, index) => (
            <li key={`${tool}-${index}`}>{tool}</li>
          ))}
        </ul>
      ) : (
        <p className="muted">No tools used.</p>
      )}

      <h3>Errors</h3>

      {evidence.errors?.length > 0 ? (
        <ul>
          {evidence.errors.map((error, index) => (
            <li key={`${error.step_id}-${index}`}>
              Step {error.step_id}: {error.message}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No execution errors.</p>
      )}

      <h3>Verifiable Claims</h3>

      {evidence.verifiable_claims?.length > 0 ? (
        <ul>
          {evidence.verifiable_claims.map((claim, index) => (
            <li key={`${claim.step_id}-${index}`}>
              Step {claim.step_id} | {claim.kind} | Input: {claim.input}
              | Claimed result: {claim.claimed_result}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No verifiable claims.</p>
      )}

      <h3>Final Answer</h3>

      <p>
        {evidence.has_final_answer
          ? evidence.final_answer
          : "No final answer produced."}
      </p>
    </section>
  );
}