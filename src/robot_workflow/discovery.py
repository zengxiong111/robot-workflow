"""Conservative, stdlib-only discovery of local robot workflow repositories."""

import ast
import configparser
import os
import tomllib
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from .engine import validate_config

MAX_FILE_BYTES = 1_000_000
MAX_FILES = 20_000
EXCLUDED = {".git", ".venv", "venv", "build", "dist", "install", "devel", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache"}


def _git(path, *args):
    try:
        p = subprocess.run(["git", "-C", str(path), *args], capture_output=True,
                           text=True, timeout=5)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _inside(path, root):
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _files(repo):
    files, notes = [], []
    count = 0
    for current, dirs, names in __import__("os").walk(repo, followlinks=False):
        base = Path(current)
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and
                         not (base / d).is_symlink() and _inside(base / d, repo))
        for name in sorted(names):
            p = base / name
            if p.is_symlink() or not _inside(p, repo) or not p.is_file():
                continue
            count += 1
            if count > MAX_FILES:
                notes.append(f"file scan capped at {MAX_FILES}; remaining files unknown")
                return files, notes
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    notes.append(f"{p.relative_to(repo).as_posix()}: skipped (>1 MB)")
                    continue
            except OSError:
                continue
            files.append(p)
    return files, notes


def _parser(path):
    n = path.name.lower()
    suffix = path.suffix.lower()
    if n.endswith(".urdf") or n.endswith(".urdf.xacro"):
        return "urdf" if suffix == ".urdf" else "yaml"
    if suffix == ".py": return "python"
    if suffix == ".json": return "json"
    if suffix == ".toml": return "toml"
    if suffix in {".yaml", ".yml"}: return "yaml"
    if suffix in {".msg", ".srv", ".action"}: return "ros"
    if n in {"package.xml", "cmakelists.txt", "setup.py", "setup.cfg"}: return "text"
    if suffix in {".xml", ".launch"}: return "text"
    return None


def _artifact_paths(files, repo):
    ranked = []
    for p in files:
        parser = _parser(p)
        if not parser or p.name.lower() in {"readme.md", "contributing.md"}:
            continue
        rel = p.relative_to(repo).as_posix()
        score = (100 if p.name.lower() in {"package.xml", "pyproject.toml", "setup.py", "cmakelists.txt"} else
                 90 if parser == "urdf" else 50 if parser in {"python", "ros"} else 20)
        # Prefer implementation and interfaces; exclude common generated/test/vendor noise.
        if any(part.lower() in EXCLUDED | {"test", "tests", "vendor", "third_party", "docs"}
               for part in Path(rel).parts):
            continue
        ranked.append((score, rel, parser))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    selected = ranked[:80]
    return ([{"glob": rel, "parser": parser} for _, rel, parser in selected],
            len(ranked) - len(selected))


def _documentation_artifacts(files, repo):
    """Return readable Markdown entrypoints as documentation-only coverage."""
    candidates = [p for p in files if p.suffix.lower() == ".md" and
                  (p.name.lower().startswith("readme") or "docs" in
                   {part.lower() for part in p.relative_to(repo).parts[:-1]})]
    candidates.sort(key=lambda p: (0 if p.name.lower().startswith("readme") else 1,
                                   p.relative_to(repo).as_posix()))
    return [{"glob": p.relative_to(repo).as_posix(), "parser": "markdown"}
            for p in candidates[:20]]


