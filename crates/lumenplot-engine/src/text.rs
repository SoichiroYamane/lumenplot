use crate::error::{SceneError, SceneErrorKind};

const LAYOUT_VERSION: u32 = 1;
const FIXTURE_FONT_BYTES: &[u8] =
    b"LUMENPLOT-BUNDLED-FONT-FIXTURE-V1\nlicense=MIT-OR-APACHE-2.0\nfsType=0\nface=0\n";

/// The semantic owner of one retained text run.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum TextRole {
    NumericTick,
    DateTick,
    UnitTick,
    AxisLabel,
    AxisTitle,
    LegendEntry,
}

impl TextRole {
    fn tag(self) -> u8 {
        match self {
            Self::NumericTick => 1,
            Self::DateTick => 2,
            Self::UnitTick => 3,
            Self::AxisLabel => 4,
            Self::AxisTitle => 5,
            Self::LegendEntry => 6,
        }
    }
}

/// Text direction retained with the shaping result.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum TextDirection {
    LeftToRight,
    RightToLeft,
}

impl TextDirection {
    fn tag(self) -> u8 {
        match self {
            Self::LeftToRight => 1,
            Self::RightToLeft => 2,
        }
    }
}

/// The route that resolved a shaped run to its font identity.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum FallbackRoute {
    PrimaryFont,
    StrictError,
}

impl FallbackRoute {
    fn tag(self) -> u8 {
        match self {
            Self::PrimaryFont => 1,
            Self::StrictError => 2,
        }
    }
}

/// A normalized OpenType variation axis retained with a font identity.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct FontVariation {
    tag: [u8; 4],
    value: f64,
}

impl FontVariation {
    fn new(tag: [u8; 4], value: f64) -> Result<Self, SceneError> {
        if !value.is_finite() || tag == [0; 4] {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        Ok(Self { tag, value })
    }

    pub fn tag(&self) -> [u8; 4] {
        self.tag
    }

    pub fn value(&self) -> f64 {
        self.value
    }
}

/// One retained shaping feature setting.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FontFeature {
    tag: [u8; 4],
    value: u32,
}

impl FontFeature {
    fn new(tag: [u8; 4], value: u32) -> Result<Self, SceneError> {
        if tag == [0; 4] {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        Ok(Self { tag, value })
    }

    pub fn tag(&self) -> [u8; 4] {
        self.tag
    }

    pub fn value(&self) -> u32 {
        self.value
    }
}

/// Exact font identity captured by one shaping result.
#[derive(Clone, Debug, PartialEq)]
pub struct FontIdentity {
    font_bytes_sha256: [u8; 32],
    face_index: u32,
    normalized_variation: Vec<FontVariation>,
    features: Vec<FontFeature>,
    script: String,
    language: String,
    direction: TextDirection,
}

impl FontIdentity {
    fn fixture() -> Result<Self, SceneError> {
        Self::from_bytes(
            FIXTURE_FONT_BYTES,
            0,
            vec![FontVariation::new(*b"wght", 400.0)?],
            vec![FontFeature::new(*b"kern", 1)?],
            "Latn",
            "en",
            TextDirection::LeftToRight,
        )
    }

