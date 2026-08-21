#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub(crate) struct SeriesId(pub(crate) u64);

impl SeriesId {
    pub(crate) fn next(value: &mut u64) -> Option<Self> {
        let id = *value;
        if id == 0 {
            return None;
        }
        *value = value.checked_add(1)?;
        Some(Self(id))
    }
}
