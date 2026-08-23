"""Private Phase-3A helper package."""


class LumenPlotError(RuntimeError):
    """Structured error raised by the private native helper."""

    __slots__ = ("_code", "_category", "_message")

    def __init__(self, code: str, category: str, message: str) -> None:
        super().__init__(message)
        self._code = code
        self._category = category
        self._message = message

    @property
    def code(self) -> str:
        return self._code

    @property
    def category(self) -> str:
        return self._category

    @property
    def message(self) -> str:
        return self._message

    def __str__(self) -> str:
        return self._message


__all__ = ["LumenPlotError"]
