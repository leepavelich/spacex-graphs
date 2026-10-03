"""The base class for errors that mean the launch data can't be trusted."""


class DataError(RuntimeError):
    """The data can't be trusted, so the run fails rather than publishing.

    The CLI turns any DataError into a one-line message and exit code 1, so a
    new check only has to raise a subclass of this to be handled.
    """
