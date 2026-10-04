import { useEffect, useState } from 'react'
import { api } from '../api.js'

function JobCard({ job, onApply, showApply }) {
  return (
    <div className="job-card">
      <div>
        <strong>{job.title}</strong>
        <span className="muted"> · {job.company}</span>
        <div className="muted small">
          {job.location || 'Unknown location'} · {job.locality}
          {job.job_type ? ` · ${job.job_type}` : ''}
          {job.posted_at ? ` · posted ${new Date(job.posted_at).toLocaleDateString()}` : ''}
          {` · ${job.source}`}
        </div>
      </div>
      <div className="job-actions">
        <a href={job.url} target="_blank" rel="noreferrer">View</a>
        {showApply && <button onClick={() => onApply(job.id)}>Apply</button>}
        {job.status === 'applied' && <span className="badge">applied</span>}
        {job.status === 'archived' && <span className="badge muted">archived</span>}
      </div>
    </div>
  )
}

export default function JobList({ status, refreshKey, onApplied }) {
  const [jobs, setJobs] = useState(null)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState(null)

  const load = () =>
    api.getMatches(status).then(setJobs).catch((err) => setError(err.message))

  useEffect(load, [status, refreshKey])

  const apply = async (id) => {
    setBusyId(id)
    try {
      await api.applyMatch(id)
      onApplied?.()
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div>
      {error && <p className="error">{error}</p>}
      {jobs && jobs.length === 0 && <p className="muted">Nothing here yet.</p>}
      {jobs && jobs.map((job) => (
        <JobCard key={job.id} job={job} onApply={apply} showApply={status === 'available'} />
      ))}
    </div>
  )
}
