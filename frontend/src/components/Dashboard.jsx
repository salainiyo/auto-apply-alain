import { useEffect, useState } from 'react'
import { api, connectProgress, waitForStatus } from '../api.js'
import JobList from './JobList.jsx'
import ResumeUpload from './ResumeUpload.jsx'
import RoleList from './RoleList.jsx'
import { Logo, StatCard } from './ui.jsx'

const TABS = ['available', 'applied', 'archived']

const fmt = (ts) => (ts ? new Date(ts).toLocaleString() : 'never')

const JOB_BUSY = { resume_conversion: 'upload', role_extraction: 'extract', job_search: 'search', auto_apply: 'apply' }
const JOB_LABEL = { resume_conversion: 'Resume conversion', role_extraction: 'Role extraction', job_search: 'Job search', auto_apply: 'Auto apply' }

export default function Dashboard({ onLogout }) {
  const [me, setMe] = useState(null)
  const [summary, setSummary] = useState(null)
  const [pipeline, setPipeline] = useState(null)
  const [tab, setTab] = useState('available')
  const [refreshKey, setRefreshKey] = useState(0)
  const [busy, setBusy] = useState(null)
  const [doneMsg, setDoneMsg] = useState('')

  const loadMe = () => api.me().then(setMe).catch(() => {})
  const loadSummary = () => api.getSummary().then(setSummary).catch(() => {})
  const loadPipeline = () => api.getStatus().then(setPipeline).catch(() => {})

  useEffect(() => {
    loadMe()
    loadSummary()
    loadPipeline()
  }, [])

  useEffect(() => {
    let closed = false
    let ws = null
    const connect = () => {
      try {
        ws = connectProgress((event) => {
          if (event.type === 'connected') return
          const label = JOB_LABEL[event.job] || event.job || 'Job'
          if (event.status === 'started') {
            setBusy(JOB_BUSY[event.job] || null)
            setDoneMsg('')
          } else if (event.status === 'completed') {
            setBusy(null)
            setDoneMsg(`✔ ${label} finished${event.detail ? ` — ${event.detail}` : ''}`)
            loadSummary()
            loadPipeline()
            setRefreshKey((k) => k + 1)
          } else if (event.status === 'manual_required') {
            setBusy(null)
            setDoneMsg(`⚠ ${label} needs your action${event.detail ? ` — ${event.detail}` : ''}`)
            loadSummary()
            loadPipeline()
            setRefreshKey((k) => k + 1)
          } else if (event.status === 'failed') {
            setBusy(null)
            setDoneMsg(`✘ ${label} failed${event.detail ? `: ${event.detail}` : ''}`)
            loadSummary()
            loadPipeline()
          }
        })
        ws.onclose = () => {
          if (!closed) setTimeout(connect, 3000)
        }
      } catch {
        if (!closed) setTimeout(connect, 3000)
      }
    }
    connect()
    return () => {
      closed = true
      if (ws) ws.close()
    }
  }, [])

  const refreshAll = () => {
    loadSummary()
    loadPipeline()
    setRefreshKey((k) => k + 1)
  }

  const handleUploadComplete = async () => {
    setBusy('upload')
    setDoneMsg('')
    const result = await waitForStatus((st) => ['completed', 'failed'].includes(st.resume_status))
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
    setDoneMsg('Resume converted — extracting roles…')
    const beforeExtract = (await api.getStatus().catch(() => null))?.last_extraction_at
    const extracted = await waitForStatus((st) => st.last_extraction_at && st.last_extraction_at !== beforeExtract)
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
      const result = await waitForStatus((st) => st.last_extraction_at && st.last_extraction_at !== beforeExtract)
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
      const result = await waitForStatus((st) => st.last_search_at && st.last_search_at !== beforeSearch)
      setDoneMsg(result ? `Job search finished — ${result.available} job${result.available === 1 ? '' : 's'} available` : 'Timed out waiting for the job search')
    } catch (err) {
      setDoneMsg(`Job search failed: ${err.message}`)
    }
    setBusy(null)
    refreshAll()
  }

  const handleApplyAuto = async (matchId) => {
    setBusy('apply')
    setDoneMsg('')
    try {
      await api.applyAuto(matchId)
    } catch (err) {
      setBusy(null)
      setDoneMsg(`✘ Auto apply failed: ${err.message}`)
      return
    }
    // WS drives the banner; this poll is the safety net until the attempt is terminal
    const deadline = Date.now() + 90 * 1000
    let attempt = null
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 2500))
      try {
        attempt = await api.getApplication(matchId)
        if (['applied', 'manual_required', 'failed'].includes(attempt.status)) break
        attempt = null
      } catch {
        attempt = null
      }
    }
    setBusy(null)
    if (!attempt) {
      setDoneMsg('Auto apply still running — refresh to see its status')
    } else if (attempt.status === 'applied') {
      setDoneMsg(`✔ Application sent${attempt.detail ? ` — ${attempt.detail}` : ''}`)
    } else if (attempt.status === 'manual_required') {
      setDoneMsg(`⚠ Needs your action — ${attempt.detail || 'please apply at the job link'}`)
    } else {
      setDoneMsg(`✘ Auto apply failed${attempt.detail ? `: ${attempt.detail}` : ''}`)
    }
    refreshAll()
  }

  const logout = async () => {
    await api.logout().catch(() => {})
    onLogout()
  }

  const busyLabel = busy === 'upload' ? 'converting your resume'
    : busy === 'extract' ? 'extracting roles'
    : busy === 'search' ? 'searching for jobs'
    : busy === 'apply' ? 'auto-applying'
    : null

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <Logo />
          <div className="flex items-center gap-3">
            {me && (
              <span className="badge bg-gray-100 text-gray-600">
                {me.email} · {me.country}
              </span>
            )}
            <button onClick={logout} className="btn-ghost">Log out</button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-5 px-6 py-8">
        {summary && (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard label="Available" value={summary.available} />
            <StatCard label="Applied" value={summary.applied} />
            <StatCard label="Archived" value={summary.archived} />
            <StatCard label="Roles" value={pipeline ? pipeline.roles_count : '—'} />
          </div>
        )}

        {pipeline && (
          <div className="card">
            <h2 className="text-sm font-semibold text-gray-900">Pipeline status</h2>
            <p className="mt-1 text-sm text-gray-500">
              Resume: <span className="font-medium">{pipeline.resume_status}</span> · Last extraction: {fmt(pipeline.last_extraction_at)} · Last search: {fmt(pipeline.last_search_at)}
            </p>
            {busyLabel && <p className="mt-2 text-sm text-brand-600">● Running in background: {busyLabel}…</p>}
            {doneMsg && (
              <p className={`mt-2 text-sm ${doneMsg.startsWith('✘') ? 'text-red-600' : doneMsg.startsWith('⚠') ? 'text-amber-600' : 'text-emerald-600'}`}>
                {doneMsg}
              </p>
            )}
          </div>
        )}

        <ResumeUpload onUploaded={handleUploadComplete} />

        <RoleList refreshKey={refreshKey} onExtract={handleExtract} extracting={busy === 'extract'} />

        <div className="card">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Job matches</h2>
              <p className="mt-1 text-xs text-gray-400">Available jobs stay for 14 days, then move to Archived. Local jobs surface first.</p>
            </div>
            <button onClick={handleSearch} disabled={busy === 'search'} className="btn-primary">
              {busy === 'search' ? 'Searching…' : 'Search jobs'}
            </button>
          </div>

          <div className="mt-4 flex gap-2 border-b border-gray-100 pb-3">
            {TABS.map((t) => (
              <button key={t} onClick={() => setTab(t)} className={tab === t ? 'tab-active' : 'tab'}>
                {t.charAt(0).toUpperCase() + t.slice(1)}
                {summary ? ` (${summary[t]})` : ''}
              </button>
            ))}
          </div>

          <JobList status={tab} refreshKey={refreshKey} onApplied={refreshAll} onApplyAuto={handleApplyAuto} />
        </div>
      </main>
    </div>
  )
}
