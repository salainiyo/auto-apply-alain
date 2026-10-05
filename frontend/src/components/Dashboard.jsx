import { useEffect, useState } from 'react'
import { api, waitForStatus } from '../api.js'
import JobList from './JobList.jsx'
import ResumeUpload from './ResumeUpload.jsx'
import RoleList from './RoleList.jsx'

const TABS = ['available', 'applied', 'archived']

const fmt = (ts) => (ts ? new Date(ts).toLocaleString() : 'never')

export default function Dashboard({ onLogout }) {
  const [me, setMe] = useState(null)
  const [summary, setSummary] = useState(null)
  const [pipeline, setPipeline] = useState(null)
  const [tab, setTab] = useState('available')
  const [refreshKey, setRefreshKey] = useState(0)
  const [busy, setBusy] = useState(null) // 'upload' | 'extract' | 'search' | null
  const [doneMsg, setDoneMsg] = useState('')

  const loadMe = () => api.me().then(setMe).catch(() => {})
  const loadSummary = () => api.getSummary().then(setSummary).catch(() => {})
  const loadPipeline = () => api.getStatus().then(setPipeline).catch(() => {})

  useEffect(() => {
    loadMe()
    loadSummary()
    loadPipeline()
  }, [])

  const refreshAll = () => {
    loadSummary()
    loadPipeline()
    setRefreshKey((k) => k + 1)
  }

  const handleUploadComplete = async () => {
    setBusy('upload')
    setDoneMsg('')
    const result = await waitForStatus((st) =>
      ['completed', 'failed'].includes(st.resume_status),
    )
    loadPipeline()
    if (!result) {
      setBusy(null)
      setDoneMsg('Timed out waiting for resume conversion')
      return
    }
    if (result.resume_status === 'failed') {
      setBusy(null)
      setDoneMsg('Resume conversion failed — check the file is a valid PDF')
      refreshAll()
      return
    }
    setDoneMsg('Resume converted — extracting roles in the background...')
    const beforeExtract = (await api.getStatus().catch(() => null))?.last_extraction_at
    const extracted = await waitForStatus(
      (st) => st.last_extraction_at && st.last_extraction_at !== beforeExtract,
    )
    setBusy(null)
    setDoneMsg(extracted ? 'Roles extracted and saved' : 'Conversion done, but role extraction timed out')
    refreshAll()
  }

  const handleExtract = async () => {
    setBusy('extract')
    setDoneMsg('')
    const beforeExtract = (await api.getStatus().catch(() => null))?.last_extraction_at
    try {
      await api.extractRoles()
      const result = await waitForStatus(
        (st) => st.last_extraction_at && st.last_extraction_at !== beforeExtract,
      )
      setDoneMsg(result ? 'Roles extracted and saved' : 'Timed out waiting for extraction')
    } catch (err) {
      setDoneMsg(`Extraction failed: ${err.message}`)
    }
    setBusy(null)
    refreshAll()
  }

  const handleSearch = async () => {
    setBusy('search')
    setDoneMsg('')
    const beforeSearch = (await api.getStatus().catch(() => null))?.last_search_at
    try {
      await api.searchJobs()
      const result = await waitForStatus(
        (st) => st.last_search_at && st.last_search_at !== beforeSearch,
      )
      setDoneMsg(
        result
          ? `Job search finished — ${result.available} job${result.available === 1 ? '' : 's'} available`
          : 'Timed out waiting for the job search',
      )
    } catch (err) {
      setDoneMsg(`Job search failed: ${err.message}`)
    }
    setBusy(null)
    refreshAll()
  }

  const logout = async () => {
    await api.logout().catch(() => {})
    onLogout()
  }

  const busyLabel =
    busy === 'upload'
      ? 'converting your resume to text'
      : busy === 'extract'
        ? 'extracting roles'
        : busy === 'search'
          ? 'searching for jobs'
          : null

  return (
    <div className="dashboard">
      <header>
        <h1>auto-apply-alain</h1>
        <div>
          {me && (
            <span className="muted">
              {me.email} · {me.country}
            </span>
          )}
          <button onClick={logout}>Log out</button>
        </div>
      </header>

      <ResumeUpload onUploaded={handleUploadComplete} />

      {pipeline && (
        <div className="card">
          <h2>Pipeline status</h2>
          <p className="muted">
            Resume: {pipeline.resume_status} · Roles: {pipeline.roles_count} · Matches:{' '}
            {pipeline.available} available / {pipeline.applied} applied / {pipeline.archived} archived
          </p>
          <p className="muted">
            Last extraction: {fmt(pipeline.last_extraction_at)} · Last search: {fmt(pipeline.last_search_at)}
          </p>
          {busyLabel && <p className="message">● Running in background: {busyLabel}...</p>}
          {doneMsg && <p className="message">✔ {doneMsg}</p>}
        </div>
      )}

      <RoleList refreshKey={refreshKey} onExtract={handleExtract} extracting={busy === 'extract'} />

      <div className="card">
        <div className="dashboard-header">
          <h2>Job matches</h2>
          <button onClick={handleSearch} disabled={busy === 'search'}>
            {busy === 'search' ? 'Searching...' : 'Search jobs'}
          </button>
        </div>
        <p className="muted">
          Available jobs stay for 14 days, then move to Archived. Remote jobs anywhere + local jobs in your
          country, never shown twice.
        </p>

        <div className="tabs">
          {TABS.map((t) => (
            <button key={t} className={tab === t ? 'tab active' : 'tab'} onClick={() => setTab(t)}>
              {t.charAt(0).toUpperCase() + t.slice(1)}
              {summary ? ` (${summary[t]})` : ''}
            </button>
          ))}
        </div>

        <JobList status={tab} refreshKey={refreshKey} onApplied={refreshAll} />
      </div>
    </div>
  )
}
