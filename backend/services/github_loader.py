import base64
import os
import re
from typing import Any

import requests
from langchain.docstore.document import Document


class GitHubRepositoryLoader:
    ALLOWED_EXTENSIONS = {".py", ".js", ".md", ".txt", ".rst"}
    ALLOWED_FILENAMES = {"README", "LICENSE", "CHANGELOG", "CONTRIBUTING", "CODE_OF_CONDUCT"}
    MAX_FILES = 200
    MAX_FILE_SIZE = 250_000  # bytes

    def __init__(self, github_token: str | None = None) -> None:
        self.github_token = github_token or os.getenv("GITHUB_TOKEN")
        self.session = requests.Session()
        if self.github_token:
            self.session.headers.update({"Authorization": f"token {self.github_token}"})
        self.session.headers.update({"Accept": "application/vnd.github+json"})

    def _parse_repo_url(self, repo_url: str) -> tuple[str, str, str]:
        match = re.search(r"github\.com/([^/]+)/([^/]+)(?:\.git)?(?:/.*)?$", repo_url)
        if not match:
            raise ValueError("Invalid GitHub repository URL.")
        owner, repo = match.group(1), match.group(2)
        repo = repo.removesuffix(".git")
        branch = self._get_default_branch(owner, repo)
        return owner, repo, branch

    def _get_default_branch(self, owner: str, repo: str) -> str:
        url = f"https://api.github.com/repos/{owner}/{repo}"
        response = self.session.get(url)
        if response.status_code != 200:
            raise ValueError("Unable to fetch repository metadata from GitHub.")
        return response.json().get("default_branch", "main")

    def _fetch_tree(self, owner: str, repo: str, branch: str) -> list[dict[str, Any]]:
        url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
        response = self.session.get(url)
        if response.status_code != 200:
            raise ValueError("Unable to fetch repository tree from GitHub.")
        return response.json().get("tree", [])

    def _fetch_file_content(self, owner: str, repo: str, path: str, branch: str) -> str:
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
        response = self.session.get(url)
        if response.status_code != 200:
            raise ValueError(f"Unable to fetch file content for {path}.")
        payload = response.json()
        if payload.get("encoding") != "base64" or "content" not in payload:
            raise ValueError(f"Unsupported content encoding for {path}.")
        raw = base64.b64decode(payload["content"]).decode("utf-8", errors="replace")
        return raw

    def get_repo_name(self, repo_url: str) -> str:
        owner, repo, _ = self._parse_repo_url(repo_url)
        return f"{owner}/{repo}"

    def load_repository(self, repo_url: str) -> list[Document]:
        owner, repo, branch = self._parse_repo_url(repo_url)
        tree = self._fetch_tree(owner, repo, branch)

        documents: list[Document] = []
        candidate_files = [item for item in tree if item.get("type") == "blob"]

        for item in candidate_files:
            if len(documents) >= self.MAX_FILES:
                break
            path = item.get("path", "")
            basename = os.path.splitext(os.path.basename(path))[0]
            extension = os.path.splitext(path)[1].lower()
            if extension not in self.ALLOWED_EXTENSIONS:
                if basename.upper() not in self.ALLOWED_FILENAMES:
                    continue
            if item.get("size", 0) > self.MAX_FILE_SIZE:
                continue

            try:
                content = self._fetch_file_content(owner, repo, path, branch)
            except ValueError:
                continue

            if not content.strip():
                continue

            documents.append(
                Document(
                    page_content=content,
                    metadata={"source": path, "repo_url": repo_url},
                )
            )

        if not documents:
            raise ValueError("No supported files were found in the repository.")

        return documents