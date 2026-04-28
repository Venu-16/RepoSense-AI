import { useState } from 'react'
import RepoIngestForm from './components/RepoIngestForm'
import ChatPanel from './components/ChatPanel'

function App() {
  const [repoUrl, setRepoUrl] = useState('')
  const [repoName, setRepoName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [chatHistory, setChatHistory] = useState([])
  const [sources, setSources] = useState([])

  const handleIngestSuccess = (repoUrlValue, repoNameValue) => {
    setRepoUrl(repoUrlValue)
    setRepoName(repoNameValue || repoUrlValue)
    setError('')
    setLoading(false)
    setChatHistory([])
    setSources([])
  }

  const handleQuerySuccess = (answer, sourceFiles, newHistory) => {
    setSources(sourceFiles)
    setChatHistory(newHistory)
    setError('')
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>RepoSense AI</h1>
          <p>Chat with any GitHub repository using code-aware retrieval.</p>
        </div>
      </header>

      <main>
        <RepoIngestForm
          onSuccess={handleIngestSuccess}
          setLoading={setLoading}
          setError={setError}
        />

        {error && <div className="error-box">{error}</div>}
        {loading && <div className="status-box">Loading…</div>}

        <ChatPanel
          repoUrl={repoUrl}
          repoName={repoName}
          chatHistory={chatHistory}
          onQuerySuccess={handleQuerySuccess}
          setLoading={setLoading}
          setError={setError}
          sources={sources}
        />
      </main>
    </div>
  )
}

export default App
