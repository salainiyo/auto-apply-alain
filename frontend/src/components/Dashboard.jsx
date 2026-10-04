import { useEffect, useState } from 'react'
import { api } from '../api.js'
import JobList from './JobList.jsx'
import ResumeUpload from './ResumeUpload.jsx'
import RoleList from './RoleList.jsx'

const TABS = ['available', 'applied', 'archived']

export default function Dashboard({ onLogout }) {
  const [me, setMe] = useState(null)
  const [summary, setSummary] = useState(null)
  const [tab, setTab] = useState('available')
  const [refreshKey, setRefreshKey] = useState(0)
  const [searchMessage, setSearchMessage] = useState('')
  const [searching, setSearching] = useState(false)

  const loadMe = () => api.me().then(setMe).catch(() => {})
  const loadSummary = () => api.getSummary().then(setSummary).catch(() => {})

  useEffect(() => {
    loadMe()
    loadSummary()
  }, [])

  const refreshAll = () => {
    loadSummary()
    setRefreshKey((k) => k + 1)
  }

  const search = async () => {
    setSearching(true)
    setSearchMessage('')
    try {
      const data = await api.searchJobs()
      setSearchMessage(data.message)
      setTimeout(refreshAll, 5000)
    } catch (err) {
      setSearchMessage(err.message)
    } finally {
      setSearching(false)
    }
  }

  const logout = async () => {
    await api.logout().catch(() => {})
    onLogout()
  }

  return (
    <div className="dashboard">
      <header>
        <h1>auto-apply-alain</h1>
        <div>
          {me && <span className="muted">{me.email} · {me.country}</span>}
          <button onClick={logout}>Log out</button>
        </div>
      </header>

      <ResumeUpload onUploaded={refreshAll} />
      <RoleList refreshKey={refreshKey} />

      <div className="card">
        <div className="dashboard-header">
          <h2>Job matches</h2>
          <button onClick={search} disabled={searching}>{searching ? 'Searching...' : 'Search jobs'}</button>
        </div>
        <p className="muted">
          Available jobs stay for 14 days, then move to Archived. Remote jobs anywhere + local jobs in your country, never shown twice.
        </p>
        {searchMessage && <p className="message">{searchMessage}</p>}

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