def _package_info(files):
    names, deps = set(), []
    for p in files:
        rel = p.name.lower()
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            continue
        if rel == "package.xml":
            try:
                root = ET.fromstring(text)
                name = root.findtext("name")
                if name: names.add(name.strip())
                for el in root.iter():
                    if el.tag in {"depend", "build_depend", "build_export_depend", "exec_depend", "run_depend"} and el.text:
                        dependency = el.text.strip()
                        line_match = re.search(rf"<\s*{re.escape(el.tag)}\s*>\s*{re.escape(dependency)}\s*<", text)
                        line = text.count("\n", 0, line_match.start()) + 1 if line_match else 1
                        deps.append((dependency, p, line, "ROS package dependency"))
            except ET.ParseError:
                pass
        elif rel == "pyproject.toml":
            try:
                data = tomllib.loads(text)
                name = data.get("project", {}).get("name")
                if name: names.add(name)
                declarations = data.get("project", {}).get("dependencies", [])
                optional = data.get("project", {}).get("optional-dependencies", {})
                declarations += [d for values in optional.values() for d in values]
                for declaration in declarations:
                    match = re.match(r"\s*([A-Za-z0-9_.-]+)", declaration)
                    if match:
                        occurrence = re.search(re.escape(declaration), text)
                        line = text.count("\n", 0, occurrence.start()) + 1 if occurrence else 1
                        deps.append((match.group(1), p, line,
                                     "Python dependency declaration"))
            except (tomllib.TOMLDecodeError, AttributeError, TypeError):
                pass
        elif rel == "setup.py":
            try:
                tree = ast.parse(text)
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    for keyword in node.keywords:
                        if keyword.arg not in {"install_requires", "requires"}:
                            continue
                        try: values = ast.literal_eval(keyword.value)
                        except (ValueError, TypeError): continue
                        if isinstance(values, str): values = [values]
                        if isinstance(values, (list, tuple)):
                            for declaration in values:
                                if isinstance(declaration, str):
                                    match = re.match(r"\s*([A-Za-z0-9_.-]+)", declaration)
                                    if match:
                                        deps.append((match.group(1), p, keyword.lineno,
                                                     "Python dependency declaration"))
            except (SyntaxError, ValueError):
                pass
    return names, deps


