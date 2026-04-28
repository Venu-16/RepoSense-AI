import { useState } from 'react'

function ChatPanel({ repoUrl, repoName, chatHistory, onQuerySuccess, setLoading, setError, sources }) {
  const [message, setMessage] = useState('')

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (!repoUrl) {
      setError('Please ingest a repository first.')
      return
    }

    setLoading(true)
    setError('')

    try {
      const response = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_url: repoUrl, query: message }),
      })
      const data = await response.json()
      if (!response.ok) {
        throw new Error(data.detail || 'Query failed.')
      }
      onQuerySuccess(data.answer, data.sources, data.history)
      setMessage('')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="card">
      <div className="panel-header">
        <div>
          <h2>Chat interface</h2>
          <p>{repoUrl ? `Repository: ${repoName || repoUrl}` : 'Ingest a repository to begin.'}</p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="form-grid">
        <input
          type="text"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="Ask a question about the repository"
          disabled={!repoUrl}
          required
        />
        <button type="submit" disabled={!repoUrl}>Send</button>
      </form>

      {sources.length > 0 && (
        <div className="sources-box">
          <strong>Source files:</strong>
          <ul>
            {sources.map((source) => (
              <li key={source}>{source}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="history-list">
        {chatHistory.map((item, index) => (
          <article key={index} className="history-item">
            <p className="history-question">Q: {item.question}</p>
            <p className="history-answer">A: {item.answer}</p>
          </article>
        ))}
      </div>
    </section>
  )
}

export default ChatPanel
