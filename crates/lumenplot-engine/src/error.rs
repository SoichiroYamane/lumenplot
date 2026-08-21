#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub(crate) enum SceneErrorKind {
    InvalidInput,
    UnsupportedCapability,
    InvalidState,
    SeriesNotFound,
    TopologyViolation,
    NonFiniteCanonical,
    CapacityExceeded,
    AllocationFailed,
    IdentityExhausted,
    RevisionExhausted,
    Internal,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct SceneError {
    kind: SceneErrorKind,
}

impl SceneError {
    pub(crate) fn new(kind: SceneErrorKind) -> Self {
        Self { kind }
    }

    pub(crate) fn kind(&self) -> SceneErrorKind {
        self.kind
    }

    pub(crate) fn message(&self) -> &'static str {
        match self.kind {
            SceneErrorKind::InvalidInput => "input is invalid",
            SceneErrorKind::UnsupportedCapability => "capability is unsupported",
            SceneErrorKind::InvalidState => "scene state is invalid",
            SceneErrorKind::SeriesNotFound => "series was not found",
            SceneErrorKind::TopologyViolation => "series topology is invalid",
            SceneErrorKind::NonFiniteCanonical => "canonical values must be finite",
            SceneErrorKind::CapacityExceeded => "capacity is exceeded",
            SceneErrorKind::AllocationFailed => "allocation failed",
            SceneErrorKind::IdentityExhausted => "identity space is exhausted",
            SceneErrorKind::RevisionExhausted => "revision space is exhausted",
            SceneErrorKind::Internal => "internal engine error",
        }
    }
}
