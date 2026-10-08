"""Read Mark of Grace: python examples/mark_of_grace.py."""

from seers import wiki


def main() -> None:
    wiki.page("Mark of Grace").show(pager=True)


if __name__ == "__main__":
    main()
