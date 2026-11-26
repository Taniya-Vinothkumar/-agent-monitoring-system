
import { Activity } from "lucide-react";

export default function StatCard({
  title,
  value,
  subtitle,
  icon: Icon = Activity,
  status = "info",
}) {
  return (
    <article className={`stat-card stat-${status}`}>
      <div className="stat-card-header">
        <span className="stat-card-title">{title}</span>

        <span className="stat-card-icon">
          <Icon size={20} />
        </span>
      </div>

      <div className="stat-card-value">
        {value ?? "—"}
      </div>

      {subtitle && (
        <div className="stat-card-subtitle">
          {subtitle}
        </div>
      )}
    </article>
  );
}
