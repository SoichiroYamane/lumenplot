"""Private value and error records used by the public backend module."""

from __future__ import annotations

from typing import Any


_UNSUPPORTED_TOKEN = "unsupported-capability"


class LumenPlotFallbackDiagnostic:
    """Immutable structured whole-frame fallback record."""

    __slots__ = (
        "_fallback_type",
        "_generation",
        "_kind",
        "_output_format",
        "_representation",
        "_scope",
        "_type_context",
    )

    def __init__(
        self,
        *,
        kind: str,
        type: str | None,
        generation: int,
        output_format: str = "png",
        scope: str = "whole-frame",
        representation: str = "raster",
        fallback_type: str = "matplotlib-agg",
    ) -> None:
        object.__setattr__(self, "_kind", kind)
        object.__setattr__(self, "_type_context", type)
        object.__setattr__(self, "_generation", int(generation))
        object.__setattr__(self, "_output_format", output_format)
        object.__setattr__(self, "_scope", scope)
        object.__setattr__(self, "_representation", representation)
        object.__setattr__(self, "_fallback_type", fallback_type)

    def __setattr__(self, name: str, value: Any) -> None:  # pragma: no cover
        raise AttributeError("LumenPlotFallbackDiagnostic is immutable")

    def __delattr__(self, name: str) -> None:  # pragma: no cover
        raise AttributeError("LumenPlotFallbackDiagnostic is immutable")

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def type(self) -> str | None:  # noqa: A003 - contract field name
        return self._type_context

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def output_format(self) -> str:
        return self._output_format

    @property
    def scope(self) -> str:
        return self._scope

    @property
    def representation(self) -> str:
        return self._representation

    @property
    def fallback_type(self) -> str:
        return self._fallback_type

    def __repr__(self) -> str:
        return (
            "LumenPlotFallbackDiagnostic("
            f"kind={self._kind!r}, type={self._type_context!r}, "
            f"generation={self._generation}, "
            f"output_format={self._output_format!r}, "
            f"scope={self._scope!r}, "
            f"representation={self._representation!r}, "
            f"fallback_type={self._fallback_type!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LumenPlotFallbackDiagnostic):
            return NotImplemented
        return (
            self._kind == other._kind
            and self._type_context == other._type_context
            and self._generation == other._generation
            and self._output_format == other._output_format
            and self._scope == other._scope
            and self._representation == other._representation
            and self._fallback_type == other._fallback_type
        )

    def __hash__(self) -> int:
        return hash(
            (
                self._kind,
                self._type_context,
                self._generation,
                self._output_format,
                self._scope,
                self._representation,
                self._fallback_type,
            )
        )


class LumenPlotPngResult:
    """Owned PNG bytes plus an immutable diagnostics tuple."""

    __slots__ = ("_diagnostics", "_png_bytes")

    def __init__(self, png_bytes: bytes, diagnostics: tuple) -> None:
        object.__setattr__(self, "_png_bytes", bytes(png_bytes))
        object.__setattr__(self, "_diagnostics", tuple(diagnostics))

    def __setattr__(self, name: str, value: Any) -> None:  # pragma: no cover
        raise AttributeError("LumenPlotPngResult is immutable")

    def __delattr__(self, name: str) -> None:  # pragma: no cover
        raise AttributeError("LumenPlotPngResult is immutable")

    @property
    def png_bytes(self) -> bytes:
        return self._png_bytes

    @property
    def diagnostics(self) -> tuple:
        return self._diagnostics

    def __repr__(self) -> str:
        return (
            "LumenPlotPngResult("
            f"{len(self._png_bytes)} bytes, "
            f"{len(self._diagnostics)} diagnostic(s))"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LumenPlotPngResult):
            return NotImplemented
        return (
            self._png_bytes == other._png_bytes
            and self._diagnostics == other._diagnostics
        )

    def __hash__(self) -> int:
        return hash((self._png_bytes, self._diagnostics))


class LumenPlotUnsupportedError(RuntimeError):
    """Explicit unsupported or terminal backend failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str = _UNSUPPORTED_TOKEN,
        type_context: str | None = None,
        generation: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.type_context = type_context
        self.generation = generation
