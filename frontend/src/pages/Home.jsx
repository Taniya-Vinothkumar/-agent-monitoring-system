import { useState } from "react";
import Dashboard from "../components/Dashboard.jsx";
import { api } from "../services/api.js";

const FAULTS = [
  { value: "", label: "None (normal run)" },
  { value: "wrong_tool_result", label: "Wrong tool result (test only)" },
  { value: "inconsistent_answer", label: "Inconsistent final answer (test only)" },
];

export default function Home({ items, onOpen, onSubmitted }) {
  const [task, setTask] = useState("What is (12 + 8) * 3 / 4?");
  const [fault, setFault] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.submitTask(task, fault);
      await onSubmitted(result.execution_id);
    } catch (err) {
      setError(`Could not submit task: ${err.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <section className="panel" aria-labelledby="submit-h">
        <h2 id="submit-h">Submit a task</h2>
        <p className="muted small">
          The agent is a rule-based mock. It handles arithmetic (e.g. "What is 6 * 7?") and word counts
          (e.g. "Count the words in: the quick brown fox").
        </p>
        <form onSubmit={submit} className="task-form">
          <label>
            Task
            <input value={task} onChange={(e) => setTask(e.target.value)} maxLength={500} required />
          </label>
          <label>
            Inject fault
            <select value={fault} onChange={(e) => setFault(e.target.value)}>
              {FAULTS.map((f) => (
                <option key={f.value} value={f.value}>{f.label}</option>
              ))}
            </select>
          </label>
          <button type="submit" disabled={busy || !task.trim()}>
            {busy ? "Running…" : "Run and review"}
          </button>
        </form>
        {error && <p className="warn-text" role="alert">{error}</p>}
      </section>

      <Dashboard items={items} onOpen={onOpen} />
    </>
  );
}
