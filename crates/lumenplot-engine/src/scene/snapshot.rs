use std::sync::Arc;

use crate::data::Topology;
use crate::error::{SceneError, SceneErrorKind};
use crate::text::{AnnotationKind, AnnotationSpace, PlotLayout};

use super::revision::SceneRevision;
use super::state::{AxisScale, AxisScales, SceneState, Viewport};

#[derive(Clone, Debug)]
pub(crate) struct SceneSnapshot {
    pub(crate) state: Arc<SceneState>,
}

impl SceneSnapshot {
    pub(crate) fn new(state: Arc<SceneState>) -> Self {
        Self { state }
    }

    pub(crate) fn revision(&self) -> SceneRevision {
        self.state.revision()
    }

    pub(crate) fn canonical_view(&self) -> Viewport {
        self.state.canonical_view()
    }

    pub(crate) fn viewport(&self) -> Viewport {
        self.state.viewport()
    }

    pub(crate) fn axis_scales(&self) -> AxisScales {
        self.state.scales()
    }

    pub(crate) fn font_revision(&self) -> u64 {
        self.state.font_revision().0
    }

    pub(crate) fn layout_revision(&self) -> u64 {
        self.state.layout_revision().0
    }

    pub(crate) fn plot_layout(&self) -> Arc<PlotLayout> {
        self.state.plot_layout().clone()
    }

    /// Builds a read-only accessibility projection of this snapshot.
    ///
    /// The tree mirrors the accepted API-0004 content (plot, axes, series,
    /// legend, annotations, controls, current view, keyboard-operable
    /// actions) without retaining new state, mutating the scene, or touching
    /// any platform bridge. Transient focus marks at most one node; an
    /// unknown key simply leaves every node unmarked. Detail strings are
    /// human-readable and carry no stability promise.
    pub(crate) fn project_a11y(&self, ui: A11yUiState) -> Result<A11yTree, SceneError> {
        let revision = self.revision();
        let viewport = self.viewport();
        let canonical = self.canonical_view();
        let scales = self.axis_scales();
        let series: Vec<(u64, Topology, u64)> = {
            let mut items = Vec::new();
            items
                .try_reserve(self.state.series_map().len())
                .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
            for (id, storage) in self.state.series_map() {
                items.push((id.0, storage.topology(), storage.source_len()));
            }
            items
        };
        let annotations: Vec<(u64, AnnotationKind, AnnotationSpace)> = {
            let mut items = Vec::new();
            items
                .try_reserve(self.state.annotations_map().len())
                .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
            for stored in self.state.annotations_map().values() {
                items.push((stored.id(), stored.kind(), stored.space()));
            }
            items
        };
        A11yTree::build(
            revision,
            viewport,
            canonical,
            scales,
            &series,
            &annotations,
            ui,
        )
    }
}

// M5-F1 private snapshot-derived accessibility projection.
//
// T1 direction from the accepted M5-P4 spike: a read-only tree derived from
// one immutable snapshot plus transient focus observations at the
// viewer/runtime edge. Zero new retained state, zero scene mutation, zero
// platform types, zero new dependencies. Every type here is `pub(crate)` by
// intent: the exact node and field names are a proposal carried in the PR
// description, not a frozen public contract. No traceability flip, no focus
// rendering, no bridge wiring in this slice.

/// Transient focus target mirrored for the projection without a runtime edge.
///
/// The variants intentionally mirror the runtime router focus set so the
/// viewer edge can pass focus observations as plain data. Hover, selection,
/// and cursor observations stay out of this slice; routing currently reads
/// only focus and the tree marks only focus.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) enum A11yFocusTarget {
    Plot,
    Legend,
    LegendEntry(u64),
    Series(u64),
    Annotation(u64),
}

/// Transient UI observations consumed by the projection.
///
/// Only focus is read. The struct exists so later hover/selection coverage
/// has a named home without changing the builder signature.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub(crate) struct A11yUiState {
    focus: Option<A11yFocusTarget>,
}

impl A11yUiState {
    pub(crate) const fn new() -> Self {
        Self { focus: None }
    }

    pub(crate) const fn with_focus(focus: Option<A11yFocusTarget>) -> Self {
        Self { focus }
    }

    pub(crate) const fn focus(self) -> Option<A11yFocusTarget> {
        self.focus
    }
}

