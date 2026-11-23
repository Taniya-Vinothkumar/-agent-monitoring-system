const short = (value) => {
  if (value == null) return "–";
  const text = JSON.stringify(value);
  return text.length > 120 ? `${text.slice(0, 117)}…` : text;
};

export default function ExecutionTrace({ execution }) {
  if (!execution) return null;
  return (
    <section className="panel" aria-labelledby="trace-h">
      <h2 id="trace-h">Execution trace</h2>
      <p className="task-line">{execution.task}</p>
      <p className="muted small">
        {execution.execution_id}: {execution.status}, {execution.steps.length} steps,{" "}
        {execution.total_duration_ms.toFixed(2)} ms, agent {execution.agent.name} ({execution.agent.mode})
        {execution.fault_injection && <> , test fault injected: <strong>{execution.fault_injection}</strong></>}
      </p>

      <div className="table-wrap">
        <table className="trace-table">
          <thead>
            <tr>
              <th className="num">#</th>
              <th>Type</th>
              <th>Name</th>
              <th>Status</th>
              <th>Input</th>
              <th>Output / error</th>
              <th className="num">ms</th>
            </tr>
          </thead>
          <tbody>
            {execution.steps.map((s) => (
              <tr key={s.step_id} className={s.status === "error" ? "row-error" : undefined}>
                <td className="num">{s.step_id}</td>
                <td>{s.type}</td>
                <td>{s.name}</td>
                <td>{s.status}</td>
                <td><code>{short(s.input)}</code></td>
                <td><code>{s.error ? s.error : short(s.output)}</code></td>
                <td className="num">{s.duration_ms.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="final">
        <span className="muted">Final answer: </span>
        {execution.final_answer ?? <em>none produced</em>}
      </p>
    </section>
  );
}
