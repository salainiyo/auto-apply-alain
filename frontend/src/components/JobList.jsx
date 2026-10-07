import { useEffect, useState } from 'react'
import { api } from '../api.js'

function localityBadge(locality) {
  return locality === 'remote' ? <span className="badge-remote">remote</span> : <span className="badge-local">local</span>
}

function mechanismBadge(mechanism) {
  if (mechanism === 'auto') return <span className="badge bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100">auto-apply</span>
  if (!mechanism || mechanism === 'unknown') return null
  return <span className="badge bg-gray-100 text-gray-600">manual only</span>
}

function attemptBadge(status) {
  if (status === 'pending' || status === 'running') return <span className="badge bg-amber-50 text-amber-700 ring-1 ring-amber-100">applying…</span>
  if (status === 'failed') return <span className="badge bg-red-50 text-red-700 ring-1 ring-red-100">auto-apply failed</span>
  if (status === 'manual_required') return <span className="badge bg-gray-100 text-gray-600">needs manual apply</span>
  return null
}

function JobCard({ job, onApply, onApplyAuto, showApply, autoPending }) {
  const [letterMsg, setLetterMsg] = useState('')
  const inFlight = autoPending || job.apply_status === 'pending' || job.apply_status === 'running'

  const copyLetter = async () => {
    try {
      const app = await api.getApplication(job.id)
      if (!app.cover_letter) {
        setLetterMsg('no letter yet')
        return
      }
      try {
        await navigator.clipboard.writeText(app.cover_letter)
        setLetterMsg('copied ✓')
      } catch {
        window.prompt('Copy your cover letter:', app.cover_letter)
        setLetterMsg('copied ✓')
      }
      setTimeout(() => setLetterMsg(''), 3000)
    } catch {
      setLetterMsg('could not load letter')
      setTimeout(() => setLetterMsg(''), 3000)
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-gray-100 p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <p className="truncate font-semibold text-gray-900">{job.title}</p>
        <p className="text-sm text-gray-500">
          {job.company || 'Unknown company'} · {job.location || 'location n/a'}
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {localityBadge(job.locality)}
          {mechanismBadge(job.apply_mechanism)}
          {attemptBadge(job.apply_status)}
          {job.job_type && <span className="badge bg-gray-100 text-gray-600">{job.job_type}</span>}
          <span className="badge-source">{job.source}</span>
          {job.posted_at && <span className="text-xs text-gray-400">{new Date(job.posted_at).toLocaleDateString()}</span>}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <a href={job.url} target="_blank" rel="noreferrer" className="btn-ghost px-3">View</a>
        {showApply && (
          <>
            <button onClick={() => onApply(job.id)} className="btn-secondary">Mark applied</button>
            {job.apply_mechanism === 'auto' && (
              <button
                onClick={() => onApplyAuto(job.id)}
                disabled={inFlight}
                className="btn-primary"
              >
                {inFlight ? 'Applying…' : 'Auto apply'}
              </button>
            )}
            {job.apply_mechanism === 'form' && job.apply_status !== 'manual_required' && (
              <button
                onClick={() => onApplyAuto(job.id)}
                disabled={inFlight}
                className="btn-primary"
              >
                {inFlight ? 'Drafting…' : 'Draft cover letter'}
              </button>
            )}
            {job.apply_status === 'manual_required' && (
              <button onClick={copyLetter} className="btn-primary">
                {letterMsg === 'copied ✓' ? 'Copied ✓' : letterMsg === 'no letter yet' ? 'No letter' : letterMsg ? letterMsg : 'Copy cover letter'}
              </button>
            )}
          </>
        )}
        {job.status === 'applied' && <span className="badge bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100">applied</span>}
        {job.status === 'archived' && <span className="badge bg-gray-100 text-gray-600">archived</span>}
      </div>
    </div>
  )
}

export default function JobList({ status, refreshKey, onApplied, onApplyAuto }) {
  const [jobs, setJobs] = useState(null)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState(null)
  const [autoId, setAutoId] = useState(null)

  const applyAuto = async (id) => {
    setAutoId(id)
    try {
      await onApplyAuto?.(id)
    } finally {
      setAutoId(null)
    }
  }

  const load = () => api.getMatches(status).then(setJobs).catch((err) => setError(err.message))

  useEffect(() => {
    load()
  }, [status, refreshKey])

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
    <div className="mt-4 space-y-3">
      {error && <p className="text-sm text-red-600">{error}</p>}
      {jobs && jobs.length === 0 && (
        <p className="rounded-xl border border-dashed border-gray-200 p-8 text-center text-sm text-gray-500">
          Nothing here yet — run a search to find {status === 'available' ? 'open ' : ''}jobs.
        </p>
      )}
      {jobs && jobs.map((job) => (
        <JobCard key={job.id} job={job} onApply={apply} onApplyAuto={applyAuto} autoPending={autoId === job.id} showApply={status === 'available'} />
      ))}
    </div>
  )
}
