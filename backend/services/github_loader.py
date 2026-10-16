import base64
import os
import re
import time
from typing import Any
from urllib.parse import quote, urlsplit

import requests
from langchain.docstore.document import Document


class GitHubRepositoryLoader:
    ALLOWED_EXTENSIONS = {".py", ".js", ".md", ".txt", ".rst"}
    ALLOWED_FILENAMES = {"README", "LICENSE", "CHANGELOG", "CONTRIBUTING", "CODE_OF_CONDUCT"}
    MAX_FILES = 200
    MAX_FILE_SIZE = 250_000  # bytes
    ARCHITECTURE_MAX_ENTRIES = 5000
    ARCHITECTURE_MAX_DIRECTORIES = 250
    ARCHITECTURE_MAX_FILES = 200
    ARCHITECTURE_MAX_FILE_SIZE = 250_000
    ARCHITECTURE_MAX_REQUESTS = 400
    ARCHITECTURE_MAX_DURATION_SECONDS = 60
    ARCHITECTURE_TIMEOUT = (3.05, 15)
    ARCHITECTURE_EXTENSIONS = {
        ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".rs", ".rb",
        ".php", ".cs", ".cpp", ".c", ".h", ".hpp", ".swift", ".kt",
        ".md", ".rst", ".txt",
    }
    ARCHITECTURE_MANIFESTS = {
        "package.json", "requirements.txt", "pyproject.toml",
        "go.mod", "cargo.toml",
    }
    ARCHITECTURE_IGNORED_DIRS = {
        ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules",
        "vendor", "dist", "build", "coverage", "__pycache__", ".next",
        ".nuxt", "target", "out", "generated", "__generated__",
        "third_party", "bower_components", "web_modules", ".tox",
        ".mypy_cache", ".pytest_cache",
    }
    ARCHITECTURE_SECRET_NAME = re.compile(
        r"(?:^|/)(?:\.env(?:\..*)?|.*(?:secret|credential|token).*|"
        r"id_rsa(?:\.pub)?|.*\.(?:pem|key|p12|pfx))$",
        re.IGNORECASE,
    )

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

    def _architecture_request(self, url: str, params: dict[str, str] | None = None):
        try:
            response = self.session.get(
                url,
                params=params,
                timeout=self.ARCHITECTURE_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise RuntimeError("GitHub request failed while analyzing the repository.") from exc

        if response.status_code == 429 or (
            response.status_code == 403
            and response.headers.get("X-RateLimit-Remaining") == "0"
        ):
            reset_at = response.headers.get("X-RateLimit-Reset")
            message = "GitHub API rate limit exceeded."
            if reset_at:
                message += f" Retry after Unix timestamp {reset_at}."
            raise RuntimeError(message)
        if response.status_code == 404:
            raise ValueError("Repository or source file was not found on GitHub.")
        if response.status_code != 200:
            raise RuntimeError(
                f"GitHub returned HTTP {response.status_code} while analyzing the repository."
            )
        return response

    @staticmethod
    def _architecture_path_is_ignored(path: str) -> bool:
        parts = path.split("/")
        if any(part.lower() in GitHubRepositoryLoader.ARCHITECTURE_IGNORED_DIRS for part in parts):
            return True
        basename = parts[-1].lower()
        return (
            bool(GitHubRepositoryLoader.ARCHITECTURE_SECRET_NAME.search(path))
            or basename.endswith((".min.js", ".min.jsx", ".min.ts", ".min.tsx", ".bundle.js"))
            or basename.endswith("_pb2.py")
            or ".generated." in basename
        )

    @classmethod
    def _architecture_file_is_supported(cls, path: str) -> bool:
        if cls._architecture_path_is_ignored(path):
            return False
        filename = os.path.basename(path).lower()
        return (
            os.path.splitext(filename)[1] in cls.ARCHITECTURE_EXTENSIONS
            or filename in cls.ARCHITECTURE_MANIFESTS
        )

    def load_architecture_snapshot(self, repo_url: str) -> dict[str, Any]:
        parsed_url = urlsplit(repo_url)
        if parsed_url.scheme != "https" or parsed_url.hostname not in {"github.com", "www.github.com"}:
            raise ValueError("Only HTTPS GitHub repository URLs are supported.")
        path_segments = [segment for segment in parsed_url.path.split("/") if segment]
        if len(path_segments) < 2:
            raise ValueError("Invalid GitHub repository URL.")

        owner, repo = path_segments[:2]
        repo = repo.removesuffix(".git")
        if not re.fullmatch(r"[A-Za-z0-9-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", repo):
            raise ValueError("Invalid GitHub repository URL.")

        api_root = f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
        started_at = time.monotonic()
        request_count = 0

        def request(url: str, params: dict[str, str] | None = None):
            nonlocal request_count
            if (
                request_count >= self.ARCHITECTURE_MAX_REQUESTS
                or time.monotonic() - started_at >= self.ARCHITECTURE_MAX_DURATION_SECONDS
            ):
                raise RuntimeError("Architecture analysis time/request limit reached.")
            request_count += 1
            return self._architecture_request(url, params=params)

        try:
            metadata = request(api_root).json()
        except ValueError as exc:
            raise RuntimeError("GitHub returned invalid repository metadata.") from exc
        if not isinstance(metadata, dict):
            raise RuntimeError("GitHub returned unexpected repository metadata.")
        branch = metadata.get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise RuntimeError("GitHub repository metadata did not include a default branch.")

        entries: list[dict[str, Any]] = []
        source_by_path: dict[str, str] = {}
        warnings: list[str] = []
        pending_directories = [""]
        visited_directories: set[str] = set()
        partial = False
        directory_calls = 0
        tree_entry_count = 0

        while pending_directories and len(entries) < self.ARCHITECTURE_MAX_ENTRIES:
            directory = pending_directories.pop(0)
            if directory in visited_directories:
                continue
            if directory_calls >= self.ARCHITECTURE_MAX_DIRECTORIES:
                partial = True
                warnings.append("Directory traversal limit reached; remaining paths were not inspected.")
                break
            directory_calls += 1
            visited_directories.add(directory)

            path_segment = f"/{quote(directory, safe='/')}" if directory else ""
            contents_url = f"{api_root}/contents{path_segment}"
            params = {"ref": branch, "per_page": "100"}
            while contents_url:
                try:
                    response = request(contents_url, params=params)
                except (RuntimeError, ValueError) as exc:
                    if not directory:
                        raise
                    partial = True
                    warnings.append(f"Could not inspect {directory or 'repository root'}: {exc}")
                    if isinstance(exc, RuntimeError) and (
                        "rate limit" in str(exc).lower() or "limit reached" in str(exc).lower()
                    ):
                        pending_directories.clear()
                    break
                params = None
                try:
                    payload = response.json()
                except ValueError as exc:
                    if not directory:
                        raise RuntimeError("GitHub returned invalid repository directory data.") from exc
                    partial = True
                    warnings.append(f"GitHub returned invalid directory data for {directory or 'repository root'}.")
                    break
                if not isinstance(payload, list):
                    if not directory:
                        raise RuntimeError("GitHub returned an unexpected repository directory listing.")
                    partial = True
                    warnings.append(f"GitHub returned an unexpected directory listing for {directory or 'repository root'}.")
                    break

                for item in payload:
                    tree_entry_count += 1
                    if tree_entry_count > self.ARCHITECTURE_MAX_ENTRIES:
                        partial = True
                        warnings.append("Repository entry limit reached; remaining paths were not inspected.")
                        pending_directories.clear()
                        contents_url = None
                        break
                    if not isinstance(item, dict):
                        partial = True
                        warnings.append("GitHub returned a malformed entry; it was skipped.")
                        continue
                    path = item.get("path")
                    if not isinstance(path, str) or self._architecture_path_is_ignored(path):
                        continue
                    entry_type = item.get("type")
                    if entry_type == "dir":
                        pending_directories.append(path)
                    elif entry_type == "file" and self._architecture_file_is_supported(path):
                        size = item.get("size")
                        if not isinstance(size, int):
                            partial = True
                            warnings.append(f"GitHub did not provide a valid size for {path}; the file was skipped.")
                        elif size > self.ARCHITECTURE_MAX_FILE_SIZE:
                            partial = True
                            warnings.append(f"File size limit exceeded for {path}; the file was skipped.")
                        else:
                            entries.append({"path": path, "size": size, "type": "file"})
                    if len(entries) >= self.ARCHITECTURE_MAX_ENTRIES:
                        break

                if tree_entry_count > self.ARCHITECTURE_MAX_ENTRIES:
                    break
                next_link = response.links.get("next", {}).get("url")
                if next_link:
                    next_url = urlsplit(next_link)
                    if next_url.scheme != "https" or next_url.hostname != "api.github.com":
                        partial = True
                        warnings.append("GitHub provided an unsafe pagination URL; traversal stopped.")
                        break
                contents_url = next_link

        if pending_directories:
            partial = True
            if not any("limit reached" in warning for warning in warnings):
                warnings.append("Repository entry limit reached; remaining paths were not inspected.")

        files = sorted(
            (entry for entry in entries if entry["type"] == "file"),
            key=lambda entry: entry["path"],
        )
        if len(files) > self.ARCHITECTURE_MAX_FILES:
            partial = True
            warnings.append("Source file limit reached; some files were not analyzed.")
            files = files[:self.ARCHITECTURE_MAX_FILES]

        source_paths = {
            entry["path"]
            for entry in files
            if os.path.splitext(entry["path"])[1].lower() in self.ARCHITECTURE_EXTENSIONS
            or os.path.basename(entry["path"]).lower() in self.ARCHITECTURE_MANIFESTS
        }
        for path in sorted(source_paths):
            try:
                response = request(
                    f"{api_root}/contents/{quote(path, safe='/')}",
                    params={"ref": branch},
                )
                payload = response.json()
                if (
                    not isinstance(payload, dict)
                    or payload.get("encoding") != "base64"
                    or not isinstance(payload.get("content"), str)
                ):
                    raise ValueError("Unsupported GitHub source content encoding.")
                encoded_content = re.sub(r"\s+", "", payload["content"])
                raw = base64.b64decode(encoded_content, validate=True)
                source_by_path[path] = raw.decode("utf-8")
            except (RuntimeError, ValueError, KeyError, UnicodeDecodeError) as exc:
                partial = True
                warnings.append(f"Could not read {path}: {exc}")
                if isinstance(exc, RuntimeError) and (
                    "rate limit" in str(exc).lower() or "limit reached" in str(exc).lower()
                ):
                    break

        return {
            "owner": owner,
            "repo": repo,
            "branch": branch,
            "entries": files,
            "contents": source_by_path,
            "partial": partial,
            "warnings": warnings,
        }