/// One node role in the private projection.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) enum A11yNodeKind {
    Plot,
    View,
    Axes,
    Series,
    Legend,
    LegendEntry,
    Annotation,
    Controls,
    Action,
}

impl A11yNodeKind {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Plot => "plot",
            Self::View => "view",
            Self::Axes => "axes",
            Self::Series => "series",
            Self::Legend => "legend",
            Self::LegendEntry => "legend-entry",
            Self::Annotation => "annotation",
            Self::Controls => "controls",
            Self::Action => "action",
        }
    }
}

/// One keyboard-operable action described by the tree.
///
/// The set mirrors the accepted keyboard matrix (arrows, PgUp/PgDn, Home,
/// Tab/Shift-Tab, Escape, G/C/E/V/L/R/A/Enter/Space/Delete). Labels and key
/// hints are human-readable and carry no stability promise.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) enum A11yActionKind {
    Navigate,
    History,
    Home,
    MoveFocus,
    Cancel,
    ToggleGrid,
    ToggleCursor,
    Export,
    ToggleSeriesVisibility,
    LegendToggle,
    LegendRestore,
    AnnotationCreate,
    AnnotationEdit,
    AnnotationDelete,
}

impl A11yActionKind {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Navigate => "navigate",
            Self::History => "history",
            Self::Home => "home",
            Self::MoveFocus => "move-focus",
            Self::Cancel => "cancel",
            Self::ToggleGrid => "toggle-grid",
            Self::ToggleCursor => "toggle-cursor",
            Self::Export => "export",
            Self::ToggleSeriesVisibility => "toggle-series-visibility",
            Self::LegendToggle => "legend-toggle",
            Self::LegendRestore => "legend-restore",
            Self::AnnotationCreate => "annotation-create",
            Self::AnnotationEdit => "annotation-edit",
            Self::AnnotationDelete => "annotation-delete",
        }
    }

    const fn key_hint(self) -> &'static str {
        match self {
            Self::Navigate => "arrows",
            Self::History => "PgUp/PgDn",
            Self::Home => "Home",
            Self::MoveFocus => "Tab",
            Self::Cancel => "Escape",
            Self::ToggleGrid => "G",
            Self::ToggleCursor => "C",
            Self::Export => "E",
            Self::ToggleSeriesVisibility => "V",
            Self::LegendToggle => "L",
            Self::LegendRestore => "R",
            Self::AnnotationCreate => "A",
            Self::AnnotationEdit => "Enter",
            Self::AnnotationDelete => "Delete",
        }
    }
}

/// One keyboard-operable action record carried by an action node.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) struct A11yAction {
    kind: A11yActionKind,
}

impl A11yAction {
    pub(crate) const fn new(kind: A11yActionKind) -> Self {
        Self { kind }
    }

    pub(crate) const fn kind(self) -> A11yActionKind {
        self.kind
    }

    pub(crate) const fn token(self) -> &'static str {
        self.kind.as_str()
    }

    pub(crate) const fn key_hint(self) -> &'static str {
        self.kind.key_hint()
    }
}

/// One node in the private projection.
#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct A11yNode {
    kind: A11yNodeKind,
    label: String,
    key: Option<u64>,
    detail: String,
    focused: bool,
    action: Option<A11yAction>,
    children: Vec<A11yNode>,
}

impl A11yNode {
    fn leaf(
        kind: A11yNodeKind,
        label: String,
        key: Option<u64>,
        detail: String,
        focused: bool,
        action: Option<A11yAction>,
    ) -> Self {
        Self {
            kind,
            label,
            key,
            detail,
            focused,
            action,
            children: Vec::new(),
        }
    }

    fn branch(
        kind: A11yNodeKind,
        label: String,
        detail: String,
        focused: bool,
        children: Vec<A11yNode>,
    ) -> Self {
        Self {
            kind,
            label,
            key: None,
            detail,
            focused,
            action: None,
            children,
        }
    }

    pub(crate) fn kind_ref(&self) -> A11yNodeKind {
        self.kind
    }

    pub(crate) fn kind_copy(&self) -> A11yNodeKind {
        self.kind
    }

    pub(crate) fn label(&self) -> &str {
        &self.label
    }

    pub(crate) fn key(&self) -> Option<u64> {
        self.key
    }

    pub(crate) fn detail(&self) -> &str {
        &self.detail
    }

    pub(crate) fn focused(&self) -> bool {
        self.focused
    }

    pub(crate) fn action(&self) -> Option<A11yAction> {
        self.action
    }