    fn from_bytes(
        font_bytes: &[u8],
        face_index: u32,
        normalized_variation: Vec<FontVariation>,
        features: Vec<FontFeature>,
        script: &str,
        language: &str,
        direction: TextDirection,
    ) -> Result<Self, SceneError> {
        if font_bytes.is_empty() || script.is_empty() || language.is_empty() {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        let font_bytes_sha256 =
            sha256(font_bytes).ok_or_else(|| SceneError::new(SceneErrorKind::AllocationFailed))?;
        let identity = Self {
            font_bytes_sha256,
            face_index,
            normalized_variation,
            features,
            script: script.to_owned(),
            language: language.to_owned(),
            direction,
        };
        if identity.is_valid() {
            Ok(identity)
        } else {
            Err(SceneError::new(SceneErrorKind::InvalidInput))
        }
    }

    pub fn font_bytes_sha256(&self) -> [u8; 32] {
        self.font_bytes_sha256
    }

    pub fn face_index(&self) -> u32 {
        self.face_index
    }

    pub fn normalized_variation(&self) -> &[FontVariation] {
        &self.normalized_variation
    }

    pub fn features(&self) -> &[FontFeature] {
        &self.features
    }

    pub fn script(&self) -> &str {
        &self.script
    }

    pub fn language(&self) -> &str {
        &self.language
    }

    pub fn direction(&self) -> TextDirection {
        self.direction
    }

    fn is_valid(&self) -> bool {
        !self
            .normalized_variation
            .windows(2)
            .any(|pair| pair[0].tag >= pair[1].tag)
            && !self
                .features
                .windows(2)
                .any(|pair| pair[0].tag >= pair[1].tag)
            && !self.script.is_empty()
            && !self.language.is_empty()
            && self
                .normalized_variation
                .iter()
                .all(|variation| variation.value.is_finite() && variation.tag != [0; 4])
            && self.features.iter().all(|feature| feature.tag != [0; 4])
    }
}

/// A finite logical glyph position retained by a shaped run.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct GlyphPosition {
    x: f64,
    y: f64,
    advance_x: f64,
    advance_y: f64,
}

impl GlyphPosition {
    fn new(x: f64, y: f64, advance_x: f64, advance_y: f64) -> Result<Self, SceneError> {
        if ![x, y, advance_x, advance_y]
            .iter()
            .all(|value| value.is_finite())
        {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        Ok(Self {
            x,
            y,
            advance_x,
            advance_y,
        })
    }

    pub fn x(&self) -> f64 {
        self.x
    }

    pub fn y(&self) -> f64 {
        self.y
    }

    pub fn advance_x(&self) -> f64 {
        self.advance_x
    }

    pub fn advance_y(&self) -> f64 {
        self.advance_y
    }

    fn is_valid(self) -> bool {
        [self.x, self.y, self.advance_x, self.advance_y]
            .iter()
            .all(|value| value.is_finite())
    }
}

/// One immutable, already-shaped text run in the retained layout.
#[derive(Clone, Debug, PartialEq)]
pub struct ShapedRun {
    role: TextRole,
    source: String,
    clusters: Vec<u32>,
    glyph_ids: Vec<u32>,
    positions: Vec<GlyphPosition>,
    font: FontIdentity,
    clip_ref: u32,
    style_ref: u32,
    fallback_route: FallbackRoute,
}

impl ShapedRun {
    #[allow(clippy::too_many_arguments)]
    fn new(
        role: TextRole,
        source: String,
        clusters: Vec<u32>,
        glyph_ids: Vec<u32>,
        positions: Vec<GlyphPosition>,
        font: FontIdentity,
        clip_ref: u32,
        style_ref: u32,
        fallback_route: FallbackRoute,
    ) -> Result<Self, SceneError> {
        let valid_clusters = clusters.iter().all(|cluster| {
            usize::try_from(*cluster)
                .ok()
                .is_some_and(|index| index <= source.len() && source.is_char_boundary(index))
        });
        let ordered_clusters = !clusters.windows(2).any(|pair| pair[0] > pair[1]);
        if source.is_empty()
            || clusters.len() != glyph_ids.len()
            || glyph_ids.len() != positions.len()
            || !valid_clusters
            || !ordered_clusters
            || glyph_ids.contains(&0)
            || positions.iter().any(|position| !position.is_valid())
            || clip_ref == 0
            || style_ref == 0
            || !font.is_valid()
        {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        Ok(Self {
            role,
            source,
            clusters,
            glyph_ids,
            positions,
            font,
            clip_ref,
            style_ref,
            fallback_route,
        })
    }

    fn clusters_are_valid(&self) -> bool {
        self.clusters.len() == self.glyph_ids.len()
            && !self.clusters.windows(2).any(|pair| pair[0] > pair[1])
            && self.clusters.iter().all(|cluster| {
                usize::try_from(*cluster).ok().is_some_and(|index| {
                    index <= self.source.len() && self.source.is_char_boundary(index)
                })
            })
    }

    pub fn role(&self) -> TextRole {
        self.role
    }

    pub fn source(&self) -> &str {
        &self.source
    }

    pub fn clusters(&self) -> &[u32] {
        &self.clusters
    }

    pub fn glyph_ids(&self) -> &[u32] {
        &self.glyph_ids
    }

    pub fn positions(&self) -> &[GlyphPosition] {
        &self.positions
    }

    pub fn font(&self) -> &FontIdentity {
        &self.font
    }

    pub fn clip_ref(&self) -> u32 {
        self.clip_ref
    }

    pub fn style_ref(&self) -> u32 {
        self.style_ref
    }

    pub fn fallback_route(&self) -> FallbackRoute {
        self.fallback_route
    }

    fn append_canonical_bytes(&self, bytes: &mut Vec<u8>) -> bool {
        bytes.push(self.role.tag());
        if !append_string(bytes, &self.source) {
            return false;
        }
        if !append_u32_slice(bytes, &self.clusters)
            || !append_u32_slice(bytes, &self.glyph_ids)
            || !append_u64(bytes, u64::from(self.clip_ref))
            || !append_u64(bytes, u64::from(self.style_ref))
        {
            return false;
        }
        if self.positions.len() > usize::MAX / 32 {
            return false;
        }
        if bytes.try_reserve(self.positions.len() * 32).is_err() {
            return false;
        }
        for position in &self.positions {
            bytes.extend_from_slice(&position.x.to_bits().to_le_bytes());
            bytes.extend_from_slice(&position.y.to_bits().to_le_bytes());
            bytes.extend_from_slice(&position.advance_x.to_bits().to_le_bytes());
            bytes.extend_from_slice(&position.advance_y.to_bits().to_le_bytes());
        }
        bytes.extend_from_slice(&self.font.font_bytes_sha256);
        if !append_u64(bytes, u64::from(self.font.face_index)) {
            return false;
        }
        if self.font.normalized_variation.len() > usize::MAX / 16
            || bytes
                .try_reserve(self.font.normalized_variation.len() * 16)
                .is_err()
            || !append_u64(
                bytes,
                u64::try_from(self.font.normalized_variation.len())
                    .ok()
                    .unwrap_or(u64::MAX),
            )
        {
            return false;
        }
        for variation in &self.font.normalized_variation {
            bytes.extend_from_slice(&variation.tag);
            bytes.extend_from_slice(&variation.value.to_bits().to_le_bytes());
        }
        if self.font.features.len() > usize::MAX / 8
            || bytes.try_reserve(self.font.features.len() * 8).is_err()
            || !append_u64(
                bytes,
                u64::try_from(self.font.features.len())
                    .ok()
                    .unwrap_or(u64::MAX),
            )
        {
            return false;
        }
        for feature in &self.font.features {
            bytes.extend_from_slice(&feature.tag);
            bytes.extend_from_slice(&feature.value.to_le_bytes());
        }
        if !append_string(bytes, &self.font.script) || !append_string(bytes, &self.font.language) {
            return false;
        }
        bytes.push(self.font.direction.tag());
        bytes.push(self.fallback_route.tag());
        true
    }
}

/// One retained layout shared by all output consumers.
#[derive(Clone, Debug, PartialEq)]
pub struct PlotLayout {
    runs: Vec<ShapedRun>,
    font_revision: u64,
    layout_revision: u64,
    layout_digest: [u8; 32],
}

impl PlotLayout {
    /// Deterministic B1 fixture: runs are pre-shaped and contain no renderer
    /// measurement callback or platform font object.
    pub(crate) fn fixture() -> Result<Self, SceneError> {
        let font = FontIdentity::fixture()?;
        let runs = vec![
            fixture_run(TextRole::NumericTick, "0.0", &font, (16.0, 16.0))?,
            fixture_run(TextRole::DateTick, "2026-01-01", &font, (32.0, 16.0))?,
            fixture_run(TextRole::UnitTick, "mm", &font, (48.0, 16.0))?,
            fixture_run(TextRole::AxisLabel, "x", &font, (64.0, 32.0))?,
            fixture_run(TextRole::AxisTitle, "measurement", &font, (64.0, 48.0))?,
            fixture_run(TextRole::LegendEntry, "series-0", &font, (72.0, 64.0))?,
        ];
        Self::from_runs(runs, 0, 0)
    }

