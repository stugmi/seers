"""``seers-wiki``: read an OSRS Wiki page in the terminal."""

import argparse

from rich.console import Console

from seers.client import Client
from seers.errors import OSRSError


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Read an OSRS Wiki page in your terminal")
    parser.add_argument("page", nargs="?", default="Mark of grace")
    parser.add_argument("--pager", action="store_true", help="Read one screen at a time")
    parser.add_argument("--width", type=int, default=100, help="Maximum reading width (default: 100)")
    args = parser.parse_args(argv)
    if args.width < 1:
        parser.error("--width must be positive")
    try:
        with Client() as client:
            page = client.wiki.page(args.page)
    except OSRSError as error:
        Console(stderr=True).print(f"Could not load page: {error}", style="bold red", markup=False)
        raise SystemExit(1) from error
    page.show(pager=args.pager, width=args.width)


if __name__ == "__main__":
    main()
