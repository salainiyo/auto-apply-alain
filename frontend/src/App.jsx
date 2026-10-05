import { useEffect, useState } from 'react'
import { getToken } from './api.js'
import AuthPage from './components/AuthPage.jsx'
import Dashboard from './components/Dashboard.jsx'
import Landing from './components/Landing.jsx'

export default function App() {
  const [authed, setAuthed] = useState(Boolean(getToken()))
  const [view, setView] = useState('landing')
  const [authMode, setAuthMode] = useState('login')

  useEffect(() => {}, [])

  if (authed) {
    return <Dashboard onLogout={() => setAuthed(false)} />
  }

  if (view === 'auth') {
    return (
      <AuthPage
        initialMode={authMode}
        onBack={() => setView('landing')}
        onAuthed={() => setAuthed(true)}
      />
    )
  }

  return (
    <Landing
      onGetStarted={() => {
        setAuthMode('register')
        setView('auth')
      }}
      onLogin={() => {
        setAuthMode('login')
        setView('auth')
      }}
    />
  )
}
