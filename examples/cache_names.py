"""Search auto-updating game cache names: python examples/cache_names.py."""

from rich.console import Console

from seers import Cache


def main() -> None:
    # The first access downloads a snapshot; later accesses refresh it after 24 hours.
    cache = Cache(auto_update=True)
    console = Console()
    console.print(cache.items.search("abyssal whip", limit=5))
    console.print(str(cache.path), style="dim", markup=False)


if __name__ == "__main__":
    main()