    fn from_runs(
        runs: Vec<ShapedRun>,
        font_revision: u64,
        layout_revision: u64,
    ) -> Result<Self, SceneError> {
        if runs.is_empty() {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        let layout_digest = canonical_digest(&runs)
            .ok_or_else(|| SceneError::new(SceneErrorKind::AllocationFailed))?;
        Ok(Self {
            runs,
            font_revision,
            layout_revision,
            layout_digest,
        })
    }

    pub(crate) fn with_layout_revision(&self, layout_revision: u64) -> Self {
        let mut next = self.clone();
        next.layout_revision = layout_revision;
        next
    }

    pub fn runs(&self) -> &[ShapedRun] {
        &self.runs
    }

    pub fn font_revision(&self) -> u64 {
        self.font_revision
    }

    pub fn layout_revision(&self) -> u64 {
        self.layout_revision
    }

    pub fn layout_digest(&self) -> [u8; 32] {
        self.layout_digest
    }

    /// Validates retained shape/layout invariants without measuring text.
    pub fn validate(&self) -> bool {
        !self.runs.is_empty()
            && self.runs.iter().all(|run| {
                !run.source.is_empty()
                    && run.clusters_are_valid()
                    && run.glyph_ids.len() == run.positions.len()
                    && run.glyph_ids.iter().all(|glyph_id| *glyph_id != 0)
                    && run.positions.iter().all(|position| position.is_valid())
                    && run.clip_ref != 0
                    && run.style_ref != 0
                    && run.font.is_valid()
            })
            && canonical_digest(&self.runs).is_some_and(|digest| digest == self.layout_digest)
    }

    /// Rejects a retained result after its scene/layout generation changes.
    pub fn validate_for_generation(&self, font_revision: u64, layout_revision: u64) -> bool {
        self.font_revision == font_revision
            && self.layout_revision == layout_revision
            && self.validate()
    }

    /// Derives one bounding box per legend run from retained origins.
    ///
    /// The boxes union each run's stored glyph cells, so hit-testing reads
    /// the same geometry the sinks draw without measuring text again. Runs
    /// without a finite glyph cell contribute no box.
    pub(crate) fn legend_entry_geometry(&self) -> Result<Vec<LegendEntryGeometry>, SceneError> {
        let mut entries = Vec::new();
        entries
            .try_reserve(self.runs.len())
            .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
        for run in &self.runs {
            if run.role() != TextRole::LegendEntry {
                continue;
            }
            let mut bounds: Option<(f64, f64, f64, f64)> = None;
            for position in run.positions() {
                let (x, y) = (position.x(), position.y());
                if !x.is_finite() || !y.is_finite() {
                    continue;
                }
                let right = x + LEGEND_GLYPH_CELL_WIDTH;
                let bottom = y + LEGEND_GLYPH_CELL_HEIGHT;
                if !right.is_finite() || !bottom.is_finite() {
                    continue;
                }
                bounds = Some(match bounds {
                    None => (x, y, right, bottom),
                    Some((x_min, y_min, x_max, y_max)) => (
                        x.min(x_min),
                        y.min(y_min),
                        right.max(x_max),
                        bottom.max(y_max),
                    ),
                });
            }
            if let Some((x_min, y_min, x_max, y_max)) = bounds {
                entries.push(LegendEntryGeometry {
                    entry: entries.len(),
                    x_min,
                    y_min,
                    x_max,
                    y_max,
                });
            }
        }
        Ok(entries)
    }

    /// Resolves one point to the legend entry below it, if any.
    ///
    /// This is a read path: it never mutates scene, layout, visibility, or
    /// transient state. A stale carrier fails instead of reporting against
    /// moved geometry, mirroring the frame-resolution gate. `hidden` carries
    /// the caller's visibility view aligned with
    /// [`Self::legend_entry_geometry`] order; a hidden entry keeps its box
    /// and still reports, so the returned flag preserves the hidden/visible
    /// distinction without owning visibility state here. Callers map the
    /// reported entry to a series key through the retained run source and
    /// the router's legend-entry target. Overlapping boxes resolve to the
    /// earliest entry in layout order.
    pub(crate) fn hit_legend_entry(
        &self,
        x: f64,
        y: f64,
        hidden: Option<&[bool]>,
        font_revision: u64,
        layout_revision: u64,
    ) -> Result<Option<LegendHit>, SceneError> {
        if !x.is_finite() || !y.is_finite() {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        if !self.validate_for_generation(font_revision, layout_revision) {
            return Err(SceneError::new(SceneErrorKind::Internal));
        }
        let entries = self.legend_entry_geometry()?;
        if hidden.is_some_and(|hidden| hidden.len() != entries.len()) {
            return Err(SceneError::new(SceneErrorKind::InvalidInput));
        }
        for geometry in &entries {
            if geometry.contains(x, y) {
                return Ok(Some(LegendHit {
                    entry: geometry.entry(),
                    hidden: hidden.map(|flags| flags[geometry.entry()]).unwrap_or(false),
                }));
            }
        }
        Ok(None)
    }
}

/// Logical fixture glyph-cell extent read by retained-geometry consumers.
///
/// Every stored glyph origin anchors one axis-aligned cell of this size. The
/// extent is a fixed property of the retained fixture, not a font query, so
/// entry boxes derived here agree with the fixture cells the sinks draw
/// without measuring text again.
pub(crate) const LEGEND_GLYPH_CELL_WIDTH: f64 = 5.0;
/// Logical fixture glyph-cell height; see [`LEGEND_GLYPH_CELL_WIDTH`].
pub(crate) const LEGEND_GLYPH_CELL_HEIGHT: f64 = 7.0;

/// Retained geometry of one legend entry in logical units.
///
/// One value is derived per [`TextRole::LegendEntry`] run, in run order.
#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct LegendEntryGeometry {
    entry: usize,
    x_min: f64,
    y_min: f64,
    x_max: f64,
    y_max: f64,
}

impl LegendEntryGeometry {
    /// Counts legend runs in layout order.
    pub(crate) fn entry(self) -> usize {
        self.entry
    }

