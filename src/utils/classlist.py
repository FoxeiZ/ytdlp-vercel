from collections.abc import Iterable, MutableSet


class ClassList(MutableSet[str]):
    def __init__(self, arg: str | Iterable[str] | None = None, *args: str):
        classes: Iterable[str] = []
        if isinstance(arg, str):
            classes = arg.split()
        elif isinstance(arg, Iterable):
            classes = arg
        elif arg is not None:
            raise TypeError("expected a string or string iterable")
        self.classes = set(filter(None, classes))
        if args:
            self.classes.update(args)

    def __contains__(self, class_: object):
        return class_ in self.classes

    def __iter__(self):
        return iter(self.classes)

    def __len__(self):
        return len(self.classes)

    def add(self, *classes: str):  # type: ignore[override]
        for class_ in classes:
            self.classes.add(class_)
        return ""

    def discard(self, *classes: str):  # type: ignore[override]
        for class_ in classes:
            self.classes.discard(class_)
        return ""

    def __str__(self):
        return " ".join(sorted(self.classes))

    def __html__(self):
        return f'class="{self}"' if self else ""
