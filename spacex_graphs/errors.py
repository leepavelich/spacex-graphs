"""The errors that mean the launch data can't be trusted.

Every one is a DataError, which the CLI turns into a one-line message and exit
code 1. The cache's fetch errors subclass it in cache.py, next to the code
that raises them.
"""


class DataError(RuntimeError):
    """The data can't be trusted, so the run fails rather than publishing.

    The CLI turns any DataError into a one-line message and exit code 1, so a
    new check only has to raise a subclass of this to be handled.
    """


class EmptyPageError(DataError):
    """A Wikipedia page yielded no launch records."""


class MissingYearsError(DataError):
    """Past years that should have launches have none."""


class NoRecentLaunchesError(DataError):
    """No launches were found, or the newest one is too old."""


class ImplausibleMassError(DataError):
    """A reported mass is outside the plausible bounds for its vehicle."""


class OutcomeIntegrityError(DataError):
    """Launch outcomes don't look like the values expected from Wikipedia."""


class PublishedLaunchesLostError(DataError):
    """Published launches or masses went missing or materially regressed."""


class PublishedCsvError(DataError):
    """The published launch baseline CSV is malformed."""
