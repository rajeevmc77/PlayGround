"""Failures a PairJudge reports, split by whether retrying can help."""


class JudgeError(Exception):
    """Base of every judge failure."""


class RateLimited(JudgeError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class Transient(JudgeError):
    """A 5xx, timeout or dropped connection: worth retrying."""


class Permanent(JudgeError):
    """A rejected request (bad input, bad key): retrying cannot help."""
