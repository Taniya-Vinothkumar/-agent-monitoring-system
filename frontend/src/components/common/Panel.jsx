
export default function Panel({
  title,
  subtitle,
  children,
  className = "",
}) {
  return (
    <section className={`panel ${className}`}>

      {title && (
        <div className="panel-header">
          <div>
            <h2>{title}</h2>

            {subtitle && (
              <p className="muted small">{subtitle}</p>
            )}
          </div>
        </div>
      )}

      <div className="panel-content">
        {children}
      </div>

    </section>
  );
}
