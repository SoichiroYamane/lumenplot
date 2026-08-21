use std::fmt;

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum ExportErrorKind {
    InvalidInput,
    UnsupportedCapability,
    CapacityExceeded,
    AllocationFailed,
    EncodingFailed,
    Internal,
}

#[derive(Clone, Eq, PartialEq)]
pub struct ExportError {
    kind: ExportErrorKind,
    message: &'static str,
}

impl ExportError {
    pub(crate) const fn new(kind: ExportErrorKind, message: &'static str) -> Self {
        Self { kind, message }
    }

    pub(crate) const fn invalid_input() -> Self {
        Self::new(ExportErrorKind::InvalidInput, "input is invalid")
    }

    pub(crate) const fn capacity_exceeded() -> Self {
        Self::new(
            ExportErrorKind::CapacityExceeded,
            "export capacity exceeded",
        )
    }

    pub(crate) const fn allocation_failed() -> Self {
        Self::new(
            ExportErrorKind::AllocationFailed,
            "export allocation failed",
        )
    }

    pub(crate) const fn encoding_failed() -> Self {
        Self::new(ExportErrorKind::EncodingFailed, "PNG encoding failed")
    }

    pub(crate) const fn internal() -> Self {
        Self::new(ExportErrorKind::Internal, "internal export error")
    }

    pub fn kind(&self) -> ExportErrorKind {
        self.kind
    }

    pub fn message(&self) -> &str {
        self.message
    }
}

impl fmt::Debug for ExportError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ExportError")
            .field("kind", &self.kind)
            .field("message", &self.message)
            .finish()
    }
}

impl fmt::Display for ExportError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.message)
    }
}

impl std::error::Error for ExportError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_error_kind_has_a_sanitized_surface() {
        let kinds = [
            ExportErrorKind::InvalidInput,
            ExportErrorKind::UnsupportedCapability,
            ExportErrorKind::CapacityExceeded,
            ExportErrorKind::AllocationFailed,
            ExportErrorKind::EncodingFailed,
            ExportErrorKind::Internal,
        ];
        for kind in kinds {
            let error = ExportError::new(kind, "safe message");
            assert_eq!(error.kind(), kind);
            assert_eq!(error.message(), "safe message");
            assert_eq!(error.to_string(), "safe message");
            assert!(std::error::Error::source(&error).is_none());
            assert!(!format!("{error:?}").contains("crate"));
        }
    }
}