    /// Returns the left edge of the retained box.
    pub(crate) fn x_min(self) -> f64 {
        self.x_min
    }

    /// Returns the top edge of the retained box.
    pub(crate) fn y_min(self) -> f64 {
        self.y_min
    }

    /// Returns the right edge of the retained box.
    pub(crate) fn x_max(self) -> f64 {
        self.x_max
    }

    /// Returns the bottom edge of the retained box.
    pub(crate) fn y_max(self) -> f64 {
        self.y_max
    }

    /// Returns whether the point rests inside the box, edges included.
    pub(crate) fn contains(self, x: f64, y: f64) -> bool {
        x >= self.x_min && x <= self.x_max && y >= self.y_min && y <= self.y_max
    }
}

/// Point-in-entry hit against retained legend geometry.
///
/// Callers map `entry` to a series key through the retained run source and
/// the router's legend-entry target; `hidden` preserves the caller's
/// visibility view for that entry.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct LegendHit {
    entry: usize,
    hidden: bool,
}

impl LegendHit {
    /// Counts legend runs in layout order.
    pub(crate) fn entry(self) -> usize {
        self.entry
    }

    /// Returns whether the caller's visibility view marks the entry hidden.
    pub(crate) fn hidden(self) -> bool {
        self.hidden
    }
}

fn fixture_run(
    role: TextRole,
    source: &str,
    font: &FontIdentity,
    origin: (f64, f64),
) -> Result<ShapedRun, SceneError> {
    // B1 deliberately has no shaper dependency. The fixture is strict: a
    // source character outside its captured glyph set is an explicit error,
    // never a silent blank or an implicit .notdef route.
    if !source
        .chars()
        .all(|character| character.is_ascii_graphic() || character == ' ')
    {
        return Err(SceneError::new(SceneErrorKind::UnsupportedCapability));
    }
    let mut clusters = Vec::new();
    let mut glyph_ids = Vec::new();
    let mut positions = Vec::new();
    if source.len() > usize::try_from(u32::MAX).unwrap_or(usize::MAX) {
        return Err(SceneError::new(SceneErrorKind::CapacityExceeded));
    }
    clusters
        .try_reserve(source.len())
        .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
    glyph_ids
        .try_reserve(source.len())
        .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
    positions
        .try_reserve(source.len())
        .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
    for (index, character) in source.chars().enumerate() {
        clusters.push(
            u32::try_from(index).map_err(|_| SceneError::new(SceneErrorKind::CapacityExceeded))?,
        );
        let glyph_id = u32::from(character);
        if glyph_id == 0 {
            return Err(SceneError::new(SceneErrorKind::UnsupportedCapability));
        }
        glyph_ids.push(glyph_id);
        let x = origin.0
            + f64::from(
                u32::try_from(index)
                    .map_err(|_| SceneError::new(SceneErrorKind::CapacityExceeded))?,
            ) * 8.0;
        positions.push(GlyphPosition::new(x, origin.1, 8.0, 0.0)?);
    }
    ShapedRun::new(
        role,
        source.to_owned(),
        clusters,
        glyph_ids,
        positions,
        font.clone(),
        1,
        1,
        FallbackRoute::PrimaryFont,
    )
}

fn canonical_digest(runs: &[ShapedRun]) -> Option<[u8; 32]> {
    let mut bytes = Vec::new();
    bytes.try_reserve(64).ok()?;
    bytes.extend_from_slice(b"lumenplot-plot-layout");
    bytes.extend_from_slice(&LAYOUT_VERSION.to_le_bytes());
    if !append_u64(&mut bytes, u64::try_from(runs.len()).ok()?) {
        return None;
    }
    for run in runs {
        if !run.append_canonical_bytes(&mut bytes) {
            return None;
        }
    }
    sha256(&bytes)
}

fn append_u64(bytes: &mut Vec<u8>, value: u64) -> bool {
    bytes.try_reserve(8).is_ok() && {
        bytes.extend_from_slice(&value.to_le_bytes());
        true
    }
}

fn append_string(bytes: &mut Vec<u8>, value: &str) -> bool {
    let length = match u64::try_from(value.len()) {
        Ok(length) => length,
        Err(_) => return false,
    };
    append_u64(bytes, length) && bytes.try_reserve(value.len()).is_ok() && {
        bytes.extend_from_slice(value.as_bytes());
        true
    }
}

fn append_u32_slice(bytes: &mut Vec<u8>, values: &[u32]) -> bool {
    let payload = match values.len().checked_mul(4) {
        Some(payload) => payload,
        None => return false,
    };
    let reserve = match payload.checked_add(8) {
        Some(reserve) => reserve,
        None => return false,
    };
    let length = match u64::try_from(values.len()) {
        Ok(length) => length,
        Err(_) => return false,
    };
    if bytes.try_reserve(reserve).is_err() || !append_u64(bytes, length) {
        return false;
    }
    for value in values {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    true
}

fn sha256(source: &[u8]) -> Option<[u8; 32]> {
    const INITIAL: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];
    const ROUND_CONSTANTS: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];

