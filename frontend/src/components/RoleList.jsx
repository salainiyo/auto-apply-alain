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
      <h2>Your roles</h2>
      <p className="muted">Extracted from your current resume (includes internships & apprenticeships).</p>
      <button onClick={onExtract} disabled={extracting}>
        {extracting ? 'Extracting...' : 'Re-run extraction'}
      </button>
      {message && <p className="error">{message}</p>}
      {roles && roles.length === 0 && <p className="muted">No roles yet — upload a resume and run extraction.</p>}
      {roles && roles.length > 0 && (
        <ul>
          {roles.map((role) => (
            <li key={role.id}>
              <strong>{role.title}</strong>
              {role.keywords && <span className="muted"> — {role.keywords}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
