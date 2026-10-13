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