    pub(crate) fn children(&self) -> &[A11yNode] {
        &self.children
    }
}

/// A read-only projection of one snapshot revision.
#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct A11yTree {
    revision: SceneRevision,
    root: A11yNode,
}

impl A11yTree {
    const ACTIONS: [A11yActionKind; 14] = [
        A11yActionKind::Navigate,
        A11yActionKind::History,
        A11yActionKind::Home,
        A11yActionKind::MoveFocus,
        A11yActionKind::Cancel,
        A11yActionKind::ToggleGrid,
        A11yActionKind::ToggleCursor,
        A11yActionKind::Export,
        A11yActionKind::ToggleSeriesVisibility,
        A11yActionKind::LegendToggle,
        A11yActionKind::LegendRestore,
        A11yActionKind::AnnotationCreate,
        A11yActionKind::AnnotationEdit,
        A11yActionKind::AnnotationDelete,
    ];

    #[allow(clippy::too_many_arguments)]
    fn build(
        revision: SceneRevision,
        viewport: Viewport,
        canonical: Viewport,
        scales: AxisScales,
        series: &[(u64, Topology, u64)],
        annotations: &[(u64, AnnotationKind, AnnotationSpace)],
        ui: A11yUiState,
    ) -> Result<Self, SceneError> {
        let focus = ui.focus();
        let view = Self::view_node(viewport, canonical);
        let axes = Self::axes_node(scales, viewport);
        let mut series_nodes = Vec::new();
        series_nodes
            .try_reserve(series.len())
            .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
        for (id, topology, source_len) in series {
            let focused = focus == Some(A11yFocusTarget::Series(*id));
            series_nodes.push(A11yNode::leaf(
                A11yNodeKind::Series,
                format!("series-{id}"),
                Some(*id),
                format!(
                    "topology {} source-len {source_len}",
                    topology_token(*topology)
                ),
                focused,
                None,
            ));
        }
        let legend = Self::legend_node(series, focus)?;
        let mut annotation_nodes = Vec::new();
        annotation_nodes
            .try_reserve(annotations.len())
            .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
        for (id, kind, space) in annotations {
            let focused = focus == Some(A11yFocusTarget::Annotation(*id));
            annotation_nodes.push(A11yNode::leaf(
                A11yNodeKind::Annotation,
                format!("annotation-{id}"),
                Some(*id),
                format!(
                    "kind {} space {}",
                    annotation_kind_token(*kind),
                    annotation_space_token(*space)
                ),
                focused,
                None,
            ));
        }
        let controls = Self::controls_node();
        let mut root_children = Vec::new();
        root_children
            .try_reserve(
                3_usize
                    .checked_add(series_nodes.len())
                    .and_then(|count| count.checked_add(1))
                    .and_then(|count| count.checked_add(annotation_nodes.len()))
                    .and_then(|count| count.checked_add(1))
                    .ok_or_else(|| SceneError::new(SceneErrorKind::CapacityExceeded))?,
            )
            .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
        root_children.push(view);
        root_children.push(axes);
        root_children.extend(series_nodes);
        root_children.push(legend);
        root_children.extend(annotation_nodes);
        root_children.push(controls);
        let root = A11yNode {
            kind: A11yNodeKind::Plot,
            label: "plot".to_owned(),
            key: None,
            detail: format!("revision {}", revision.0),
            focused: focus == Some(A11yFocusTarget::Plot),
            action: None,
            children: root_children,
        };
        Ok(Self { revision, root })
    }

    fn view_node(viewport: Viewport, canonical: Viewport) -> A11yNode {
        A11yNode::leaf(
            A11yNodeKind::View,
            "view".to_owned(),
            None,
            format!(
                "viewport [{}, {}, {}, {}] canonical [{}, {}, {}, {}]",
                viewport.x().min(),
                viewport.x().max(),
                viewport.y().min(),
                viewport.y().max(),
                canonical.x().min(),
                canonical.x().max(),
                canonical.y().min(),
                canonical.y().max(),
            ),
            false,
            None,
        )
    }

    fn axes_node(scales: AxisScales, viewport: Viewport) -> A11yNode {
        A11yNode::leaf(
            A11yNodeKind::Axes,
            "axes".to_owned(),
            None,
            format!(
                "x {} [{}, {}] y {} [{}, {}]",
                scale_token(scales.x()),
                viewport.x().min(),
                viewport.x().max(),
                scale_token(scales.y()),
                viewport.y().min(),
                viewport.y().max(),
            ),
            false,
            None,
        )
    }

