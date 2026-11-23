import { useCallback, useEffect, useState } from "react";
import Home from "./pages/Home.jsx";
import Monitoring from "./pages/Monitoring.jsx";
import { loadExecutions } from "./services/api.js";

const SOURCE_NOTES = {
  loading: "Loading…",
  backend: "Live data from the backend.",
  "sample-empty": "Backend is running but has no runs yet. Showing bundled sample data; submit a task to see live data.",
  "sample-offline": "Backend not reachable. Showing bundled sample data. Start it with: uvicorn backend.app.main:app --port 8000",
};

export default function App() {
  const [page, setPage] = useState("home");
  const [selectedId, setSelectedId] = useState(null);
  const [data, setData] = useState({ items: [], source: "loading", error: null });

  const refresh = useCallback(async () => {
    const next = await loadExecutions();
    setData(next);
    return next;
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const open = (id) => {
    setSelectedId(id);
    setPage("monitoring");
  };

  return (
    <div className="app">
      <header className="topbar">
        <h1>Agent Monitoring</h1>
        <nav aria-label="Primary">
          <button className={page === "home" ? "tab active" : "tab"} onClick={() => setPage("home")}>
            Overview
          </button>
          <button
            className={page === "monitoring" ? "tab active" : "tab"}
            onClick={() => setPage("monitoring")}
          >
            Monitoring
          </button>
        </nav>
      </header>

      <p className={`source source-${data.source}`} role="status">
        {SOURCE_NOTES[data.source]}
      </p>

      <main>
        {page === "home" ? (
          <Home items={data.items} onOpen={open} onSubmitted={async (id) => { await refresh(); open(id); }} />
        ) : (
          <Monitoring items={data.items} selectedId={selectedId} onSelect={setSelectedId} />
        )}
      </main>
    </div>
  );
}
