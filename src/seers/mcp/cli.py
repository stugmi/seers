"""``seers-mcp`` / ``python -m seers.mcp``.

Kept apart from ``seers.mcp.server`` so the default mode, the relay an MCP client
launches once per session, starts without importing the MCP SDK.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from seers.mcp.relay import DEFAULT_PORT


def _server_options(args: argparse.Namespace) -> list[str]:
    """The options that configure a server, normalised: a relay passes them to the server it
    starts, and a running server accepts only relays that ask for the same ones."""
    # float(): an untouched default is still an int, and the server must derive the same text.
    options = ["--max-age", repr(float(args.max_age)), "--idle-timeout", repr(float(args.idle_timeout))]
    if args.cache_path is not None:
        options += ["--cache-path", str(args.cache_path.resolve())]
    if args.cache_dir is not None:
        options += ["--cache-dir", str(args.cache_dir.resolve())]
    if args.auto_update:
        options.append("--auto-update")
    if args.no_sync:
        options.append("--no-sync")
    return options


def main(argv: list[str] | None = None) -> None:
    """Serve the tools to the stdio client that launched this process, through the shared server."""
    parser = argparse.ArgumentParser(
        prog="seers-mcp",
        description="seers MCP server. Without --serve or --port: a stdio session on the shared "
        "server, which is started if it is not running and exits once no client uses it.",
    )
    parser.add_argument("--cache-path", type=Path, help="Use your own cache.db or directory")
    parser.add_argument("--cache-dir", type=Path, help="Where downloaded snapshots are stored")
    parser.add_argument("--auto-update", action="store_true", help="Refresh the cache when it is read")
    parser.add_argument("--max-age", type=float, default=86400, help="Refresh interval in seconds")
    parser.add_argument("--no-sync", action="store_true", help="Do not check OpenRS2 for a changed cache at startup")
    parser.add_argument("--shared-port", type=int, default=DEFAULT_PORT, help=f"Loopback port of the shared server (default: {DEFAULT_PORT})")
    parser.add_argument("--idle-timeout", type=float, default=60, help="Seconds the shared server stays up after its last client leaves (default: 60)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--serve", action="store_true", help="Be the shared server, in the foreground; stdio sessions start it themselves")
    mode.add_argument("--port", type=int, help="Serve streamable HTTP on this port instead")
    mode.add_argument("--install", nargs="*", type=Path, metavar="FILE", help="Write this installation's server entry into MCP client config files and exit: the given JSON files, or with none, every known client config that already has a seers entry")
    mode.add_argument("--upgrade", nargs="?", const="", metavar="SOURCE", help="Install the newest seers into this environment, then check and correct the client configs as --install does. SOURCE is anything pip accepts (default: the repository's main branch)")
    parser.add_argument("--host", default="127.0.0.1", help="Interface for --port (default: loopback only)")
    args = parser.parse_args(argv)
    if args.install is not None:
        from seers.mcp.install import install

        install(args.install)
        return
    if args.upgrade is not None:
        from seers.mcp.install import upgrade

        upgrade(args.upgrade or None)
        return
    if args.cache_path is not None and (args.auto_update or args.cache_dir is not None):
        parser.error("--cache-path cannot be combined with --auto-update or --cache-dir")
    if not args.idle_timeout >= 0:
        parser.error("--idle-timeout cannot be negative")

    options = _server_options(args)
    if not args.serve and args.port is None:
        from seers.mcp import relay

        relay.run(args.shared_port, options)
        return

    settings = {
        "cache_path": args.cache_path,
        "cache_dir": args.cache_dir,
        "auto_update": args.auto_update,
        "max_age": args.max_age,
        "sync_on_start": not args.no_sync,
    }
    if args.serve:
        import anyio

        from seers.mcp import shared

        anyio.run(lambda: shared.serve(args.shared_port, options, args.idle_timeout, **settings))
    else:
        from seers.mcp.server import SeersMCP

        SeersMCP(**settings).run("streamable-http", host=args.host, port=args.port)
