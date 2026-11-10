"""Write the MCP client configuration for this installation of seers.

The entry is the ``seers-mcp`` command, which follows whichever installation is
on PATH. When PATH does not lead to this installation it launches this
interpreter with ``-m seers.mcp`` instead. ``install()`` puts that entry into
client configuration files: by default every known one that already has a
``seers`` server, so stale entries (an old path, a URL nobody serves) are
corrected and clients the user never configured are left alone.

Only JSON files are edited. A file with comments or one that does not parse is
reported and left untouched.
"""

from __future__ import annotations

from importlib.metadata import distribution
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from seers import REPOSITORY, __version__

NAME = "seers"
_SERVER_TABLES = ("mcpServers", "servers")  # "servers": VS Code's mcp.json
_TRANSPORT_KEYS = ("type", "url", "command", "args", "headers")


def _script() -> Path:
    """Where this installation's ``seers-mcp`` command is, or would be."""
    return Path(sysconfig.get_path("scripts")) / ("seers-mcp.exe" if sys.platform == "win32" else "seers-mcp")


def entry() -> dict[str, Any]:
    """The server entry for this installation: the ``seers-mcp`` command when the one on PATH
    is this installation's, else this interpreter by its full path."""
    found = shutil.which("seers-mcp")
    if found and _script().exists() and os.path.samefile(found, _script()):
        return {"command": "seers-mcp"}
    return {"command": sys.executable, "args": ["-m", "seers.mcp"]}


def known_configs() -> list[Path]:
    """Where MCP clients keep user-level JSON configuration, whether or not the file exists."""
    home = Path.home()
    if sys.platform == "win32":
        roaming = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        roaming = home / "Library" / "Application Support"
    else:
        roaming = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    return [
        home / ".omp" / "agent" / "mcp.json",
        home / ".claude.json",
        roaming / "Claude" / "claude_desktop_config.json",
        home / ".cursor" / "mcp.json",
        roaming / "Code" / "User" / "mcp.json",
        home / ".codeium" / "windsurf" / "mcp_config.json",
        home / ".gemini" / "settings.json",
        home / ".mcp.json",
    ]


def _tables(node: Any) -> list[dict[str, Any]]:
    """Every server table in a document; some clients also nest one per project."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _SERVER_TABLES and isinstance(value, dict):
                found.append(value)
            else:
                found += _tables(value)
    elif isinstance(node, list):
        for value in node:
            found += _tables(value)
    return found


def _update(path: Path, *, add: bool) -> str:
    """Set the entry in one file and say what happened. ``add`` creates it where missing."""
    document: Any = {}
    text = ""
    if path.exists():
        text = path.read_text(encoding="utf-8")
        try:
            document = json.loads(text)
        except ValueError:
            return "skipped: not plain JSON, edit it by hand"
        if not isinstance(document, dict):
            return "skipped: not a JSON object"
    elif not add:
        return "absent"

    tables = [table for table in _tables(document) if NAME in table]
    if not tables:
        if not add:
            return "no seers entry"
        table = next(iter(_tables(document)), None)
        if table is None:
            table = document.setdefault(_SERVER_TABLES[0], {})
        table[NAME] = {}
        tables = [table]

    changed = False
    for table in tables:
        old = table[NAME] if isinstance(table[NAME], dict) else {}
        # Keep what is not about how to reach the server (env, disabled, timeouts).
        new = {**entry(), **{key: value for key, value in old.items() if key not in _TRANSPORT_KEYS}}
        if new != table[NAME]:
            table[NAME] = new
            changed = True
    if not changed:
        return "already correct"

    indent = "\t" if "\n\t" in text else 4 if '\n    "' in text else 2
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")
    return "updated"


def install(paths: list[Path]) -> None:
    """Update the given files, adding the entry where missing; with none, fix every known
    configuration that already has a seers entry. Prints one line per file touched or skipped."""
    targets = [(path, True) for path in paths] or [(path, False) for path in known_configs()]
    for path, add in targets:
        outcome = _update(path, add=add)
        if outcome not in ("absent", "no seers entry"):
            print(f"{path}: {outcome}")
    if not paths:
        codex = Path.home() / ".codex" / "config.toml"
        if codex.exists() and f"mcp_servers.{NAME}" in codex.read_text(encoding="utf-8", errors="replace"):
            print(f"{codex}: has a seers entry, but TOML is not edited; compare it with the entry below")
        print("Add seers to another client with: seers-mcp --install FILE, or paste this entry:")
        print(json.dumps({"mcpServers": {NAME: entry()}}, indent=2))


def _origin() -> dict[str, Any]:
    """What pip recorded about where this installation came from; empty for an index install."""
    try:
        return json.loads(distribution(NAME).read_text("direct_url.json") or "{}")
    except ValueError:
        return {}


def _checkout() -> Path | None:
    """The source directory when seers is an editable install, which pip must not replace."""
    origin = _origin()
    if not origin.get("dir_info", {}).get("editable"):
        return None
    return Path(url2pathname(urlparse(origin["url"]).path))


def _source() -> str:
    """Where to upgrade from: the place seers was installed from, else the repository's main branch."""
    origin = _origin()
    if "url" not in origin:
        return f"{REPOSITORY}/archive/refs/heads/main.zip"
    vcs = origin.get("vcs_info", {}).get("vcs")
    return f"{vcs}+{origin['url']}" if vcs else origin["url"]


def upgrade(source: str | None = None) -> None:
    """Install the newest seers into this environment, then correct the client configurations.

    ``source`` is anything pip installs from; the default is where seers was installed from.
    """
    checkout = _checkout()
    if checkout is not None:
        command = ["git", "-C", str(checkout), "pull", "--ff-only"]
    else:
        requirement = f"seers[mcp] @ {source or _source()}"
        has_pip = subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True, check=False)
        installer = (
            [sys.executable, "-m", "pip", "install"]
            if has_pip.returncode == 0
            else ["uv", "pip", "install", "--python", sys.executable]  # uv environments have no pip
        )
        command = [*installer, "--upgrade", requirement]
    print(f"seers {__version__}: {' '.join(command)}", flush=True)
    try:
        subprocess.run(command, check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        hint = "nothing else was changed"
        if sys.platform == "win32" and checkout is None:
            # Windows cannot replace seers-mcp.exe while it runs, as this command or as a session.
            hint += f". Close agent sessions that use seers, then run: {sys.executable} -m seers.mcp --upgrade"
        raise SystemExit(f"seers-mcp: the upgrade failed ({error}); {hint}") from error
    # A new process: this one still runs the old code, and the new one may know more configs.
    subprocess.run([sys.executable, "-m", "seers.mcp", "--install"], check=True)
    print("Restart open agent sessions to use the new version.")
