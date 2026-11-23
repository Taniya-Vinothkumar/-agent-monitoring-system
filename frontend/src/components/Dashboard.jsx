const VERDICT_LABEL = { pass: "Pass", needs_attention: "Needs attention", fail: "Fail" };

export function VerdictBadge({ verdict }) {
  if (!verdict) return <span className="badge badge-none">Not reviewed</span>;
  return <span className={`badge badge-${verdict}`}>{VERDICT_LABEL[verdict]}</span>;
}

const pct = (v) => (v == null ? "–" : `${Math.round(v * 100)}%`);

export default function Dashboard({ items, onOpen }) {
  const count = (v) => items.filter((i) => i.verdict === v).length;
  const scored = items.filter((i) => i.trust_score != null);
  const mean = scored.length ? scored.reduce((a, i) => a + i.trust_score, 0) / scored.length : null;

  return (
    <section aria-labelledby="runs-h">
      <h2 id="runs-h">Agent runs</h2>
      <dl className="stats">
        <div><dt>Runs</dt><dd>{items.length}</dd></div>
        <div><dt>Pass</dt><dd>{count("pass")}</dd></div>
        <div><dt>Needs attention</dt><dd>{count("needs_attention")}</dd></div>
        <div><dt>Fail</dt><dd>{count("fail")}</dd></div>
        <div><dt>Mean trust</dt><dd>{pct(mean)}</dd></div>
      </dl>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Task</th>
              <th>Run</th>
              <th>Review</th>
              <th className="num">Trust</th>
              <th className="num">Duration</th>
              <th>Started</th>
            </tr>
          </thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.execution_id}>
                <td>
                  <button className="link" onClick={() => onOpen(i.execution_id)}>{i.task}</button>
                  {i.is_sample && <span className="tag">sample</span>}
                  {i.fault_injection && <span className="tag">test fault: {i.fault_injection}</span>}
                </td>
                <td>{i.status}</td>
                <td><VerdictBadge verdict={i.verdict} /></td>
                <td className="num">{pct(i.trust_score)}</td>
                <td className="num">{i.total_duration_ms.toFixed(1)} ms</td>
                <td>{new Date(i.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
