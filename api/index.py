import os
from typing import Iterable, MutableSet
from flask import Flask, redirect


PREFIX = "/"
BASEDIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASEDIR, *[os.path.pardir, "templates"]),
    static_folder=os.path.join(BASEDIR, *[os.path.pardir, "static"]),
)


@app.template_global("classlist")
class ClassList(MutableSet):
    """Data structure for holding, and ultimately returning as a single string,
    a set of identifiers that should be managed like CSS classes.
    """

    def __init__(self, arg: str | Iterable | None = None, *args: str):
        """Constructor.
        :param arg: A single class name or an iterable thereof.
        """
        if isinstance(arg, str):
            classes = arg.split()
        elif isinstance(arg, Iterable):
            classes = arg
        elif arg is not None:
            raise TypeError("expected a string or string iterable, got %r" % type(arg))

        self.classes = set(filter(None, classes))
        if args:
            self.classes.update(args)

    def __contains__(self, class_):
        return class_ in self.classes

    def __iter__(self):
        return iter(self.classes)

    def __len__(self):
        return len(self.classes)

    def add(self, *classes):
        for class_ in classes:
            self.classes.add(class_)
        return ""

    def discard(self, *classes):
        for class_ in classes:
            self.classes.discard(class_)

        return ""

    def __str__(self):
        return " ".join(sorted(self.classes))

    def __html__(self):
        return 'class="%s"' % self if self else ""


@app.route(PREFIX)
def index():
    return redirect("/api/ytdl", code=302)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
