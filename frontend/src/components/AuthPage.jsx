import { useEffect, useState } from 'react'
import { api, setToken } from '../api.js'
import { Logo } from './ui.jsx'

export default function AuthPage({ initialMode = 'login', onBack, onAuthed }) {
  const [mode, setMode] = useState(initialMode)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [country, setCountry] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

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
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <div className="flex justify-center"><Logo className="text-2xl" /></div>
          <p className="mt-2 text-sm text-gray-500">
            {mode === 'login' ? 'Welcome back' : 'Create your account'}
          </p>
        </div>

        <form onSubmit={submit} className="card space-y-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-500">Email</label>
            <input className="input" placeholder="you@email.com" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-500">Password</label>
            <input className="input" placeholder="••••••••" type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          {mode === 'register' && (
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-500">Country of residence</label>
              <input className="input" placeholder="Rwanda" required minLength={2} value={country} onChange={(e) => setCountry(e.target.value)} />
              <p className="mt-1 text-[11px] text-gray-400">Used to decide which jobs are "local" for you.</p>
            </div>
          )}

          <button type="submit" disabled={busy} className="btn-primary w-full">
            {busy ? 'Please wait...' : mode === 'login' ? 'Log in' : 'Create account'}
          </button>

          {message && <p className="rounded-lg bg-brand-50 p-3 text-center text-sm text-brand-700">{message}</p>}
        </form>

        <div className="mt-4 text-center text-sm text-gray-500">
          {mode === 'login' ? (
            <>New here?{' '}
              <button onClick={() => setMode('register')} className="font-medium text-brand-600">Create an account</button>
            </>
          ) : (
            <>Already have an account?{' '}
              <button onClick={() => setMode('login')} className="font-medium text-brand-600">Log in</button>
            </>
          )}
        </div>
        <div className="mt-2 text-center">
          <button onClick={onBack} className="text-xs text-gray-400 hover:text-gray-600">← Back to home</button>
        </div>
      </div>
    </div>
  )
}
