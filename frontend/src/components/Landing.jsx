import { Logo } from './ui.jsx'

const FEATURES = [
  { title: '1 · Upload your resume', body: 'Drop your PDF on us. We convert it to readable text in the background — never blocks your browser.' },
  { title: '2 · AI finds your roles', body: 'Gemini reads your resume and suggests the roles you can apply for, including internships and apprenticeships.' },
  { title: '3 · Live job hunting', body: 'Searches remote+local roles across Remotive, RemoteOK, Arbeitnow, weworkremotely and the open web.' },
  { title: '4 · Auto-apply', body: 'One click sends a tailored, Gemini-written cover letter with your resume attached to the employer.' },
]

const STEPS = [
  { n: '1', t: 'Register with your country', d: 'Searches are based on your residence so jobs are marked local or remote correctly.' },
  { n: '2', t: 'Upload one PDF resume', d: 'Roles re-derive automatically whenever you replace or update your resume.' },
  { n: '3', t: 'Pick roles, watch matches arrive', d: 'Jobs expire from Available after 14 days. Applied ones are kept forever in the Applied tab.' },
]

export default function Landing({ onGetStarted, onLogin }) {
  return (
    <div className="min-h-screen bg-white">
      <header className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
        <Logo />
        <div className="flex items-center gap-2">
          <button onClick={onLogin} className="btn-ghost">Log in</button>
          <button onClick={onGetStarted} className="btn-primary">Get started</button>
        </div>
      </header>

      <section className="mx-auto max-w-5xl px-6 py-16 text-center">
        <span className="badge bg-brand-50 text-brand-700 ring-1 ring-brand-100">Auto job applications made easy</span>
        <h1 className="mt-6 text-5xl font-extrabold tracking-tight text-gray-900">
          Your resume in. <span className="text-brand-600">Tailored applications out.</span>
        </h1>
        <p className="mx-auto mt-5 max-w-2xl text-lg text-gray-600">
          Upload a PDF once — our AI learns which roles match you, searches the open web for live, non-expired
          positions in your country, and sends tailored cover letters when you hit Auto Apply.
        </p>
        <div className="mt-8 flex items-center justify-center gap-3">
          <button onClick={onGetStarted} className="btn-primary px-6 py-3 text-base">Get started</button>
          <button onClick={onLogin} className="btn-secondary px-6 py-3 text-base">I already have an account</button>
        </div>
      </section>

      <section className="border-t border-gray-100 bg-gray-50/60 py-14">
        <div className="mx-auto max-w-5xl px-6">
          <h2 className="text-center text-2xl font-bold tracking-tight">Everything you need to land interviews faster</h2>
          <div className="mt-10 grid grid-cols-1 gap-5 sm:grid-cols-2">
            {FEATURES.map((f) => (
              <div key={f.title} className="card">
                <h3 className="text-base font-semibold text-gray-900">{f.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-gray-600">{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-5xl px-6 py-14">
        <h2 className="text-center text-2xl font-bold tracking-tight">How it works</h2>
        <ol className="mt-10 grid grid-cols-1 gap-6 sm:grid-cols-3">
          {STEPS.map((s) => (
            <li key={s.n} className="card">
              <div className="grid h-9 w-9 place-items-center rounded-full bg-brand-50 text-brand-700 font-bold">{s.n}</div>
              <p className="mt-4 text-base font-semibold">{s.t}</p>
              <p className="mt-2 text-sm text-gray-600">{s.d}</p>
            </li>
          ))}
        </ol>
      </section>

      <footer className="border-t border-gray-100 py-8 text-center text-sm text-gray-400">
        auto-apply · built with FastAPI, Celery, Gemini and React
      </footer>
    </div>
  )
}
