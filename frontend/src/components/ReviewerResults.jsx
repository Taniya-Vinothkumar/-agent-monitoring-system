
import StatusBadge from "./common/StatusBadge.jsx";

const MARK = {
  pass: "Pass",
  fail: "Fail",
  skipped: "Skipped",
};

export default function ReviewerResults({ review }) {
  if (!review) return null;

  const specialistReviews = review.specialist_reviews || [];

  return (
    <section className="panel" aria-labelledby="review-h">
      <h2 id="review-h">Reviewer results</h2>

      {/* Deterministic reviewer */}
      <p className="verdict-line">
        <StatusBadge status={review.verdict} />

        <span>score {Math.round(review.score * 100)}%</span>

        <span className="muted small">
          {review.reviewer.name} v{review.reviewer.version} (
          {review.reviewer.mode})
        </span>
      </p>

      <ul className="checks">
        {review.checks.map((c) => (
          <li key={c.check_id} className={`check check-${c.status}`}>
            <span className="check-status">{MARK[c.status]}</span>

            <div>
              <div>{c.description}</div>

              <div className="muted small">
                {c.detail}

                {c.evidence_step_ids.length > 0 && (
                  <> (steps {c.evidence_step_ids.join(", ")})</>
                )}
              </div>
            </div>

            <span className="muted small">{c.severity}</span>
          </li>
        ))}
      </ul>

      {/* Deterministic audit */}
      <h3>
        Audit of this review: {review.audit.passed ? "passed" : "failed"}
      </h3>

      <ul className="audit">
        {review.audit.findings.map((f) => (
          <li
            key={f.audit_id}
            className={f.status === "fail" ? "warn-text" : undefined}
          >
            {f.status === "pass" ? "Pass" : "Fail"}: {f.description}{" "}
            <span className="muted small">{f.detail}</span>
          </li>
        ))}
      </ul>

      {/* Specialist AI reviews */}
      <h3>Specialist AI reviews</h3>

      {specialistReviews.length === 0 ? (
        <p className="muted">
          No specialist reviews available for this execution.
        </p>
      ) : (
        <div className="specialist-reviews">
          {specialistReviews.map((specialist, index) => (
            <div
              className="panel"
              key={`${specialist.reviewer}-${specialist.role}-${index}`}
            >
              <h4>
                {specialist.reviewer} ({specialist.role.replace("_", " ")})
              </h4>

              <p className="verdict-line">
                <StatusBadge status={specialist.verdict} />

                <span className="muted small">
                  {specialist.status}
                </span>

                <span className="muted small">
                  {specialist.latency_ms.toFixed(1)} ms
                </span>
              </p>

              <p className="muted small">
                Version: {specialist.version} | Model: {specialist.model}
              </p>

              <p>{specialist.summary}</p>

              <h5>Specialist checks</h5>

              {specialist.checks.length === 0 ? (
                <p className="muted small">No checks returned.</p>
              ) : (
                <ul className="checks">
                  {specialist.checks.map((check) => (
                    <li
                      key={check.check_id}
                      className={`check check-${check.status}`}
                    >
                      <span className="check-status">
                        {MARK[check.status]}
                      </span>
                      <div>{check.detail}</div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Proposed improvements */}
      <h3>Proposed improvements</h3>

      {review.improvements.length === 0 ? (
        <p className="muted">None. No checks failed.</p>
      ) : (
        <ul className="improvements">
          {review.improvements.map((i) => (
            <li key={i.improvement_id}>
              {i.suggestion}

              <div className="muted small">
                For {i.target_check}. Proposal only; needs human approval,
                nothing is applied automatically.
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
