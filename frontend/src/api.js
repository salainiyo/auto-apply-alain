const TOKEN_KEY = 'access_token'

export const getToken = () => localStorage.getItem(TOKEN_KEY) || ''
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t)
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)

export async function waitForStatus(checkFn, { intervalMs = 2500, timeoutMs = 180000 } = {}) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    await new Promise((r) => setTimeout(r, intervalMs))
    try {
      const st = await api.getStatus()
      if (checkFn(st)) return st
    } catch {
      // transient poll failure — keep waiting
    }
  }
  return null
}

const jsonHeaders = () => ({
  'Content-Type': 'application/json',
  Authorization: `Bearer ${getToken()}`,
})

async function handle(resp) {
  if (resp.status === 401) {
    clearToken()
    window.location.reload()
    throw new Error('Session expired. Please log in again.')
  }
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) throw new Error(data.detail || `Error ${resp.status}`)
  return data
}

export const api = {
  register: (body) =>
    fetch('/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(handle),
  login: async (body) => {
    const data = await fetch('/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(handle)
    setToken(data.access_token)
    return data
  },
  verifyEmail: (token) =>
    fetch('/auth/verify-email', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }) }).then(handle),
  logout: () => fetch('/auth/logout', { method: 'POST', headers: jsonHeaders() }).then(handle).finally(clearToken),
  me: () => fetch('/users/me', { headers: jsonHeaders() }).then(handle),

  uploadResume: (file) => {
    const form = new FormData()
    form.append('file', file)
    return fetch('/resumes/upload', { method: 'POST', headers: { Authorization: `Bearer ${getToken()}` }, body: form }).then(handle)
  },
  getCurrentResume: () => fetch('/resumes/current', { headers: jsonHeaders() }).then(handle),

  getRoles: () => fetch('/roles', { headers: jsonHeaders() }).then(handle),
  extractRoles: () => fetch('/roles/extract', { method: 'POST', headers: jsonHeaders() }).then(handle),

  searchJobs: () => fetch('/jobs/search', { method: 'POST', headers: jsonHeaders() }).then(handle),
  getMatches: (status = 'available') =>
    fetch(`/jobs/matches?status_filter=${status}`, { headers: jsonHeaders() }).then(handle),
  applyMatch: (id) =>
    fetch(`/jobs/matches/${id}/apply`, { method: 'POST', headers: jsonHeaders() }).then(handle),

  getSummary: () => fetch('/dashboard/summary', { headers: jsonHeaders() }).then(handle),
  getStatus: () => fetch('/dashboard/status', { headers: jsonHeaders() }).then(handle),
}
