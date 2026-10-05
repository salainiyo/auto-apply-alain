export function Logo({ className = 'text-xl' }) {
  return (
    <span className={`inline-flex items-center gap-2 font-bold tracking-tight ${className}`}>
      <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand-600 text-white">AA</span>
      <span>
        auto-<span className="text-brand-600">apply</span>
      </span>
    </span>
  )
}

export function StatCard({ label, value, hint }) {
  return (
    <div className="card">
      <p className="text-sm font-medium text-gray-500">{label}</p>
      <p className="mt-1 text-3xl font-bold tracking-tight">{value}</p>
      {hint && <p className="mt-1 text-xs text-gray-400">{hint}</p>}
    </div>
  )
}

export function EmptyState({ title, action, onAction }) {
  return (
    <div className="rounded-xl border border-dashed border-gray-200 p-8 text-center">
      <p className="text-sm text-gray-500">{title}</p>
      {action && (
        <button onClick={onAction} className="btn-primary mt-3">
          {action}
        </button>
      )}
    </div>
  )
}
