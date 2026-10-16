import base64
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from requests import Timeout

from backend.main import app
from backend.services.architecture_explorer import ArchitectureExplorer
from backend.services.github_loader import GitHubRepositoryLoader


def github_response(payload, status=200, headers=None, links=None):
    response = Mock()
    response.status_code = status
    response.headers = headers or {}
    response.links = links or {}
    response.json.return_value = payload
    return response


class ArchitectureExplorerTests(unittest.TestCase):
    def test_loader_follows_pages_and_filters_unsafe_and_unsupported_files(self):
        loader = GitHubRepositoryLoader()
        loader.session = Mock()
        next_page = (
            "https://api.github.com/repos/owner/repo/contents"
            "?ref=main&per_page=100&page=2"
        )
        loader.session.get.side_effect = [
            github_response({"default_branch": "main"}),
            github_response(
                [
                    {"type": "dir", "path": "src"},
                    {"type": "dir", "path": "node_modules"},
                    {"type": "file", "path": ".env", "size": 20},
                    {"type": "file", "path": "image.png", "size": 20},
                ],
                links={"next": {"url": next_page}},
            ),
            github_response(
                [{"type": "file", "path": "package.json", "size": 30}]
            ),
            github_response(
                [{"type": "file", "path": "src/main.py", "size": 40}]
            ),
            github_response(
                {
                    "encoding": "base64",
                    "content": base64.b64encode(b'{"dependencies":{"react":"^18"}}').decode(),
                }
            ),
            github_response(
                {
                    "encoding": "base64",
                    "content": base64.b64encode(b"print('ok')").decode(),
                }
            ),
        ]

        result = loader.load_architecture_snapshot("https://github.com/owner/repo")

        self.assertEqual(
            {entry["path"] for entry in result["entries"]},
            {"package.json", "src/main.py"},
        )
        self.assertEqual(set(result["contents"]), {"package.json", "src/main.py"})
        self.assertFalse(result["partial"])
        self.assertTrue(
            all(call.kwargs["timeout"] == loader.ARCHITECTURE_TIMEOUT
                for call in loader.session.get.call_args_list)
        )

    def test_loader_marks_rate_limited_subtree_as_partial(self):
        loader = GitHubRepositoryLoader()
        loader.session = Mock()
        loader.session.get.side_effect = [
            github_response({"default_branch": "main"}),
            github_response([{"type": "dir", "path": "src"}]),
            github_response(
                {"message": "API rate limit exceeded"},
                status=403,
                headers={"X-RateLimit-Remaining": "0"},
            ),
        ]

        result = loader.load_architecture_snapshot("https://github.com/owner/repo")

        self.assertTrue(result["partial"])
        self.assertTrue(any("rate limit" in warning.lower() for warning in result["warnings"]))

    def test_loader_surfaces_github_network_failures(self):
        loader = GitHubRepositoryLoader()
        loader.session = Mock()
        loader.session.get.side_effect = Timeout("timed out")

        with self.assertRaisesRegex(RuntimeError, "GitHub request failed"):
            loader.load_architecture_snapshot("https://github.com/owner/repo")

    def test_analyzer_reports_python_symbols_routes_local_imports_and_frameworks(self):
        snapshot = {
            "owner": "owner",
            "repo": "repo",
            "branch": "main",
            "entries": [],
            "contents": {
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "from helper import greet\n"
                    "app = FastAPI()\n"
                    "@app.get('/health')\n"
                    "def health():\n"
                    "    return greet()\n"
                    "\n"
                    "class Service:\n"
                    "    def ready(self):\n"
                    "        return True\n"
                ),
                "helper.py": "def greet():\n    return 'ok'\n",
                "pyproject.toml": (
                    "[project]\n"
                    "dependencies = ['fastapi>=0.100']\n"
                ),
                "package.json": (
                    '{"dependencies":{"react":"^18.0.0"}}'
                ),
            },
            "partial": False,
            "warnings": [],
        }
        loader = Mock()
        loader.load_architecture_snapshot.return_value = snapshot

        result = ArchitectureExplorer(loader).analyze("https://github.com/owner/repo")

        self.assertEqual(result["status"], "complete")
        self.assertEqual(
            {framework["name"] for framework in result["frameworks"]},
            {"FastAPI", "React"},
        )
        self.assertTrue(any(node["type"] == "class" for node in result["nodes"]))
        route = next(node for node in result["nodes"] if node["type"] == "route")
        self.assertEqual(route["label"], "GET /health")
        self.assertEqual(route["line_start"], 4)
        self.assertTrue(route["source_url"].endswith("#L4"))
        self.assertTrue(any(edge["type"] == "imports" for edge in result["edges"]))
        self.assertTrue(any(edge["type"] == "exposes" for edge in result["edges"]))

    def test_analyzer_reports_malformed_manifest_as_partial(self):
        loader = Mock()
        loader.load_architecture_snapshot.return_value = {
            "owner": "owner",
            "repo": "repo",
            "branch": "main",
            "entries": [],
            "contents": {"package.json": '{"dependencies":'},
            "partial": False,
            "warnings": [],
        }

        result = ArchitectureExplorer(loader).analyze("https://github.com/owner/repo")

        self.assertEqual(result["status"], "partial")
        self.assertTrue(any("Could not parse manifest" in warning for warning in result["warnings"]))

    def test_endpoint_returns_the_documented_graph_shape(self):
        result = {
            "repo_name": "owner/repo",
            "status": "partial",
            "warnings": ["Some source files could not be read."],
            "languages": [{"name": "Python", "files": 1}],
            "frameworks": [],
            "nodes": [],
            "edges": [],
        }
        with patch(
            "backend.routes.architecture.ArchitectureExplorer"
        ) as explorer:
            explorer.return_value.analyze.return_value = result
            response = TestClient(app).post(
                "/api/architecture",
                json={"repo_url": "https://github.com/owner/repo"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), result)

    def test_endpoint_rejects_non_github_urls(self):
        with patch(
            "backend.routes.architecture.ArchitectureExplorer"
        ) as explorer:
            explorer.return_value.analyze.side_effect = ValueError(
                "Only HTTPS GitHub repository URLs are supported."
            )
            response = TestClient(app).post(
                "/api/architecture",
                json={"repo_url": "https://example.com/owner/repo"},
            )

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
