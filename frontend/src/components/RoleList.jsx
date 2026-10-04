import { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function RoleList({ refreshKey }) {
  const [roles, setRoles] = useState(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  const load = () => api.getRoles().then(setRoles).catch((err) => setMessage(err.message))

  useEffect(() => {
    load()
  }, [refreshKey])

  const extract = async () => {
    setBusy(true)
    setMessage('')
    try {
      const data = await api.extractRoles()
      setMessage(data.message)
      setTimeout(load, 3000)
    } catch (err) {
      setMessage(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <h2>Your roles</h2>
      <p className="muted">Extracted from your current resume (includes internships & apprenticeships).</p>
      <button onClick={extract} disabled={busy}>{busy ? 'Extracting...' : 'Re-run extraction'}</button>
      {message && <p className="message">{message}</p>}
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
