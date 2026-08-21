#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct Point {
    pub(crate) source: u64,
    pub(crate) x: f64,
    pub(crate) y: f64,
}

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) struct GapSpan {
    pub(crate) start: u64,
    pub(crate) end: u64,
}

impl GapSpan {
    pub(crate) fn new(start: u64, end: u64) -> Option<Self> {
        (start < end).then_some(Self { start, end })
    }
}
