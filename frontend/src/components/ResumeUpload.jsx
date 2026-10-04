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
    try {
      const data = await api.uploadResume(file)
      setStatus({ ok: true, text: `Uploaded "${data.original_filename}" — converting to .txt in the background...` })
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
      <h2>Resume</h2>
      <p className="muted">PDF only, max 10 MB. Uploading a new resume replaces the current one.</p>
      <input ref={fileRef} type="file" accept="application/pdf,.pdf" />
      <button onClick={upload} disabled={busy}>{busy ? 'Uploading...' : 'Upload resume'}</button>
      {status && <p className={status.ok ? 'message' : 'error'}>{status.text}</p>}
    </div>
  )
}
