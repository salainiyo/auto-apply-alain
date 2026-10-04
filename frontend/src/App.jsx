import { useState } from 'react'

const API = {
  register: (body) => fetch('/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  login: (body) => fetch('/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  me: (token) => fetch('/users/me', { headers: { Authorization: `Bearer ${token}` } }),
}

export default function App() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [country, setCountry] = useState('')
  const [token, setToken] = useState(localStorage.getItem('access_token') || '')
  const [me, setMe] = useState(null)
  const [message, setMessage] = useState('')

  return (
    <div style={{ maxWidth: 420, margin: '60px auto', fontFamily: 'sans-serif' }}>
      <h1>auto-apply-alain</h1>
      <p>Backend scaffold UI — full dashboard arrives in Step 6.</p>

      <div style={{ display: 'grid', gap: 8 }}>
        <input placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input placeholder="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <input placeholder="country" value={country} onChange={(e) => setCountry(e.target.value)} />

        <button onClick={async () => {
          const r = await API.register({ email, password, country })
          setMessage(`${r.status}: ${JSON.stringify(await r.json())}`)
        }}>Register</button>

        <button onClick={async () => {
          const r = await API.login({ email, password })
          if (r.ok) {
            const data = await r.json()
            localStorage.setItem('access_token', data.access_token)
            setToken(data.access_token)
            setMessage('Logged in')
          } else {
            setMessage(`${r.status}: ${JSON.stringify(await r.json())}`)
          }
        }}>Login</button>

        <button onClick={async () => {
          const r = await API.me(token)
          setMe(r.ok ? await r.json() : null)
          setMessage(`me: ${r.status}`)
        }}>Get /users/me</button>
      </div>

      {message && <pre>{message}</pre>}
      {me && <pre>{JSON.stringify(me, null, 2)}</pre>}
    </div>
  )
}