def discover(root, project="Robot Workflow"):
    """Discover Git checkouts directly or recursively below root.

    Only concrete dependency declarations, submodule paths, and explicit links
    to another discovered checkout create edges. Returns a schema-1 config.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("root must be an existing directory")
    checkouts = []
    # Walk without following symlinks, pruning nested checkout internals and bulky outputs.
    for current, dirs, _ in os.walk(root, followlinks=False):
        base = Path(current)
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not (base / d).is_symlink())
        if base != root and _git(base, "rev-parse", "--show-toplevel"):
            top = Path(_git(base, "rev-parse", "--show-toplevel")).resolve()
            if top == base.resolve() and _inside(top, root):
                checkouts.append(top)
    checkouts = sorted(set(checkouts), key=lambda p: p.relative_to(root).as_posix())
    if not checkouts:
        raise ValueError("No Git checkouts found below root")
    repos, nodes, notes, metadata = [], [], [], {}
    id_by_path = {}
    for repo in checkouts:
        rel = repo.relative_to(root).as_posix()
        rid = re.sub(r"[^A-Za-z0-9_.-]+", "-", rel).strip("-") or "repository"
        if rid in id_by_path.values():
            rid += "-" + str(len(repos) + 1)
        id_by_path[rel] = rid
        files, scan_notes = _files(repo)
        artifacts, omitted = _artifact_paths(files, repo)
        if omitted:
            notes.append(f"{rel}: omitted {omitted} supported artifacts beyond the 80-artifact limit")
        if not artifacts:
            artifacts = _documentation_artifacts(files, repo)
            if artifacts:
                notes.append(f"{rel}: documentation-only coverage from Markdown; no functional source artifacts found")
            else:
                artifacts = [{"glob": ".gitmodules" if (repo / ".gitmodules").is_file() else ".gitignore", "parser": "text"}]
                notes.append(f"{rel}: no readable supported source or Markdown documentation; unknown placeholder selected")
        repos.append({"id": rid, "path": rel})
        nodes.append({"id": rid, "label": repo.name, "repository": rid,
                      "artifacts": artifacts, "owner": "unassigned"})
        notes.extend(f"{rel}/{n}" for n in scan_notes)
        names, deps = _package_info(files)
        remotes = _git(repo, "remote", "-v") or ""
        remote_ids = set()
        for remote_line in remotes.splitlines():
            fields = remote_line.split()
            if len(fields) < 2: continue
            url = fields[1].removesuffix(" (fetch)").removesuffix(" (push)")
            match = re.search(r"(?:github\.com[:/])([^/\s]+)/([^/\s]+?)(?:\.git)?$", url, re.I)
            if match:
                remote_ids.add((match.group(1).lower(), match.group(2).lower()))
        metadata[rid] = {"path": rel, "files": files, "package_names": names, "deps": deps,
                         "remote_ids": remote_ids}

    target_by_name = {}
    absolute_paths = {}
    for rid, info in metadata.items():
        absolute_paths[(root / info["path"]).resolve()] = rid
        for name in info["package_names"]:
            target_by_name.setdefault(name, rid)
    edges, seen = [], set()

    def add(source, target, file, line, basis, detail):
        if source == target or source not in metadata or target not in metadata:
            return
        key = (source, target)
        if key in seen: return
        seen.add(key)
        edges.append({"from": source, "to": target, "watch": ["*"], "emits": ["*"],
                      "basis": basis, "reason": f"{detail} ({file}:{line})"})

    for rid, info in metadata.items():
        repo = root / info["path"]
        gm = repo / ".gitmodules"
        if gm.is_file() and not gm.is_symlink():
            try:
                cp = configparser.ConfigParser()
                cp.read(gm, encoding="utf-8")
                for section in cp.sections():
                    path = cp.get(section, "path", fallback="")
                    target = id_by_path.get((Path(info["path"]) / path).as_posix())
                    if target:
                        add(target, rid, f"{info['path']}/.gitmodules", 1, "inferred: git submodule declaration", f"Submodule path {path}")
            except configparser.Error:
                notes.append(f"{info['path']}/.gitmodules: could not parse")
        for dep, p, line, basis in info["deps"]:
            target = target_by_name.get(dep)
            if target:
                add(target, rid, f"{info['path']}/{p.relative_to(repo).as_posix()}", line,
                    f"inferred: {basis.lower()}", f"Depends on {dep}")
        for p in info["files"]:
            try: text = p.read_text(encoding="utf-8")
            except (UnicodeError, OSError): continue
            for line_no, line in enumerate(text.splitlines(), 1):
                # Match only explicit relative/absolute checkout paths or exact remote identities.
                for target_path, target in absolute_paths.items():
                    if target == rid: continue
                    rel_name = os.path.relpath(target_path, repo)
                    tokens = (rf"(?<![\w.-]){re.escape(rel_name)}(?:/|(?=\s|$|[\]\)`,;]))",
                              re.escape(str(target_path)))
                    if any(re.search(token, line) for token in tokens):
                        add(target, rid, f"{info['path']}/{p.relative_to(repo).as_posix()}", line_no,
                            "inferred: explicit local repository path reference", f"References local checkout {rel_name}")
                for target, target_info in metadata.items():
                    if target == rid: continue
                    for owner_name, repo_name in target_info["remote_ids"]:
                        url_pattern = rf"github\.com[:/]{re.escape(owner_name)}/{re.escape(repo_name)}(?:\.git)?(?:[/#?\s]|$)"
                        if re.search(url_pattern, line, re.I):
                            add(target, rid, f"{info['path']}/{p.relative_to(repo).as_posix()}", line_no,
                                "inferred: exact GitHub remote identity reference",
                                f"References remote {owner_name}/{repo_name}")
    config = {"schema_version": 1, "project": project, "repositories": repos,
              "nodes": nodes, "edges": edges, "requirements": [],
              "discovery": {"method": "stdlib conservative scan", "notes": sorted(set(notes))}}
    return validate_config(config)
