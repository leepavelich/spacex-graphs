"""The base class for errors that mean the launch data can't be trusted."""


class DataError(RuntimeError):
    """The data can't be trusted, so the run fails rather than publishing.

    The CLI turns any DataError into a one-line message and exit code 1, so a
    new check only has to raise a subclass of this to be handled.
    """


class ImplausibleMassError(DataError):
    """A reported mass is outside the plausible bounds for its vehicle."""


class OutcomeIntegrityError(DataError):
    """Launch outcomes don't look like the values expected from Wikipedia."""


class PublishedCsvError(DataError):
    """The published launch baseline CSV is malformed."""
