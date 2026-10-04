import { useState } from 'react'
import { getToken } from './api.js'
import AuthPage from './components/AuthPage.jsx'
import Dashboard from './components/Dashboard.jsx'

export default function App() {
  const [authed, setAuthed] = useState(Boolean(getToken()))

  if (!authed) {
    return <AuthPage onAuthed={() => setAuthed(true)} />
  }
  return <Dashboard onLogout={() => setAuthed(false)} />
}
