
const STATUS_LABELS = {
  pass: "Pass",
  needs_attention: "Needs attention",
  fail: "Fail",
};

export default function StatusBadge({ status }) {
  if (!status || !STATUS_LABELS[status]) {
    return (
      <span className="badge badge-none">
        Not reviewed
      </span>
    );
  }

  return (
    <span className={`badge badge-${status}`}>
      {STATUS_LABELS[status]}
    </span>
  );
}