    fn legend_node(
        series: &[(u64, Topology, u64)],
        focus: Option<A11yFocusTarget>,
    ) -> Result<A11yNode, SceneError> {
        let mut entries = Vec::new();
        entries
            .try_reserve(series.len())
            .map_err(|_| SceneError::new(SceneErrorKind::AllocationFailed))?;
        for (id, _, _) in series {
            entries.push(A11yNode::leaf(
                A11yNodeKind::LegendEntry,
                format!("legend-entry-{id}"),
                Some(*id),
                format!("series {id}"),
                focus == Some(A11yFocusTarget::LegendEntry(*id)),
                None,
            ));
        }
        Ok(A11yNode::branch(
            A11yNodeKind::Legend,
            "legend".to_owned(),
            format!("entries {}", entries.len()),
            focus == Some(A11yFocusTarget::Legend),
            entries,
        ))
    }

    fn controls_node() -> A11yNode {
        let mut actions = Vec::with_capacity(Self::ACTIONS.len());
        for kind in Self::ACTIONS {
            let action = A11yAction::new(kind);
            actions.push(A11yNode::leaf(
                A11yNodeKind::Action,
                format!("action-{}", kind.as_str()),
                None,
                format!("key {}", kind.key_hint()),
                false,
                Some(action),
            ));
        }
        A11yNode::branch(
            A11yNodeKind::Controls,
            "controls".to_owned(),
            format!("actions {}", actions.len()),
            false,
            actions,
        )
    }

    pub(crate) fn revision(&self) -> SceneRevision {
        self.revision
    }

    pub(crate) fn root(&self) -> &A11yNode {
        &self.root
    }

    /// Counts every node in the tree, including the root.
    pub(crate) fn node_count(&self) -> usize {
        fn count(node: &A11yNode) -> usize {
            let mut total = 1;
            for child in node.children() {
                total += count(child);
            }
            total
        }
        count(&self.root)
    }

    /// Collects the labels of every focused node in tree order.
    pub(crate) fn focused_labels(&self) -> Vec<&str> {
        fn visit<'a>(node: &'a A11yNode, out: &mut Vec<&'a str>) {
            if node.focused {
                out.push(node.label());
            }
            for child in node.children() {
                visit(child, out);
            }
        }
        let mut out = Vec::new();
        visit(&self.root, &mut out);
        out
    }

    /// Finds the first direct child of the root with the given kind.
    pub(crate) fn root_child(&self, kind: A11yNodeKind) -> Option<&A11yNode> {
        self.root
            .children()
            .iter()
            .find(|node| node.kind_ref() == kind)
    }
}

const fn topology_token(topology: Topology) -> &'static str {
    match topology {
        Topology::MonotonicX => "monotonic-x",
        Topology::ArbitraryXY => "arbitrary-xy",
    }
}

const fn scale_token(scale: AxisScale) -> &'static str {
    match scale {
        AxisScale::Linear => "linear",
        AxisScale::Log10 => "log10",
    }
}

const fn annotation_kind_token(kind: AnnotationKind) -> &'static str {
    match kind {
        AnnotationKind::Text => "text",
        AnnotationKind::Line => "line",
        AnnotationKind::Arrow => "arrow",
        AnnotationKind::Rectangle => "rectangle",
    }
}

const fn annotation_space_token(space: AnnotationSpace) -> &'static str {
    match space {
        AnnotationSpace::Data2D => "data-2d",
        AnnotationSpace::AxesLogical => "axes-logical",
        AnnotationSpace::FigureLogical => "figure-logical",
        AnnotationSpace::DisplayLogical => "display-logical",
    }
}

/// Why the platform tree bridge is unavailable.
///
/// This is a capability report, not an operation error and not a fallback
/// reason. Keyboard operation, visible focus, contrast-aware defaults, and
/// reduced-motion behavior stay fully available while the bridge is down.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) enum A11yBridgeReason {
    NoPlatformAdapter,
    AdapterInitFailed,
}

impl A11yBridgeReason {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::NoPlatformAdapter => "no-platform-adapter",
            Self::AdapterInitFailed => "adapter-init-failed",
        }
    }
}

