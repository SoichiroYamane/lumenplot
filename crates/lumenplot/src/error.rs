use std::fmt;

use lumenplot_engine::bridge::{
    SceneError as EngineSceneError, SceneErrorKind as EngineSceneErrorKind,
};

#[non_exhaustive]
pub enum ErrorCode {
    InvalidInput,
    UnsupportedCapability,
    Closed,
    InvalidState,
    HostLoopMisuse,
    Reentrancy,
    BackendUnavailable,
    DeviceLost,
    RecoveryFailed,
    OutOfMemory,
    ResourceInvalid,
    Internal,
}

impl ErrorCode {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::InvalidInput => "invalid-input",
            Self::UnsupportedCapability => "unsupported-capability",
            Self::Closed => "closed",
            Self::InvalidState => "invalid-state",
            Self::HostLoopMisuse => "host-loop-misuse",
            Self::Reentrancy => "reentrancy",
            Self::BackendUnavailable => "backend-unavailable",
            Self::DeviceLost => "device-lost",
            Self::RecoveryFailed => "recovery-failed",
            Self::OutOfMemory => "out-of-memory",
            Self::ResourceInvalid => "resource-invalid",
            Self::Internal => "internal",
        }
    }
}

#[non_exhaustive]
pub enum ErrorCategory {
    Input,
    Capability,
    Lifecycle,
    Host,
    Backend,
    Resource,
    Internal,
}

impl ErrorCategory {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Input => "input",
            Self::Capability => "capability",
            Self::Lifecycle => "lifecycle",
            Self::Host => "host",
            Self::Backend => "backend",
            Self::Resource => "resource",
            Self::Internal => "internal",
        }
    }
}

pub struct PublicError {
    code: ErrorCode,
    message: &'static str,
}

impl PublicError {
    pub fn code(&self) -> ErrorCode {
        match &self.code {
            ErrorCode::InvalidInput => ErrorCode::InvalidInput,
            ErrorCode::UnsupportedCapability => ErrorCode::UnsupportedCapability,
            ErrorCode::Closed => ErrorCode::Closed,
            ErrorCode::InvalidState => ErrorCode::InvalidState,
            ErrorCode::HostLoopMisuse => ErrorCode::HostLoopMisuse,
            ErrorCode::Reentrancy => ErrorCode::Reentrancy,
            ErrorCode::BackendUnavailable => ErrorCode::BackendUnavailable,
            ErrorCode::DeviceLost => ErrorCode::DeviceLost,
            ErrorCode::RecoveryFailed => ErrorCode::RecoveryFailed,
            ErrorCode::OutOfMemory => ErrorCode::OutOfMemory,
            ErrorCode::ResourceInvalid => ErrorCode::ResourceInvalid,
            ErrorCode::Internal => ErrorCode::Internal,
        }
    }

    pub fn category(&self) -> ErrorCategory {
        match &self.code {
            ErrorCode::InvalidInput => ErrorCategory::Input,
            ErrorCode::UnsupportedCapability => ErrorCategory::Capability,
            ErrorCode::Closed | ErrorCode::InvalidState => ErrorCategory::Lifecycle,
            ErrorCode::HostLoopMisuse | ErrorCode::Reentrancy => ErrorCategory::Host,
            ErrorCode::BackendUnavailable | ErrorCode::DeviceLost | ErrorCode::RecoveryFailed => {
                ErrorCategory::Backend
            }
            ErrorCode::OutOfMemory | ErrorCode::ResourceInvalid => ErrorCategory::Resource,
            ErrorCode::Internal => ErrorCategory::Internal,
        }
    }

    pub fn message(&self) -> &str {
        self.message
    }

    pub(crate) fn from_engine(error: EngineSceneError) -> Self {
        Self::from_engine_kind(error.kind())
    }

    fn from_engine_kind(kind: EngineSceneErrorKind) -> Self {
        let (code, message) = match kind {
            EngineSceneErrorKind::InvalidInput => (ErrorCode::InvalidInput, "input is invalid"),
            EngineSceneErrorKind::UnsupportedCapability => (
                ErrorCode::UnsupportedCapability,
                "capability is unsupported",
            ),
            EngineSceneErrorKind::InvalidState => {
                (ErrorCode::InvalidState, "scene state is invalid")
            }
            EngineSceneErrorKind::SeriesNotFound => {
                (ErrorCode::ResourceInvalid, "series is invalid")
            }
            EngineSceneErrorKind::TopologyViolation => {
                (ErrorCode::InvalidInput, "series topology is invalid")
            }
            EngineSceneErrorKind::NonFiniteCanonical => {
                (ErrorCode::InvalidInput, "canonical values must be finite")
            }
            EngineSceneErrorKind::CapacityExceeded => {
                (ErrorCode::InvalidInput, "input capacity is exceeded")
            }
            EngineSceneErrorKind::AllocationFailed => (ErrorCode::OutOfMemory, "allocation failed"),
            EngineSceneErrorKind::IdentityExhausted => {
                (ErrorCode::Internal, "identity space is exhausted")
            }
            EngineSceneErrorKind::RevisionExhausted => {
                (ErrorCode::Internal, "revision space is exhausted")
            }
            EngineSceneErrorKind::Internal => (ErrorCode::Internal, "internal error"),
        };
        Self { code, message }
    }
}

impl fmt::Debug for PublicError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PublicError")
            .field("code", &self.code.as_str())
            .field("category", &self.category().as_str())
            .field("message", &self.message)
            .finish()
    }
}

impl fmt::Display for PublicError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.message)
    }
}

impl std::error::Error for PublicError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn engine_error_mapping_is_exhaustive_and_sanitized() {
        let cases = [
            (EngineSceneErrorKind::InvalidInput, "invalid-input", "input"),
            (
                EngineSceneErrorKind::TopologyViolation,
                "invalid-input",
                "input",
            ),
            (
                EngineSceneErrorKind::NonFiniteCanonical,
                "invalid-input",
                "input",
            ),
            (
                EngineSceneErrorKind::CapacityExceeded,
                "invalid-input",
                "input",
            ),
            (
                EngineSceneErrorKind::UnsupportedCapability,
                "unsupported-capability",
                "capability",
            ),
            (
                EngineSceneErrorKind::InvalidState,
                "invalid-state",
                "lifecycle",
            ),
            (
                EngineSceneErrorKind::SeriesNotFound,
                "resource-invalid",
                "resource",
            ),
            (
                EngineSceneErrorKind::AllocationFailed,
                "out-of-memory",
                "resource",
            ),
            (
                EngineSceneErrorKind::IdentityExhausted,
                "internal",
                "internal",
            ),
            (
                EngineSceneErrorKind::RevisionExhausted,
                "internal",
                "internal",
            ),
            (EngineSceneErrorKind::Internal, "internal", "internal"),
        ];

        for (kind, code, category) in cases {
            let error = PublicError::from_engine_kind(kind);
            assert_eq!(error.code().as_str(), code);
            assert_eq!(error.category().as_str(), category);
            assert!(!error.message().is_empty());
            assert!(!error.message().contains("crate"));
            assert!(!error.message().contains("0x"));
            assert!(std::error::Error::source(&error).is_none());
        }
    }
}
