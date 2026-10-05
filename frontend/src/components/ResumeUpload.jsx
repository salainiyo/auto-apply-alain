import { useRef, useState } from 'react'
import { api } from '../api.js'

export default function ResumeUpload({ onUploaded }) {
  const fileRef = useRef()
  const [status, setStatus] = useState(null)
  const [busy, setBusy] = useState(false)

  const upload = async () => {
    const file = fileRef.current?.files?.[0]
    if (!file) {
      setStatus({ ok: false, text: 'Choose a PDF file first' })
      return
    }
    setBusy(true)
    setStatus({ ok: true, text: 'Uploading…' })
    try {
      const data = await api.uploadResume(file)
      setStatus({ ok: true, text: `Uploaded "${data.original_filename}" (${data.status}).` })
      if (fileRef.current) fileRef.current.value = ''
      onUploaded?.()
    } catch (err) {
      setStatus({ ok: false, text: err.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <h2 className="text-sm font-semibold text-gray-900">Resume</h2>
      <p className="mt-1 text-xs text-gray-400">PDF only, max 10 MB. Uploading a new one replaces the current resume.</p>
      <div className="mt-3 flex items-center gap-3">
        <input ref={fileRef} type="file" accept="application/pdf,.pdf" className="text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-brand-50 file:px-4 file:py-2 file:text-sm file:font-medium file:text-brand-700 hover:file:bg-brand-100" />
        <button onClick={upload} disabled={busy} className="btn-primary shrink-0">
          {busy ? 'Uploading…' : 'Upload'}
        </button>
      </div>
      {status && (
        <p className={`mt-3 text-sm ${status.ok ? 'text-gray-600' : 'text-red-600'}`}>{status.text}</p>
      )}
    </div>
  )
}