    let with_marker = source.len().checked_add(1)?;
    let with_length = with_marker.checked_add(8)?;
    let padding = (64 - (with_length % 64)) % 64;
    let padded_len = with_length.checked_add(padding)?;
    let bit_length = u64::try_from(source.len()).ok()?.checked_mul(8)?;

    let mut padded = Vec::new();
    padded.try_reserve_exact(padded_len).ok()?;
    padded.extend_from_slice(source);
    padded.push(0x80);
    padded.resize(padded_len - 8, 0);
    padded.extend_from_slice(&bit_length.to_be_bytes());

    let mut state = INITIAL;
    for chunk in padded.chunks_exact(64) {
        let mut words = [0u32; 64];
        for (index, word) in words[..16].iter_mut().enumerate() {
            let start = index * 4;
            *word = u32::from_be_bytes([
                chunk[start],
                chunk[start + 1],
                chunk[start + 2],
                chunk[start + 3],
            ]);
        }
        for index in 16..64 {
            let s0 = words[index - 15].rotate_right(7)
                ^ words[index - 15].rotate_right(18)
                ^ (words[index - 15] >> 3);
            let s1 = words[index - 2].rotate_right(17)
                ^ words[index - 2].rotate_right(19)
                ^ (words[index - 2] >> 10);
            words[index] = words[index - 16]
                .wrapping_add(s0)
                .wrapping_add(words[index - 7])
                .wrapping_add(s1);
        }

        let mut working = state;
        for index in 0..64 {
            let s1 = working[4].rotate_right(6)
                ^ working[4].rotate_right(11)
                ^ working[4].rotate_right(25);
            let choose = (working[4] & working[5]) ^ ((!working[4]) & working[6]);
            let temporary1 = working[7]
                .wrapping_add(s1)
                .wrapping_add(choose)
                .wrapping_add(ROUND_CONSTANTS[index])
                .wrapping_add(words[index]);
            let s0 = working[0].rotate_right(2)
                ^ working[0].rotate_right(13)
                ^ working[0].rotate_right(22);
            let majority =
                (working[0] & working[1]) ^ (working[0] & working[2]) ^ (working[1] & working[2]);
            let temporary2 = s0.wrapping_add(majority);

            working[7] = working[6];
            working[6] = working[5];
            working[5] = working[4];
            working[4] = working[3].wrapping_add(temporary1);
            working[3] = working[2];
            working[2] = working[1];
            working[1] = working[0];
            working[0] = temporary1.wrapping_add(temporary2);
        }
        for index in 0..8 {
            state[index] = state[index].wrapping_add(working[index]);
        }
    }