/// Structured unavailable-bridge diagnostic inside the API-0002 envelope.
///
/// The machine contract reuses the existing `UnsupportedCapability` /
/// `capability` code and category; no new top-level error kind is
/// introduced. PDF tags and SVG title/desc output are separately labeled
/// and are never inferred from this interactive-tree report.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) struct A11yBridgeDiagnostic {
    reason: A11yBridgeReason,
    host: &'static str,
    revision: SceneRevision,
}

impl A11yBridgeDiagnostic {
    pub(crate) const CAPABILITY: &'static str = "accessibility-tree-bridge";
    pub(crate) const SCOPE: &'static str = "interactive-tree-only";

    pub(crate) const fn unavailable(
        reason: A11yBridgeReason,
        host: &'static str,
        revision: SceneRevision,
    ) -> Self {
        Self {
            reason,
            host,
            revision,
        }
    }

    /// Existing API-0002 machine code for the report; no new kind.
    pub(crate) const fn code(self) -> SceneErrorKind {
        SceneErrorKind::UnsupportedCapability
    }

    /// Stable API-0002 category token for the report.
    pub(crate) const fn category_token(self) -> &'static str {
        "capability"
    }

    pub(crate) const fn capability(self) -> &'static str {
        Self::CAPABILITY
    }

    pub(crate) const fn reason(self) -> A11yBridgeReason {
        self.reason
    }

    pub(crate) const fn reason_token(self) -> &'static str {
        self.reason.as_str()
    }

    pub(crate) const fn host(self) -> &'static str {
        self.host
    }

    pub(crate) const fn revision(self) -> SceneRevision {
        self.revision
    }

    pub(crate) const fn scope(self) -> &'static str {
        Self::SCOPE
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::data::SeriesInput;
    use crate::scene::state::{AxisRange, AxisScales, PlotScene, Viewport};
    use crate::text::{AnnotationShape, AnnotationSpace};

    fn assert_send_sync<T: Send + Sync>() {}

    #[test]
    fn snapshot_is_send_and_sync() {
        assert_send_sync::<SceneSnapshot>();
    }

    fn scene() -> PlotScene {
        PlotScene::new(
            Viewport::from_bounds(0.0, 10.0, 0.0, 10.0).expect("view"),
            AxisScales::new(AxisScale::Linear, AxisScale::Linear),
        )
        .expect("scene")
    }

    fn series_data(values: &[f64]) -> SeriesInput {
        SeriesInput::from_owned_xy(
            Topology::MonotonicX,
            (0..values.len()).map(|value| value as f64).collect(),
            values.to_vec(),
            None,
        )
        .expect("data")
    }

    fn kinds(root: &A11yNode) -> Vec<A11yNodeKind> {
        root.children().iter().map(A11yNode::kind_ref).collect()
    }

    #[test]
    fn empty_scene_projects_plot_axes_view_legend_controls() {
        let plot = scene();
        let snapshot = plot.snapshot();
        let tree = snapshot
            .project_a11y(A11yUiState::new())
            .expect("projection");
        assert_eq!(tree.revision(), snapshot.revision());
        assert_eq!(tree.root().kind_ref(), A11yNodeKind::Plot);
        assert!(!tree.root().focused());
        let child_kinds = kinds(tree.root());
        assert!(child_kinds.contains(&A11yNodeKind::View));
        assert!(child_kinds.contains(&A11yNodeKind::Axes));
        assert!(child_kinds.contains(&A11yNodeKind::Legend));
        assert!(child_kinds.contains(&A11yNodeKind::Controls));
        assert!(tree.focused_labels().is_empty());
        let legend = tree.root_child(A11yNodeKind::Legend).expect("legend child");
        assert!(legend.children().is_empty());
        let controls = tree
            .root_child(A11yNodeKind::Controls)
            .expect("controls child");
        assert_eq!(controls.children().len(), 14);
        assert!(
            controls
                .children()
                .iter()
                .all(|node| node.kind_ref() == A11yNodeKind::Action)
        );
        assert!(
            controls
                .children()
                .iter()
                .any(|node| node.action() == Some(A11yAction::new(A11yActionKind::MoveFocus)))
        );
        // View and axes carry the snapshot context without mutating it.
        let view = tree.root_child(A11yNodeKind::View).expect("view child");
        assert!(view.detail().contains("viewport"));
        let axes = tree.root_child(A11yNodeKind::Axes).expect("axes child");
        assert!(axes.detail().contains("linear"));
        assert_eq!(plot.revision(), snapshot.revision());
    }

    #[test]
    fn series_and_annotations_appear_with_stable_keys() {
        let mut plot = scene();
        let (first, second) = {
            let mut transaction = plot.transaction();
            let first = transaction
                .add_series(series_data(&[1.0, 2.0]))
                .expect("add");
            let second = transaction
                .add_series(series_data(&[3.0, 4.0, 5.0]))
                .expect("add");
            transaction
                .add_annotation(
                    AnnotationSpace::Data2D,
                    AnnotationShape::Text {
                        x: 1.0,
                        y: 1.0,
                        half_width: 0.5,
                        half_height: 0.25,
                    },
                    1,
                    1,
                    0,
                )
                .expect("annotation");
            transaction
                .add_annotation(
                    AnnotationSpace::AxesLogical,
                    AnnotationShape::Rectangle {
                        x_min: 0.0,
                        y_min: 0.0,
                        x_max: 2.0,
                        y_max: 1.0,
                    },
                    1,
                    1,
                    1,
                )
                .expect("annotation");
            transaction.commit().expect("commit");
            (first.0, second.0)
        };
        let snapshot = plot.snapshot();
        let tree = snapshot
            .project_a11y(A11yUiState::new())
            .expect("projection");
        assert_eq!(tree.revision(), snapshot.revision());
        let series_keys: Vec<u64> = tree
            .root()
            .children()
            .iter()
            .filter(|node| node.kind_ref() == A11yNodeKind::Series)
            .filter_map(|node| node.key())
            .collect();
        assert_eq!(series_keys, vec![first, second]);
        let legend = tree.root_child(A11yNodeKind::Legend).expect("legend child");
        let entry_keys: Vec<u64> = legend
            .children()
            .iter()
            .filter_map(|node| node.key())
            .collect();
        assert_eq!(entry_keys, vec![first, second]);
        let annotation_nodes: Vec<&A11yNode> = tree
            .root()
            .children()
            .iter()
            .filter(|node| node.kind_ref() == A11yNodeKind::Annotation)
            .collect();
        assert_eq!(annotation_nodes.len(), 2);
        assert!(annotation_nodes[0].detail().contains("text"));
        assert!(annotation_nodes[0].detail().contains("data-2d"));
        assert!(annotation_nodes[1].detail().contains("rectangle"));
        assert!(annotation_nodes[1].detail().contains("axes-logical"));
        // No focus requested, so nothing is marked.
        assert!(tree.focused_labels().is_empty());
        // Deterministic order: BTreeMap key order is preserved.
        assert!(series_keys.windows(2).all(|pair| pair[0] < pair[1]));
    }

    #[test]
    fn focus_marks_exactly_one_node() {
        let mut plot = scene();
        let series_id = {
            let mut transaction = plot.transaction();
            let id = transaction
                .add_series(series_data(&[1.0, 2.0]))
                .expect("add");
            transaction.commit().expect("commit");
            id.0
        };
        let annotation_id = {
            let mut transaction = plot.transaction();
            let id = transaction
                .add_annotation(
                    AnnotationSpace::DisplayLogical,
                    AnnotationShape::Line {
                        x1: 0.0,
                        y1: 0.0,
                        x2: 1.0,
                        y2: 1.0,
                    },
                    1,
                    1,
                    0,
                )
                .expect("annotation");
            transaction.commit().expect("commit");
            id.0
        };
        let snapshot = plot.snapshot();
        for focus in [
            Some(A11yFocusTarget::Plot),
            Some(A11yFocusTarget::Legend),
            Some(A11yFocusTarget::LegendEntry(series_id)),
            Some(A11yFocusTarget::Series(series_id)),
            Some(A11yFocusTarget::Annotation(annotation_id)),
            None,
        ] {
            let tree = snapshot
                .project_a11y(A11yUiState::with_focus(focus))
                .expect("projection");
            let focused = tree.focused_labels();
            match focus {
                None => assert!(focused.is_empty(), "no focus marks nothing"),
                Some(A11yFocusTarget::Plot) => assert_eq!(focused, vec!["plot"]),
                Some(A11yFocusTarget::Legend) => assert_eq!(focused, vec!["legend"]),
                Some(A11yFocusTarget::LegendEntry(id)) => {
                    let expected = format!("legend-entry-{id}");
                    assert_eq!(focused, vec![expected.as_str()]);
                }
                Some(A11yFocusTarget::Series(id)) => {
                    let expected = format!("series-{id}");
                    assert_eq!(focused, vec![expected.as_str()]);
                }
                Some(A11yFocusTarget::Annotation(id)) => {
                    let expected = format!("annotation-{id}");
                    assert_eq!(focused, vec![expected.as_str()]);
                }
            }
        }
        // Unknown keys never fail the projection; they mark nothing.
        let tree = snapshot
            .project_a11y(A11yUiState::with_focus(Some(A11yFocusTarget::Series(
                u64::MAX,
            ))))
            .expect("projection");
        assert!(tree.focused_labels().is_empty());
    }

    #[test]
    fn projection_is_read_only_and_revision_pinned() {
        let mut plot = scene();
        let before = plot.snapshot();
        let before_revision = before.revision();
        let before_tree = before.project_a11y(A11yUiState::new()).expect("projection");
        assert_eq!(before_tree.revision(), before_revision);
        let before_count = before_tree.node_count();
        {
            let mut transaction = plot.transaction();
            transaction
                .add_series(series_data(&[1.0, 2.0]))
                .expect("add");
            transaction.commit().expect("commit");
        }
        // The projection itself never advances the scene.
        assert_eq!(plot.revision().0, before_revision.0 + 1);
        // A stale snapshot still projects its own pinned revision.
        let stale_tree = before.project_a11y(A11yUiState::new()).expect("projection");
        assert_eq!(stale_tree.revision(), before_revision);
        assert_eq!(stale_tree.node_count(), before_count);
        let fresh_tree = plot
            .snapshot()
            .project_a11y(A11yUiState::new())
            .expect("projection");
        assert_eq!(fresh_tree.revision(), plot.revision());
        assert!(fresh_tree.node_count() > before_count);
    }

    #[test]
    fn bridge_diagnostic_stays_inside_unsupported_capability_envelope() {
        let plot = scene();
        let revision = plot.snapshot().revision();
        for reason in [
            A11yBridgeReason::NoPlatformAdapter,
            A11yBridgeReason::AdapterInitFailed,
        ] {
            let diagnostic = A11yBridgeDiagnostic::unavailable(reason, "headless", revision);
            assert_eq!(diagnostic.code(), SceneErrorKind::UnsupportedCapability);
            assert_eq!(diagnostic.category_token(), "capability");
            assert_eq!(diagnostic.capability(), "accessibility-tree-bridge");
            assert_eq!(diagnostic.host(), "headless");
            assert_eq!(diagnostic.revision(), revision);
            assert_eq!(diagnostic.scope(), "interactive-tree-only");
            assert!(!diagnostic.reason_token().is_empty());
        }
        let missing = A11yBridgeDiagnostic::unavailable(
            A11yBridgeReason::NoPlatformAdapter,
            "headless",
            revision,
        );
        let failed = A11yBridgeDiagnostic::unavailable(
            A11yBridgeReason::AdapterInitFailed,
            "headless",
            revision,
        );
        assert_ne!(missing.reason_token(), failed.reason_token());
        assert_eq!(missing.reason_token(), "no-platform-adapter");
        assert_eq!(failed.reason_token(), "adapter-init-failed");
        // The diagnostic never blocks the tree: keyboard and focus content
        // stays available while the bridge is down.
        let tree = plot
            .snapshot()
            .project_a11y(A11yUiState::with_focus(Some(A11yFocusTarget::Plot)))
            .expect("projection");
        assert_eq!(tree.focused_labels(), vec!["plot"]);
        assert!(tree.root_child(A11yNodeKind::Controls).is_some());
    }

    #[test]
    fn node_kind_tokens_cover_required_content() {
        assert_eq!(A11yNodeKind::Plot.as_str(), "plot");
        assert_eq!(A11yNodeKind::Axes.as_str(), "axes");
        assert_eq!(A11yNodeKind::Series.as_str(), "series");
        assert_eq!(A11yNodeKind::Legend.as_str(), "legend");
        assert_eq!(A11yNodeKind::Annotation.as_str(), "annotation");
        assert_eq!(A11yNodeKind::Action.as_str(), "action");
    }

    #[test]
    fn unused_import_guard() {
        // Keeps the AxisRange import path referenced by sibling transaction
        // tests from drifting while this module owns viewport bounds.
        let range = AxisRange::new(0.0, 1.0).expect("range");
        assert_eq!((range.min(), range.max()), (0.0, 1.0));
    }
}
