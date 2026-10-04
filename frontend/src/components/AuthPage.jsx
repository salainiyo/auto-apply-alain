import { useEffect, useState } from 'react'
import { api, setToken } from '../api.js'

export default function AuthPage({ onAuthed }) {
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [country, setCountry] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  // email verification link: /?token=... (frontend root)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const verifyToken = params.get('token')
    if (verifyToken) {
      setBusy(true)
      api
        .verifyEmail(verifyToken)
        .then((data) => setMessage(data.message))
        .catch((err) => setMessage(err.message))
        .finally(() => setBusy(false))
    }
  }, [])

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setMessage('')
    try {
      if (mode === 'register') {
        const data = await api.register({ email, password, country })
        setMessage(data.message)
      } else {
        await api.login({ email, password })
        setToken(localStorage.getItem('access_token'))
        onAuthed()
      }
    } catch (err) {
      setMessage(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <h1>auto-apply-alain</h1>
      <div className="tabs">
        <button className={mode === 'login' ? 'tab active' : 'tab'} onClick={() => setMode('login')}>Login</button>
        <button className={mode === 'register' ? 'tab active' : 'tab'} onClick={() => setMode('register')}>Register</button>
      </div>

      <form onSubmit={submit} className="card">
        <input placeholder="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <input placeholder="password" type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
        {mode === 'register' && (
          <input placeholder="country of residence" required minLength={2} value={country} onChange={(e) => setCountry(e.target.value)} />
        )}
        <button type="submit" disabled={busy}>{busy ? '...' : mode === 'login' ? 'Log in' : 'Create account'}</button>
      </form>

      {message && <p className="message">{message}</p>}
    </div>
  )
}
