import ast
import json
import os
import re
from collections import Counter
from typing import Any
from urllib.parse import quote

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

from backend.services.github_loader import GitHubRepositoryLoader


LANGUAGES = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript (JSX)",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (TSX)",
    ".go": "Go",
    ".java": "Java",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".h": "C/C++",
    ".hpp": "C++",
    ".swift": "Swift",
    ".kt": "Kotlin",
}

FRAMEWORK_NAMES = {
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "react": "React",
    "vue": "Vue",
    "express": "Express",
    "fastify": "Fastify",
    "next": "Next.js",
    "spring-boot": "Spring Boot",
    "gin": "Gin",
    "rails": "Ruby on Rails",
    "actix-web": "Actix Web",
}

FRAMEWORK_SOURCE_IMPORTS = {
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "react": "React",
    "vue": "Vue",
    "express": "Express",
    "fastify": "Fastify",
    "next": "Next.js",
}

MAX_GRAPH_NODES = 1000
MAX_GRAPH_EDGES = 2500


def _source_url(owner: str, repo: str, branch: str, path: str, line: int | None = None) -> str:
    url = (
        f"https://github.com/{quote(owner, safe='')}/{quote(repo, safe='')}"
        f"/blob/{quote(branch, safe='')}/{quote(path, safe='/')}"
    )
    return f"{url}#L{line}" if line else url


def _manifest_frameworks(path: str, text: str) -> set[str]:
    filename = os.path.basename(path).lower()
    dependencies: set[str] = set()
    if filename == "package.json":
        manifest = json.loads(text)
        for section in ("dependencies", "devDependencies", "optionalDependencies"):
            values = manifest.get(section, {})
            if isinstance(values, dict):
                dependencies.update(name.lower() for name in values)
    elif filename == "requirements.txt":
        for line in text.splitlines():
            match = re.match(r"\s*([A-Za-z0-9_.-]+)", line)
            if match and not line.lstrip().startswith("#"):
                dependencies.add(match.group(1).lower().replace("_", "-"))
    elif filename == "pyproject.toml":
        if tomllib is None:
            raise RuntimeError("TOML manifest parsing requires Python 3.11 or newer.")
        manifest = tomllib.loads(text)
        project = manifest.get("project", {})
        dependencies.update(
            re.split(r"[<>=!~\[]", dependency, maxsplit=1)[0].lower().replace("_", "-")
            for dependency in project.get("dependencies", [])
            if isinstance(dependency, str)
        )
        optional = project.get("optional-dependencies", {})
        if isinstance(optional, dict):
            dependencies.update(
                re.split(r"[<>=!~\[]", dependency, maxsplit=1)[0].lower().replace("_", "-")
                for values in optional.values()
                if isinstance(values, list)
                for dependency in values
                if isinstance(dependency, str)
            )
    elif filename == "go.mod":
        dependencies.update(
            line.strip().split()[0].rsplit("/", 1)[-1].lower()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("//")
        )
    elif filename == "cargo.toml":
        if tomllib is None:
            raise RuntimeError("TOML manifest parsing requires Python 3.11 or newer.")
        manifest = tomllib.loads(text)
        for section in ("dependencies", "dev-dependencies"):
            values = manifest.get(section, {})
            if isinstance(values, dict):
                dependencies.update(name.lower() for name in values)
    return {FRAMEWORK_NAMES[name] for name in dependencies if name in FRAMEWORK_NAMES}


def _python_module_paths(module: str) -> list[str]:
    base = module.replace(".", "/")
    return [f"{base}.py", f"{base}/__init__.py"]


def _resolve_python_import(path: str, module: str, level: int, available_paths: set[str]) -> str | None:
    current_module = os.path.splitext(path)[0].replace("/", ".")
    if current_module.endswith(".__init__"):
        current_module = current_module[:-9]
    package_parts = current_module.split(".")[:-1]
    if level:
        if len(package_parts) < level:
            return None
        package_parts = package_parts[: max(0, len(package_parts) - level + 1)]
        module = ".".join(part for part in (*package_parts, module) if part)
    if not module:
        return None
    for candidate in _python_module_paths(module):
        if candidate in available_paths:
            return candidate
    return None


