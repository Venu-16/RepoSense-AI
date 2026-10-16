# RepoSense-AI

A Retrieval-Augmented Generation (RAG) application that allows users to ask questions about a GitHub repository. It ingests repository documents, indexes them in a vector store, and uses embeddings to retrieve relevant context for answering queries.

# **Architecture**
![Architecture diagram](https://github.com/Venu-16/RepoSense-AI/blob/main/reposence%20ai.png)

# **Components**
  - **User Interface:** App.jsx, ChatPanel.jsx, RepoIngestForm.jsx
  - **Backend API:** FastAPI application with query and ingest endpoints
  - **RAG Pipeline:** Retrieves relevant documents using a vector index and embeddings
  - **Repository Ingestion:** Loads repository documents through the GitHub API
# Workflow
 - Submit a GitHub repository URL through the UI.
 - The ingestion endpoint loads and indexes repository documents.
 - Ask questions through the chat panel.
 - The query endpoint retrieves relevant context using the RAG pipeline.
 - The application generates answers based on the retrieved documents.
# Tech Stack
 - React
 - FastAPI
 - Python
 - Retrieval-Augmented Generation (RAG)
 - Vector Index
 - Embeddings
 - GitHub API

# Local development

From the repository root, install the backend dependencies and start the API:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000
```

In a second terminal, start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open the URL printed by Vite. Its development server proxies `/api` requests to
the backend at `http://127.0.0.1:8000`. To verify the frontend proxy, run
`npm test` from `frontend`.

# Architecture explorer

After ingesting a repository, the UI also requests `POST /api/architecture`
with the existing `{ "repo_url": "..." }` request shape. The endpoint is
independent of RAG indexing and returns a bounded graph of supported files,
folders, Python symbols, locally resolvable Python imports, and statically
recognized FastAPI routes. It reports language counts and frameworks only when
they are evidenced by supported file extensions, manifests, or imports.

All graph relationships are static inferences, not verified runtime
dependencies. Python source is parsed with `ast`; repository code is never
executed. GitHub API requests have timeouts and rate-limit/error reporting.
Traversal is capped at 5,000 entries, 250 directories, 200 source files, 250 KB
per file, 400 GitHub API requests, and 60 seconds. Recognized manifests include
`package.json`, `requirements.txt`, `pyproject.toml`, `go.mod`, and
`Cargo.toml`. If the GitHub listing is paginated or any configured limit or
fetch/parse error prevents complete analysis, the response is marked partial
and includes warnings. Secret-like paths, binaries, generated/dependency
directories, and unsupported file types are excluded. Node details link to
their GitHub source and line references when available; the graph can be
exported as SVG.

Verification:

```bash
# From the repository root, with backend requirements installed
.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py' -v

# Frontend checks
cd frontend
npm test
npm run build
```

For a local UI smoke check, start the backend and Vite as described above,
ingest a public GitHub repository with Python files and a project manifest,
then inspect nodes/edges, follow a source link, and use **Export SVG**. A
repository with unsupported files only should show the empty state; an
unavailable or rate-limited GitHub API should show an error or partial-result
warning.
