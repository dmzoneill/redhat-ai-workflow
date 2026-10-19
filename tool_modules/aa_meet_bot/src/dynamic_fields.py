"""Shared attribute fallback for classes that store state in ``__dict__``."""


class DynamicFields:  # pylint: disable=too-few-public-methods
    """Base for objects whose fields are written through ``__dict__``.

    ``too-few-public-methods`` is disabled because this base only exists so
    pylint accepts dynamically stored attributes. It adds no public API.
    """

    def __getattr__(self, name: str):
        """Missing attributes still raise AttributeError."""
        raise AttributeError(name)