def _python_symbols(
    path: str,
    text: str,
    owner: str,
    repo: str,
    branch: str,
    available_paths: set[str],
    max_symbols: int,
    max_imports: int,
    max_routes: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], set[str], bool]:
    tree = ast.parse(text, filename=path)
    symbols: list[dict[str, Any]] = []
    imports: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    imported_modules: set[str] = set()
    fastapi_objects: set[str] = set()
    truncated = False

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            if len(symbols) < max_symbols:
                symbols.append(
                    {
                        "id": f"symbol:{path}:{node.lineno}:{node.name}",
                        "type": kind,
                        "label": node.name,
                        "path": path,
                        "line_start": node.lineno,
                        "line_end": getattr(node, "end_lineno", node.lineno),
                        "explanation": f"Python {kind} declared in {path}.",
                        "evidence": f"{kind.title()} declaration at line {node.lineno}.",
                        "source_url": _source_url(owner, repo, branch, path, node.lineno),
                    }
                )
            else:
                truncated = True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".", 1)[0])
                target = _resolve_python_import(path, alias.name, 0, available_paths)
                if target and len(imports) < max_imports:
                    imports.append(
                        {
                            "target": target,
                            "line": node.lineno,
                            "evidence": f"Python import '{alias.name}' at line {node.lineno}.",
                        }
                    )
                elif target:
                    truncated = True
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module.split(".", 1)[0])
            target = _resolve_python_import(path, node.module or "", node.level, available_paths)
            if target and len(imports) < max_imports:
                imports.append(
                    {
                        "target": target,
                        "line": node.lineno,
                        "evidence": f"Python import from '{'.' * node.level}{node.module or ''}' at line {node.lineno}.",
                    }
                )
            elif target:
                truncated = True
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                if value.func.id in {"FastAPI", "APIRouter"}:
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    fastapi_objects.update(target.id for target in targets if isinstance(target, ast.Name))

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            owner_node = decorator.func.value
            method = decorator.func.attr.upper()
            if (
                not isinstance(owner_node, ast.Name)
                or owner_node.id not in fastapi_objects
                or method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}
                or not decorator.args
                or not isinstance(decorator.args[0], ast.Constant)
                or not isinstance(decorator.args[0].value, str)
            ):
                continue
            route_path = decorator.args[0].value
            route_id = f"route:{path}:{decorator.lineno}:{method}:{route_path}"
            if len(routes) >= max_routes:
                truncated = True
                continue
            routes.append(
                {
                    "id": route_id,
                    "type": "route",
                    "label": f"{method} {route_path}",
                    "path": path,
                    "line_start": decorator.lineno,
                    "line_end": getattr(decorator, "end_lineno", decorator.lineno),
                    "explanation": (
                        f"Route inferred from the {owner_node.id}.{method.lower()} decorator "
                        f"on {node.name}; this is static analysis, not runtime verification."
                    ),
                    "evidence": f"Route decorator at line {decorator.lineno}.",
                    "source_url": _source_url(owner, repo, branch, path, decorator.lineno),
                    "handler_id": f"symbol:{path}:{node.lineno}:{node.name}",
                }
            )
    return symbols, imports, routes, imported_modules, truncated


