import { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function RoleList({ refreshKey, onExtract, extracting }) {
  const [roles, setRoles] = useState(null)
  const [message, setMessage] = useState('')

  const load = () => api.getRoles().then(setRoles).catch((err) => setMessage(err.message))

  useEffect(() => {
    load()
  }, [refreshKey])

  return (
    <div className="card">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">Your roles</h2>
          <p className="mt-1 text-xs text-gray-400">AI-extracted apply targets, incl. internships & apprenticeships.</p>
        </div>
        <button onClick={onExtract} disabled={extracting} className="btn-secondary">
          {extracting ? 'Extracting…' : 'Re-run extraction'}
        </button>
      </div>
      {message && <p className="mt-3 text-sm text-red-600">{message}</p>}
      {roles && roles.length === 0 && (
        <p className="mt-3 text-sm text-gray-500">No roles yet — upload a resume first.</p>
      )}
      {roles && roles.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {roles.map((role) => (
            <span key={role.id} className="rounded-full bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700 ring-1 ring-brand-100">
              {role.title}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
