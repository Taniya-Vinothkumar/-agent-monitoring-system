
import { useCallback, useEffect, useState } from "react";
import {
  Sun,
  Moon,
  LayoutDashboard,
  Activity,
  ShieldCheck,
  Bot,
  AlertTriangle,
  ClipboardCheck,
  Settings,
  Radio,
} from "lucide-react";

import Home from "./pages/Home.jsx";
import Monitoring from "./pages/Monitoring.jsx";
import Approvals from "./pages/Approvals.jsx";
import { api, loadExecutions } from "./services/api.js";
import { useTheme } from "./context/ThemeContext.jsx";

const SOURCE_NOTES = {
  loading: "Loading...",
  backend: "Live data from the backend.",
  "sample-empty":
    "Backend is running but has no runs yet. Showing bundled sample data; submit a task to see live data.",
  "sample-offline":
    "Backend not reachable. Showing bundled sample data. Start it with: uvicorn backend.app.main:app --port 8000",
};

export default function App() {
  const [page, setPage] = useState("home");
  const [selectedId, setSelectedId] = useState(null);

  const [data, setData] = useState({
    items: [],
    source: "loading",
    error: null,
  });

  const [healthStatus, setHealthStatus] = useState("checking");
  const [healthApp, setHealthApp] = useState("");

  const { theme, toggleTheme } = useTheme();

  const refresh = useCallback(async () => {
    const next = await loadExecutions();
    setData(next);
    return next;
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    let active = true;

    const checkHealth = async () => {
      try {
        const result = await api.health();

        if (active) {
          setHealthStatus(result.status === "ok" ? "online" : "offline");
          setHealthApp(result.app || "");
        }
      } catch {
        if (active) {
          setHealthStatus("offline");
          setHealthApp("");
        }
      }
    };

    checkHealth();

    const interval = setInterval(checkHealth, 15000);

    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  const open = (id) => {
    setSelectedId(id);
    setPage("monitoring");
  };

  const healthLabel = {
    checking: "CHECKING BACKEND",
    online: "BACKEND ONLINE",
    offline: "BACKEND OFFLINE",
  }[healthStatus];

  const navigation = [
    {
      section: "MAIN MENU",
      items: [
        { id: "home", label: "Overview", icon: LayoutDashboard },
        { id: "monitoring", label: "Monitoring", icon: Activity },
      ],
    },
    {
      section: "GUARDIAN SYSTEM",
      items: [
        { id: "guardian", label: "Guardian Loop", icon: ShieldCheck },
        { id: "agents", label: "Agents", icon: Bot },
        { id: "incidents", label: "Incidents", icon: AlertTriangle },
        { id: "approvals", label: "Approvals", icon: ClipboardCheck },
      ],
    },
    {
      section: "CONFIGURATION",
      items: [
        { id: "settings", label: "Settings", icon: Settings },
      ],
    },
  ];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon">
            <ShieldCheck size={25} />
          </div>

          <div className="brand-text">
            <h2>GUARDIAN</h2>
            <span>AGENT MONITORING</span>
          </div>
        </div>

        <div className="sidebar-status">
          <span className={`status-dot status-${healthStatus}`} />
          SYSTEM CONSOLE
        </div>

        <nav className="sidebar-nav" aria-label="Main navigation">
          {navigation.map((group) => (
            <div className="nav-group" key={group.section}>
              <p className="nav-section-title">{group.section}</p>

              {group.items.map((item) => {
                const Icon = item.icon;

                return (
                  <button
                    key={item.id}
                    className={
                      page === item.id ? "sidebar-link active" : "sidebar-link"
                    }
                    onClick={() => {
                      if (["home", "monitoring", "approvals"].includes(item.id)) {
                        setPage(item.id);
                      }
                    }}
                    disabled={!["home", "monitoring", "approvals"].includes(item.id)}
                    title={
                      !["home", "monitoring", "approvals"].includes(item.id)
                        ? "Coming in a later development step"
                        : item.label
                    }
                  >
                    <Icon size={18} />
                    <span>{item.label}</span>

                    {item.id === "monitoring" && (
                      <span className="nav-count">{data.items.length}</span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <Radio size={15} />
          <span>GUARDIAN CORE</span>
          <span className={`status-dot status-${healthStatus}`} />
        </div>
      </aside>

      <div className="main-area">
        <header className="topbar">
          <div className="page-heading">
            <span className="breadcrumb">GUARDIAN CONSOLE /</span>
            <h1>
              {page === "home" ? "Overview" : page === "approvals" ? "Approvals" : "Monitoring"}
            </h1>
          </div>

          <div className="header-actions">
            <span
              className="system-indicator"
              title={healthApp ? `Application: ${healthApp}` : "Backend health"}
              aria-live="polite"
            >
              <span className={`status-dot status-${healthStatus}`} />
              {healthLabel}
            </span>

            <button
              type="button"
              className="theme-toggle"
              onClick={toggleTheme}
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
              title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            >
              {theme === "dark" ? (
                <Sun size={18} />
              ) : (
                <Moon size={18} />
              )}
              <span>
                {theme === "dark" ? "Light mode" : "Dark mode"}
              </span>
            </button>
          </div>
        </header>

        <div className="content-area">
          <p className={`source source-${data.source}`} role="status">
            {SOURCE_NOTES[data.source]}
          </p>

          <main>
            {page === "home" ? (
              <Home
                items={data.items}
                onOpen={open}
                onSubmitted={async (id) => {
                  await refresh();
                  open(id);
                }}
              />
            ) : page === "approvals" ? (
              <Approvals items={data.items} />
            ) : (
              <Monitoring
                items={data.items}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />
            )}
          </main>
        </div>
      </div>
    </div>
  );
}