    let mut digest = [0u8; 32];
    for (index, word) in state.into_iter().enumerate() {
        digest[index * 4..index * 4 + 4].copy_from_slice(&word.to_be_bytes());
    }
    Some(digest)
}

#[cfg(test)]
mod tests {
    use super::*;

    const FIXTURE_FONT_SHA256: [u8; 32] = [
        0xc7, 0x7e, 0x54, 0xd9, 0x02, 0x7d, 0xb7, 0xb8, 0xaf, 0x82, 0x1d, 0x96, 0xd9, 0xbb, 0xa2,
        0x04, 0x31, 0x10, 0x0b, 0x94, 0x05, 0x5d, 0x42, 0x80, 0x4c, 0xb2, 0x95, 0xc7, 0x9e, 0xe4,
        0x3f, 0xb7,
    ];

    #[test]
    fn fixture_retains_all_required_text_families_and_font_identity() {
        let layout = PlotLayout::fixture().expect("fixture layout");
        assert!(layout.validate());
        assert_eq!(layout.font_revision(), 0);
        assert_eq!(layout.layout_revision(), 0);
        assert_eq!(layout.runs().len(), 6);
        assert_eq!(
            layout
                .runs()
                .iter()
                .map(|run| run.role())
                .collect::<Vec<_>>(),
            vec![
                TextRole::NumericTick,
                TextRole::DateTick,
                TextRole::UnitTick,
                TextRole::AxisLabel,
                TextRole::AxisTitle,
                TextRole::LegendEntry,
            ]
        );
        for run in layout.runs() {
            assert!(!run.source().is_empty());
            assert_eq!(run.clusters().len(), run.glyph_ids().len());
            assert_eq!(run.glyph_ids().len(), run.positions().len());
            assert_eq!(run.fallback_route(), FallbackRoute::PrimaryFont);
            assert_ne!(run.clip_ref(), 0);
            assert_ne!(run.style_ref(), 0);
            assert_eq!(run.font().face_index(), 0);
            assert_eq!(run.font().script(), "Latn");
            assert_eq!(run.font().language(), "en");
            assert_eq!(run.font().direction(), TextDirection::LeftToRight);
            assert_eq!(run.font().normalized_variation().len(), 1);
            assert_eq!(run.font().features().len(), 1);
            assert!(run.positions().iter().all(|position| {
                position.x().is_finite()
                    && position.y().is_finite()
                    && position.advance_x().is_finite()
                    && position.advance_y().is_finite()
            }));
        }
        assert_eq!(
            layout.runs()[0].font().font_bytes_sha256(),
            FIXTURE_FONT_SHA256
        );
    }

