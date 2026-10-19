class DomainError(Exception):
    """A business rule rejected the command (HTTP 400)."""


class InvalidInput(DomainError):
    """The command's data is malformed, e.g. a negative price (HTTP 422)."""


class InsufficientStock(DomainError):
    """Dispatching or adjusting would take stock below zero (HTTP 409)."""


class NotFound(DomainError):
    """The aggregate (product/user) has no events, so it does not exist (HTTP 404)."""


class AlreadyExists(DomainError):
    """Tried to create an aggregate whose stream already has events (HTTP 409)."""


class ConcurrencyError(DomainError):
    """Someone else appended to the stream after we loaded it (HTTP 409)."""