import { useState } from 'react'

function RepoIngestForm({ onSuccess, setLoading, setError }) {
  const [repoUrl, setRepoUrl] = useState('')

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setLoading(true)

    try {
      const response = await fetch('/api/ingest-repo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_url: repoUrl }),
      })

      const data = await response.json()
      if (!response.ok) {
        throw new Error(data.detail || 'Failed to ingest repository.')
      }

      onSuccess(data.repo_url, data.repo_name)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="card">
      <h2>Ingest a GitHub repository</h2>
      <form onSubmit={handleSubmit} className="form-grid">
        <input
          type="url"
          value={repoUrl}
          onChange={(event) => setRepoUrl(event.target.value)}
          placeholder="https://github.com/owner/repo"
          required
          disabled={false}
        />
        <button type="submit" disabled={false}>Ingest repository</button>
      </form>
    </section>
  )
}

export default RepoIngestForm