class ArchitectureExplorer:
    def __init__(self, repository_loader: GitHubRepositoryLoader | None = None) -> None:
        self.repository_loader = repository_loader or GitHubRepositoryLoader()

    def analyze(self, repo_url: str) -> dict[str, Any]:
        snapshot = self.repository_loader.load_architecture_snapshot(repo_url)
        contents = snapshot["contents"]
        owner, repo, branch = snapshot["owner"], snapshot["repo"], snapshot["branch"]
        available_python_paths = {
            path for path in contents if path.lower().endswith(".py")
        }

        languages = Counter(
            LANGUAGES[os.path.splitext(path)[1].lower()]
            for path in contents
            if os.path.splitext(path)[1].lower() in LANGUAGES
        )
        partial = snapshot["partial"]
        warnings = list(snapshot["warnings"])
        framework_evidence: dict[str, set[str]] = {}
        for path, text in contents.items():
            try:
                frameworks = _manifest_frameworks(path, text)
            except (ValueError, RuntimeError, TypeError, AttributeError) as exc:
                partial = True
                warnings.append(f"Could not parse manifest {path}: {exc}")
                frameworks = set()
            for framework in frameworks:
                framework_evidence.setdefault(framework, set()).add(f"dependency listed in {path}")

        nodes: list[dict[str, Any]] = [
            {
                "id": "root",
                "type": "repository",
                "label": f"{owner}/{repo}",
                "path": "",
                "explanation": "Repository root; descendants are based on GitHub file paths.",
                "evidence": "Repository structure returned by GitHub.",
                "source_url": f"https://github.com/{quote(owner, safe='')}/{quote(repo, safe='')}",
            }
        ]
        edges: list[dict[str, Any]] = []
        node_ids = {"root"}
        path_node_ids: dict[str, str] = {}
        edge_limit_reported = False

        def add_edge(edge: dict[str, Any]) -> None:
            nonlocal partial, edge_limit_reported
            if len(edges) >= MAX_GRAPH_EDGES:
                partial = True
                if not edge_limit_reported:
                    warnings.append("Graph edge limit reached; some relationships are not shown.")
                    edge_limit_reported = True
                return
            edges.append(edge)

        for path in sorted(contents):
            parents = path.split("/")[:-1]
            parent_id = "root"
            current_path = ""
            for part in parents:
                current_path = f"{current_path}/{part}".lstrip("/")
                directory_id = f"dir:{current_path}"
                if directory_id not in node_ids:
                    nodes.append(
                        {
                            "id": directory_id,
                            "type": "folder",
                            "label": part,
                            "path": current_path,
                            "explanation": f"Directory inferred from the path of analyzed files ({current_path}).",
                            "evidence": "GitHub file path hierarchy.",
                            "source_url": None,
                        }
                    )
                    node_ids.add(directory_id)
                    add_edge(
                        {
                            "source": parent_id,
                            "target": directory_id,
                            "type": "contains",
                            "label": "contains",
                            "explanation": "Parent-child relationship inferred from the repository path.",
                            "evidence": f"Directory path: {current_path}.",
                        }
                    )
                parent_id = directory_id
            file_id = f"file:{path}"
            path_node_ids[path] = file_id
            if file_id in node_ids:
                continue
            nodes.append(
                {
                    "id": file_id,
                    "type": "file",
                    "label": os.path.basename(path),
                    "path": path,
                    "explanation": f"Supported source or project manifest found at {path}.",
                    "evidence": "File path and content fetched from GitHub.",
                    "source_url": _source_url(owner, repo, branch, path),
                }
            )
            node_ids.add(file_id)
            add_edge(
                {
                    "source": parent_id,
                    "target": file_id,
                    "type": "contains",
                    "label": "contains",
                    "explanation": "Parent-child relationship inferred from the repository path.",
                    "evidence": f"File path: {path}.",
                }
            )

        for path, text in contents.items():
            if path.lower().endswith((".js", ".jsx", ".ts", ".tsx")):
                for package_name, framework in FRAMEWORK_SOURCE_IMPORTS.items():
                    if re.search(rf"\bfrom\s+['\"]{re.escape(package_name)}(?:/[^'\"]*)?['\"]", text):
                        framework_evidence.setdefault(framework, set()).add(f"import found in {path}")

            if not path.lower().endswith(".py"):
                continue
            try:
                node_capacity = max(
                    0,
                    MAX_GRAPH_NODES - len(nodes) - len(FRAMEWORK_NAMES),
                )
                relation_capacity = max(0, MAX_GRAPH_EDGES - len(edges))
                symbols, imports, routes, imported_modules, truncated = _python_symbols(
                    path,
                    text,
                    owner,
                    repo,
                    branch,
                    available_python_paths,
                    node_capacity,
                    relation_capacity,
                    node_capacity,
                )
            except (SyntaxError, ValueError) as exc:
                partial = True
                warnings.append(f"Could not parse {path}: {exc}")
                continue
            if truncated:
                partial = True
                warnings.append(f"Graph detail limit reached while analyzing {path}.")
            for module in imported_modules:
                framework = FRAMEWORK_SOURCE_IMPORTS.get(module)
                if framework:
                    framework_evidence.setdefault(framework, set()).add(f"import found in {path}")

            source_id = path_node_ids[path]
            for symbol in symbols:
                if symbol["id"] not in node_ids:
                    if len(nodes) >= MAX_GRAPH_NODES - len(FRAMEWORK_NAMES):
                        partial = True
                        warnings.append("Graph node limit reached; some inferred symbols are not shown.")
                        break
                    nodes.append(symbol)
                    node_ids.add(symbol["id"])
                    add_edge(
                        {
                            "source": source_id,
                            "target": symbol["id"],
                            "type": "defines",
                            "label": "defines",
                            "explanation": "Symbol is declared in this Python file.",
                            "evidence": symbol["evidence"],
                            "path": path,
                            "line_start": symbol["line_start"],
                            "source_url": symbol["source_url"],
                        }
                    )
            for imported in imports:
                target_id = path_node_ids.get(imported["target"])
                if target_id:
                    add_edge(
                        {
                            "source": source_id,
                            "target": target_id,
                            "type": "imports",
                            "label": "imports",
                            "explanation": "A statically resolved local Python import; external imports are not drawn.",
                            "evidence": imported["evidence"],
                            "line": imported["line"],
                            "path": path,
                            "source_url": _source_url(owner, repo, branch, path, imported["line"]),
                        }
                    )
            for route in routes:
                handler_id = route.pop("handler_id")
                route_id = route["id"]
                if handler_id not in node_ids:
                    partial = True
                    warnings.append(f"Route handler for {route['label']} exceeded the graph node limit.")
                    continue
                if route_id not in node_ids:
                    if len(nodes) >= MAX_GRAPH_NODES - len(FRAMEWORK_NAMES):
                        partial = True
                        warnings.append("Graph node limit reached; some inferred routes are not shown.")
                        break
                    nodes.append(route)
                    node_ids.add(route_id)
                    add_edge(
                        {
                            "source": handler_id,
                            "target": route_id,
                            "type": "exposes",
                            "label": "exposes",
                            "explanation": "Route decorator associates this function with an HTTP method and path.",
                            "evidence": route["evidence"],
                            "path": path,
                            "line_start": route["line_start"],
                            "source_url": route["source_url"],
                        }
                    )

        for framework in sorted(framework_evidence):
            nodes.append(
                {
                    "id": f"framework:{framework}",
                    "type": "framework",
                    "label": framework,
                    "path": "",
                    "explanation": "Framework inferred from declared dependencies or source imports; usage is not runtime-verified.",
                    "evidence": "; ".join(sorted(framework_evidence[framework])),
                    "source_url": None,
                }
            )
            for evidence in sorted(framework_evidence[framework]):
                source_path = evidence.rsplit(" in ", 1)[-1]
                source_id = path_node_ids.get(source_path)
                if source_id:
                    add_edge(
                        {
                            "source": source_id,
                            "target": f"framework:{framework}",
                            "type": "uses",
                            "label": "declares/imports",
                            "explanation": "Framework association inferred from a dependency declaration or import.",
                            "evidence": evidence,
                            "path": source_path,
                            "source_url": _source_url(owner, repo, branch, source_path),
                        }
                    )
        if len(nodes) > MAX_GRAPH_NODES:
            partial = True
            warnings.append("Graph node limit reached; some inferred symbols are not shown.")
            structural_nodes = [
                node for node in nodes
                if node["type"] in {"repository", "folder", "file", "framework"}
            ]
            inferred_nodes = [
                node for node in nodes
                if node["type"] not in {"repository", "folder", "file", "framework"}
            ]
            nodes = structural_nodes + inferred_nodes[:MAX_GRAPH_NODES - len(structural_nodes)]
            node_ids = {node["id"] for node in nodes}
        edges = [
            edge for edge in edges
            if edge["source"] in node_ids and edge["target"] in node_ids
        ]

        return {
            "repo_name": f"{owner}/{repo}",
            "status": "partial" if partial else "complete",
            "warnings": sorted(set(warnings)),
            "languages": [
                {"name": language, "files": count}
                for language, count in sorted(languages.items())
            ],
            "frameworks": [
                {
                    "name": framework,
                    "evidence": sorted(evidence),
                    "inferred": True,
                }
                for framework, evidence in sorted(framework_evidence.items())
            ],
            "nodes": nodes,
            "edges": edges,
        }