    #[test]
    fn fixture_font_hash_and_layout_digest_are_deterministic() {
        let first = PlotLayout::fixture().expect("first fixture");
        let second = PlotLayout::fixture().expect("second fixture");
        assert_eq!(first, second);
        assert_eq!(first.layout_digest(), second.layout_digest());
        assert_eq!(
            sha256(b"abc"),
            Some([
                0xba, 0x78, 0x16, 0xbf, 0x8f, 0x01, 0xcf, 0xea, 0x41, 0x41, 0x40, 0xde, 0x5d, 0xae,
                0x22, 0x23, 0xb0, 0x03, 0x61, 0xa3, 0x96, 0x17, 0x7a, 0x9c, 0xb4, 0x10, 0xff, 0x61,
                0xf2, 0x00, 0x15, 0xad,
            ])
        );
    }

    #[test]
    fn missing_glyphs_are_strict_fixture_errors() {
        let font = FontIdentity::fixture().expect("font");
        let error = fixture_run(TextRole::AxisLabel, "é", &font, (0.0, 0.0))
            .expect_err("fixture has no captured non-ASCII glyph");
        assert_eq!(error.kind(), SceneErrorKind::UnsupportedCapability);
    }

    #[test]
    fn two_consumers_read_the_same_retained_result_without_remeasurement() {
        let layout = PlotLayout::fixture().expect("layout");
        fn screen_consumer(layout: &PlotLayout) -> ([u8; 32], usize) {
            (layout.layout_digest(), layout.runs().len())
        }
        fn export_consumer(layout: &PlotLayout) -> ([u8; 32], usize) {
            (layout.layout_digest(), layout.runs().len())
        }
        assert_eq!(screen_consumer(&layout), export_consumer(&layout));
    }
}

/// Focused read-path tests for legend hit-testing.
///
/// Every case reads retained geometry only: no scene mutation, no visibility
/// mutation, no drag, and no remeasurement. The stale-generation case pins
/// the fail-closed gate the cursor and sink paths share.
#[cfg(test)]
mod legend_hit_tests {
    use super::*;

    fn fixture() -> PlotLayout {
        PlotLayout::fixture().expect("fixture layout")
    }

    fn two_entry_layout() -> PlotLayout {
        let font = FontIdentity::fixture().expect("font");
        let runs = vec![
            fixture_run(TextRole::AxisTitle, "title", &font, (0.0, 0.0)).expect("title run"),
            fixture_run(TextRole::LegendEntry, "aa", &font, (0.0, 0.0)).expect("first entry"),
            fixture_run(TextRole::LegendEntry, "bb", &font, (100.0, 100.0)).expect("second entry"),
        ];
        PlotLayout::from_runs(runs, 0, 0).expect("two-entry layout")
    }

    #[test]
    fn fixture_entry_box_unions_the_retained_glyph_cells() {
        let layout = fixture();
        let entries = layout.legend_entry_geometry().expect("entry boxes");
        assert_eq!(entries.len(), 1);
        let entry = entries[0];
        assert_eq!(entry.entry(), 0);
        // "series-0" carries eight glyphs opening at (72, 64); each stored
        // origin anchors one 5x7 fixture cell.
        assert_eq!(entry.x_min(), 72.0);
        assert_eq!(entry.y_min(), 64.0);
        assert_eq!(entry.x_max(), 72.0 + 7.0 * 8.0 + LEGEND_GLYPH_CELL_WIDTH);
        assert_eq!(entry.y_max(), 64.0 + LEGEND_GLYPH_CELL_HEIGHT);
        assert_eq!(layout.runs()[5].source(), "series-0");
    }

