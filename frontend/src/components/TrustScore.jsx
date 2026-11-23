const pct = (v) => `${Math.round(v * 100)}%`;

/** Trust as a point plus its 95% range on a 0-100% scale, not a bare number. */
export default function TrustScore({ trust }) {
  if (!trust) return null;
  const tone = trust.score >= 0.85 ? "high" : trust.score >= 0.6 ? "mid" : "low";
  const label = `Trust ${pct(trust.score)}, 95% range ${pct(trust.lower)} to ${pct(trust.upper)}`;

  return (
    <section className="panel trust" aria-labelledby="trust-h">
      <h2 id="trust-h">Trust</h2>
      <div className="trust-readout">
        <span className={`trust-value tone-${tone}`}>{pct(trust.score)}</span>
        <span className="muted">
          range {pct(trust.lower)}–{pct(trust.upper)} from {trust.n_checks} checks
        </span>
      </div>

      <div className="meter" role="img" aria-label={label}>
        <div className="meter-band" style={{ left: `${trust.lower * 100}%`, width: `${(trust.upper - trust.lower) * 100}%` }} />
        <div className={`meter-point tone-bg-${tone}`} style={{ left: `${trust.score * 100}%` }} />
      </div>
      <div className="meter-scale" aria-hidden="true">
        <span>0</span><span>50%</span><span>100%</span>
      </div>

      {trust.critical_failure_cap_applied && (
        <p className="warn-text">A critical check failed, so trust is capped at 50%.</p>
      )}
      {trust.audit_penalty_applied && (
        <p className="warn-text">The review failed its own audit, so trust is capped at 50%.</p>
      )}
      <p className="muted small">
        Method: {trust.method}. This estimate has not been calibrated against ground truth yet.
      </p>
    </section>
  );
}
