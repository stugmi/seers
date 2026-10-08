"""Search automatically refreshed definitions: python examples/definitions.py."""

from rich.console import Console

from seers import Definitions


def main() -> None:
    # First access fetches definitions; later accesses refresh after 24 hours.
    data = Definitions(auto_update=True)
    console = Console()
    console.print(data.items.search("abyssal whip", limit=5))
    console.print(str(data.data_dir), style="dim", markup=False)


if __name__ == "__main__":
    main()
