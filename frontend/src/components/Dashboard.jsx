
import StatusBadge from "./common/StatusBadge.jsx";

const pct = (value) => {
  return value == null ? "–" : `${Math.round(value * 100)}%`;
};

export default function Dashboard({ items, onOpen }) {
  const count = (verdict) => {
    return items.filter((item) => item.verdict === verdict).length;
  };

  const scored = items.filter((item) => item.trust_score != null);

  const mean = scored.length
    ? scored.reduce((total, item) => total + item.trust_score, 0) /
      scored.length
    : null;

  return (
    <section aria-labelledby="runs-h">
      <h2 id="runs-h">Agent runs</h2>

      <dl className="stats">
        <div>
          <dt>Runs</dt>
          <dd>{items.length}</dd>
        </div>

        <div>
          <dt>Pass</dt>
          <dd>{count("pass")}</dd>
        </div>

        <div>
          <dt>Needs attention</dt>
          <dd>{count("needs_attention")}</dd>
        </div>

        <div>
          <dt>Fail</dt>
          <dd>{count("fail")}</dd>
        </div>

        <div>
          <dt>Mean trust</dt>
          <dd>{pct(mean)}</dd>
        </div>
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
            {items.map((item) => (
              <tr key={item.execution_id}>
                <td>
                  <button
                    className="link"
                    onClick={() => onOpen(item.execution_id)}
                  >
                    {item.task}
                  </button>

                  {item.is_sample && (
                    <span className="tag">sample</span>
                  )}

                  {item.fault_injection && (
                    <span className="tag">
                      test fault: {item.fault_injection}
                    </span>
                  )}
                </td>

                <td>{item.status}</td>

                <td>
                  <StatusBadge status={item.verdict} />
                </td>

                <td className="num">{pct(item.trust_score)}</td>

                <td className="num">
                  {item.total_duration_ms.toFixed(1)} ms
                </td>

                <td>
                  {new Date(item.created_at).toLocaleString()}
                </td>
              </tr>
            ))}

            {items.length === 0 && (
              <tr>
                <td colSpan="6">No agent runs available yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