    #[test]
    fn point_inside_and_on_edges_hits_while_outside_misses() {
        let layout = fixture();
        let hit = layout
            .hit_legend_entry(100.0, 67.5, None, 0, 0)
            .expect("inside hit")
            .expect("entry below the point");
        assert_eq!(hit.entry(), 0);
        assert!(!hit.hidden());
        for (x, y) in [
            (72.0, 64.0),
            (133.0, 71.0),
            (72.0, 71.0),
            (133.0, 64.0),
            (74.5, 67.0),
        ] {
            assert!(
                layout
                    .hit_legend_entry(x, y, None, 0, 0)
                    .expect("edge query")
                    .is_some(),
                "edge point ({x}, {y}) must hit"
            );
        }
        for (x, y) in [
            (71.999, 67.5),
            (133.001, 67.5),
            (100.0, 63.999),
            (100.0, 71.001),
            (0.0, 0.0),
            (200.0, 200.0),
        ] {
            assert!(
                layout
                    .hit_legend_entry(x, y, None, 0, 0)
                    .expect("outside query")
                    .is_none(),
                "outside point ({x}, {y}) must miss"
            );
        }
    }

    #[test]
    fn hidden_entries_keep_geometry_and_stay_distinguishable() {
        let layout = fixture();
        let visible = layout
            .hit_legend_entry(100.0, 67.5, Some(&[false]), 0, 0)
            .expect("visible query")
            .expect("entry below the point");
        assert_eq!(visible.entry(), 0);
        assert!(!visible.hidden());
        let hidden = layout
            .hit_legend_entry(100.0, 67.5, Some(&[true]), 0, 0)
            .expect("hidden query")
            .expect("hidden entry keeps its box");
        assert_eq!(hidden.entry(), 0);
        assert!(hidden.hidden());
        // Geometry is identical either way: only the flag distinguishes.
        assert_eq!(
            layout.legend_entry_geometry().expect("boxes"),
            layout.legend_entry_geometry().expect("boxes")
        );
    }

    #[test]
    fn two_entries_resolve_independently_and_first_wins_overlap() {
        let layout = two_entry_layout();
        let entries = layout.legend_entry_geometry().expect("entry boxes");
        assert_eq!(entries.len(), 2);
        assert_eq!((entries[0].x_min(), entries[0].y_min()), (0.0, 0.0));
        assert_eq!((entries[1].x_min(), entries[1].y_min()), (100.0, 100.0));
        let first = layout
            .hit_legend_entry(2.0, 3.0, None, 0, 0)
            .expect("first query")
            .expect("first entry");
        assert_eq!(first.entry(), 0);
        let second = layout
            .hit_legend_entry(102.0, 103.0, None, 0, 0)
            .expect("second query")
            .expect("second entry");
        assert_eq!(second.entry(), 1);
        assert!(
            layout
                .hit_legend_entry(50.0, 50.0, None, 0, 0)
                .expect("gap query")
                .is_none()
        );

        let font = FontIdentity::fixture().expect("font");
        let overlapping = PlotLayout::from_runs(
            vec![
                fixture_run(TextRole::LegendEntry, "aa", &font, (0.0, 0.0)).expect("run"),
                fixture_run(TextRole::LegendEntry, "aa", &font, (0.0, 0.0)).expect("run"),
            ],
            0,
            0,
        )
        .expect("overlapping layout");
        let hit = overlapping
            .hit_legend_entry(2.0, 3.0, None, 0, 0)
            .expect("overlap query")
            .expect("overlap resolves");
        assert_eq!(hit.entry(), 0);
    }

    #[test]
    fn non_finite_queries_misaligned_visibility_and_stale_layouts_fail() {
        let layout = fixture();
        let error = layout
            .hit_legend_entry(f64::NAN, 67.5, None, 0, 0)
            .expect_err("non-finite query");
        assert_eq!(error.kind(), SceneErrorKind::InvalidInput);
        let error = layout
            .hit_legend_entry(100.0, 67.5, Some(&[]), 0, 0)
            .expect_err("misaligned visibility view");
        assert_eq!(error.kind(), SceneErrorKind::InvalidInput);
        let error = layout
            .hit_legend_entry(100.0, 67.5, Some(&[false, true]), 0, 0)
            .expect_err("overlong visibility view");
        assert_eq!(error.kind(), SceneErrorKind::InvalidInput);

        let moved = layout.with_layout_revision(1);
        let error = moved
            .hit_legend_entry(100.0, 67.5, None, 0, 0)
            .expect_err("stale carrier");
        assert_eq!(error.kind(), SceneErrorKind::Internal);
        let error = layout
            .hit_legend_entry(100.0, 67.5, None, 0, 1)
            .expect_err("stale generation pair");
        assert_eq!(error.kind(), SceneErrorKind::Internal);
        assert!(
            moved
                .hit_legend_entry(100.0, 67.5, None, 0, 1)
                .expect("current generation pair")
                .is_some()
        );
    }
}
