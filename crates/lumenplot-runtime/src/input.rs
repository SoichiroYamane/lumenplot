//! Backend-neutral semantic input routing for the native runtime.
//!
//! The facade does not expose this module. Its inputs are already normalized to
//! gesture-level events: this module intentionally does not infer drags,
//! clicks, double clicks, or trackpad gestures from a time-ordered stream.
//! Such inference would require host/window policy and would make a headless
//! route ambiguous. A host must supply an explicit [`PointerPhase`] instead.
//!
//! The returned [`SemanticAction`] is an operation description, not a scene
//! mutation. In particular, hover, cursor, selection highlight, context, and
//! focus actions are transient UI state and must not be copied into ordinary
//! Plot State or exports. The router contains no animation, time, window, or
//! GPU assumptions. Reduced-motion preference is accepted by
//! [`route_with_motion`] only to make the semantic-preservation boundary
//! explicit; it cannot change the returned action.

#![allow(dead_code)]

use std::fmt;

/// A pointer button understood by the semantic map.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) enum PointerButton {
    /// The primary button used for direct manipulation and selection.
    Left,
    /// The secondary button used for transient context actions.
    Right,
    /// An auxiliary button. It is explicit so routing can reject it.
    Middle,
    /// A host-reported button outside the accepted v1 matrix.
    Other(u16),
}

/// One modifier key that may be present on an input event.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) enum ModifierKey {
    /// Shift modifier; the only pointer modifier with a v1 gesture meaning.
    Shift,
    /// Control modifier.
    Control,
    /// Alt/Option modifier.
    Alt,
    /// Super/Command/Windows modifier.
    Super,
}

/// A compact set of modifier keys.
///
/// Only the four declared [`ModifierKey`] values can be represented. The
/// checked [`Self::from_bits`] constructor prevents an unknown host bit from
/// being silently treated as no modifier.
#[derive(Clone, Copy, Debug, Default, Eq, Hash, PartialEq)]
pub struct ModifierKeys(u8);

impl ModifierKeys {
    /// No modifiers are held.
    pub const NONE: Self = Self(0);
    /// Shift is held.
    pub const SHIFT: Self = Self(1 << 0);
    /// Control is held.
    pub const CONTROL: Self = Self(1 << 1);
    /// Alt/Option is held.
    pub const ALT: Self = Self(1 << 2);
    /// Super/Command/Windows is held.
    pub const SUPER: Self = Self(1 << 3);

    const KNOWN_BITS: u8 = Self::SHIFT.0 | Self::CONTROL.0 | Self::ALT.0 | Self::SUPER.0;

    /// Returns an empty modifier set.
    pub const fn empty() -> Self {
        Self::NONE
    }

    /// Creates a set from a single modifier key.
    pub(crate) const fn from_key(key: ModifierKey) -> Self {
        match key {
            ModifierKey::Shift => Self::SHIFT,
            ModifierKey::Control => Self::CONTROL,
            ModifierKey::Alt => Self::ALT,
            ModifierKey::Super => Self::SUPER,
        }
    }

    /// Creates a set from raw bits, rejecting unknown bits.
    pub const fn from_bits(bits: u8) -> Option<Self> {
        if bits & !Self::KNOWN_BITS == 0 {
            Some(Self(bits))
        } else {
            None
        }
    }

    /// Returns the checked bit representation.
    pub const fn bits(self) -> u8 {
        self.0
    }

    /// Returns whether a modifier is present.
    pub(crate) const fn contains(self, key: ModifierKey) -> bool {
        self.0 & Self::from_key(key).0 != 0
    }

    /// Returns whether no modifier is present.
    pub const fn is_empty(self) -> bool {
        self.0 == 0
    }

    /// Adds one modifier to this set.
    pub(crate) const fn with(self, key: ModifierKey) -> Self {
        Self(self.0 | Self::from_key(key).0)
    }

    /// Combines two checked modifier sets.
    pub const fn union(self, other: Self) -> Self {
        Self(self.0 | other.0)
    }
}

/// Compatibility spelling for code that calls the set `Modifiers`.
pub(crate) type Modifiers = ModifierKeys;

/// Axis scope attached to a pan, zoom, or box-zoom action.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum AxisRestriction {
    /// Both x and y dimensions are affected.
    Both,
    /// Only the x dimension is affected.
    X,
    /// Only the y dimension is affected.
    Y,
}

/// Compatibility spelling for consumers that call the value an axis constraint.
pub(crate) type AxisConstraint = AxisRestriction;

/// A normalized pointer gesture phase.
///
/// `Press`, `Move`, and `Release` are retained to make an incomplete or
/// unnormalized host event explicit. They are rejected by the router because
/// deciding whether they form a click or drag requires state and, for a double
/// click, host timing. Hosts should provide `Drag`, `Click`, or `DoubleClick`
/// once that policy has already been resolved.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) enum PointerPhase {
    /// A hover update; it changes only transient hover state.
    Hover,
    /// A completed or normalized drag update.
    Drag,
    /// A normalized single click.
    Click,
    /// A normalized double click; no timing is inferred here.
    DoubleClick,
    /// A wheel step or scroll update.
    Wheel,
    /// A trackpad scroll update.
    Trackpad,
    /// A host press phase without a resolved gesture.
    Press,
    /// A host move phase without a resolved gesture.
    Move,
    /// A host release phase without a resolved gesture.
    Release,
    /// Cancellation of an in-progress transient gesture.
    Cancel,
}

/// A semantic target under a pointer.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum PointerTarget {
    /// The plot background, with no series geometry under the pointer.
    PlotBackground,
    /// A selectable line/series identified by a runtime-local key.
    Series(u64),
    /// The x-axis region.
    XAxis,
    /// The y-axis region.
    YAxis,
    /// Legend geometry that is not a particular entry.
    Legend,
    /// A Legend entry identified by its series key.
    LegendEntry(u64),
    /// An annotation identified by a runtime-local key.
    Annotation(u64),
    /// A target the v1 semantic map does not understand.
    Other,
}

impl PointerTarget {
    fn gesture_axis(self) -> Result<AxisRestriction, InputRouteError> {
        match self {
            Self::PlotBackground | Self::Series(_) => Ok(AxisRestriction::Both),
            Self::XAxis => Ok(AxisRestriction::X),
            Self::YAxis => Ok(AxisRestriction::Y),
            Self::Legend | Self::LegendEntry(_) | Self::Annotation(_) | Self::Other => {
                Err(InputRouteError::new(
                    InputRouteErrorKind::UnsupportedPointerTarget,
                    "pointer drag or scroll has no plot-axis target",
                ))
            }
        }
    }

    fn is_context_target(self) -> bool {
        !matches!(self, Self::Other)
    }
}

/// A keyboard key after host key normalization.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum KeyboardKey {
    /// Left navigation key.
    ArrowLeft,
    /// Right navigation key.
    ArrowRight,
    /// Up navigation key.
    ArrowUp,
    /// Down navigation key.
    ArrowDown,
    /// Previous-history key.
    PageUp,
    /// Next-history key.
    PageDown,
    /// Canonical-view key.
    Home,
    /// Focus-next key.
    Tab,
    /// Activation key for focused controls.
    Enter,
    /// Alternate activation key for focused Legend entries.
    Space,
    /// Cancellation key.
    Escape,
    /// Delete key for a focused annotation.
    Delete,
    /// Annotation command key.
    A,
    /// Cursor command key.
    C,
    /// Export command key.
    E,
    /// Grid command key.
    G,
    /// Legend command key.
    L,
    /// Restore-visibility command key.
    R,
    /// Series-visibility command key.
    V,
    /// A normalized key outside the accepted matrix.
    Other(u32),
}

/// A pointer input supplied to the semantic router.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) struct PointerEvent {
    phase: PointerPhase,
    button: Option<PointerButton>,
    modifiers: ModifierKeys,
    target: PointerTarget,
}

impl PointerEvent {
    /// Constructs a pointer event. Gesture validity is checked by [`route`].
    pub(crate) const fn new(
        phase: PointerPhase,
        button: Option<PointerButton>,
        modifiers: ModifierKeys,
        target: PointerTarget,
    ) -> Self {
        Self {
            phase,
            button,
            modifiers,
            target,
        }
    }

    /// Returns the normalized phase.
    pub(crate) const fn phase(self) -> PointerPhase {
        self.phase
    }

    /// Returns the button, if this event reports one.
    pub(crate) const fn button(self) -> Option<PointerButton> {
        self.button
    }

    /// Returns the modifier set.
    pub(crate) const fn modifiers(self) -> ModifierKeys {
        self.modifiers
    }

    /// Returns the semantic target.
    pub(crate) const fn target(self) -> PointerTarget {
        self.target
    }
}

/// A keyboard input supplied to the semantic router.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct KeyboardEvent {
    key: KeyboardKey,
    modifiers: ModifierKeys,
}

impl KeyboardEvent {
    /// Constructs a normalized key-press event.
    pub const fn new(key: KeyboardKey, modifiers: ModifierKeys) -> Self {
        Self { key, modifiers }
    }

    /// Returns the normalized key.
    pub const fn key(self) -> KeyboardKey {
        self.key
    }

    /// Returns the modifier set.
    pub const fn modifiers(self) -> ModifierKeys {
        self.modifiers
    }
}

/// A focusable transient UI target.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum FocusTarget {
    /// The plot surface.
    Plot,
    /// The Legend as a whole.
    Legend,
    /// One Legend entry, identified by its series key.
    LegendEntry(u64),
    /// A series control, identified by its series key.
    Series(u64),
    /// One annotation, identified by a runtime-local key.
    Annotation(u64),
}

/// Transient UI observations used while routing an input.
///
/// This is deliberately not a scene or Plot State type. The runtime may
/// replace these observations between events; ordinary exports must omit all
/// of them. Routing currently reads only `focus`, while the other fields make
/// the ownership boundary explicit for hover/cursor/context consumers.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct TransientUiState {
    cursor: Option<PointerTarget>,
    hover: Option<PointerTarget>,
    context: Option<PointerTarget>,
    focus: Option<FocusTarget>,
}

impl TransientUiState {
    /// Creates an empty transient UI state.
    pub const fn new() -> Self {
        Self {
            cursor: None,
            hover: None,
            context: None,
            focus: None,
        }
    }

    /// Returns a state with the supplied focus target.
    pub const fn with_focus(focus: Option<FocusTarget>) -> Self {
        Self {
            cursor: None,
            hover: None,
            context: None,
            focus,
        }
    }

    /// Returns a copy with the supplied focus target.
    pub(crate) const fn with_focus_target(self, focus: Option<FocusTarget>) -> Self {
        Self { focus, ..self }
    }

    /// Returns a copy with the supplied cursor observation.
    pub(crate) const fn with_cursor(self, cursor: Option<PointerTarget>) -> Self {
        Self { cursor, ..self }
    }

    /// Returns a copy with the supplied hover observation.
    pub(crate) const fn with_hover(self, hover: Option<PointerTarget>) -> Self {
        Self { hover, ..self }
    }

    /// Returns a copy with the supplied context observation.
    pub(crate) const fn with_context(self, context: Option<PointerTarget>) -> Self {
        Self { context, ..self }
    }

    /// Returns the cursor observation.
    pub(crate) const fn cursor(self) -> Option<PointerTarget> {
        self.cursor
    }

    /// Returns the hover observation.
    pub(crate) const fn hover(self) -> Option<PointerTarget> {
        self.hover
    }

    /// Returns the context observation.
    pub(crate) const fn context(self) -> Option<PointerTarget> {
        self.context
    }

    /// Returns the focused target.
    pub const fn focus(self) -> Option<FocusTarget> {
        self.focus
    }
}

/// The two ways focus can move through the semantic control order.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum FocusDirection {
    /// Move to the next focusable target.
    Next,
    /// Move to the previous focusable target.
    Previous,
}

/// Direction for keyboard view navigation.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum NavigationDirection {
    /// Move toward the lower x range.
    Left,
    /// Move toward the higher x range.
    Right,
    /// Move toward the higher y range.
    Up,
    /// Move toward the lower y range.
    Down,
}

/// Direction for view-history traversal.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum HistoryDirection {
    /// Restore the prior view entry.
    Previous,
    /// Restore the next view entry.
    Next,
}

/// An operation on the formal publication Legend.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum LegendAction {
    /// Toggle one series' visibility while retaining Legend geometry.
    ToggleVisibility { series: u64 },
    /// Solo one series, retaining the prior visibility snapshot in UI state.
    Solo { series: u64 },
    /// Restore the visibility snapshot associated with one series' solo action.
    Restore { series: u64 },
}

/// An annotation operation. Annotation state itself belongs to Plot State;
/// focus and editing chrome around it do not.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum AnnotationAction {
    /// Begin creation of an annotation.
    Create,
    /// Begin editing an existing annotation.
    Edit { annotation: u64 },
    /// Delete an existing annotation.
    Delete { annotation: u64 },
}

/// A selectable target for a transient selection highlight.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum SelectionTarget {
    /// A line/series target.
    Series(u64),
    /// An annotation target.
    Annotation(u64),
}

/// The required anchor semantics for pointer zoom.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum ZoomAnchor {
    /// Preserve the scientific point under the pointer.
    Pointer,
}

/// Whether an action is transient UI, Plot State-affecting, or read-only.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) enum ActionStateScope {
    /// The action changes state that is eligible for ordinary export.
    PlotState,
    /// The action changes only transient UI state and is excluded from export.
    TransientUi,
    /// The action does not mutate either state class.
    ReadOnly,
}

/// A semantic operation produced by the input map.
///
/// No variant represents a permanent Pan, Zoom, or Box Zoom mode. Direct
/// pointer gestures select their operation from phase, button, modifiers, and
/// target; keyboard commands select the same semantic operation directly.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum SemanticAction {
    /// Pan the current viewport.
    Pan { axis: AxisRestriction },
    /// Zoom around the pointer, with optional axis restriction.
    Zoom {
        axis: AxisRestriction,
        anchor: ZoomAnchor,
    },
    /// Replace the current viewport with the selected box.
    BoxZoom { axis: AxisRestriction },
    /// Select a line or annotation as transient UI state.
    Select { target: SelectionTarget },
    /// Clear the transient selection highlight.
    ClearSelection,
    /// Restore the stored canonical view.
    Home,
    /// Open a transient context action for a target.
    Context { target: PointerTarget },
    /// Update transient hover state.
    Hover { target: PointerTarget },
    /// Move the current viewport using keyboard navigation.
    Navigate { direction: NavigationDirection },
    /// Traverse the transient view-history stack.
    History { direction: HistoryDirection },
    /// Toggle grid visibility in Plot State.
    ToggleGrid,
    /// Toggle the transient cursor/inspection surface.
    ToggleCursor,
    /// Toggle visibility for a focused series.
    ToggleSeriesVisibility { series: u64 },
    /// Perform a Legend operation.
    Legend { action: LegendAction },
    /// Perform an annotation operation.
    Annotation { action: AnnotationAction },
    /// Cancel a transient gesture or editing operation.
    Cancel,
    /// Request export at the host's selected output boundary.
    Export,
    /// Move focus through the runtime's semantic focus order.
    MoveFocus { direction: FocusDirection },
}

impl SemanticAction {
    /// Returns the state ownership class for this operation.
    pub(crate) const fn state_scope(self) -> ActionStateScope {
        match self {
            Self::Select { .. }
            | Self::ClearSelection
            | Self::Context { .. }
            | Self::Hover { .. }
            | Self::ToggleCursor
            | Self::Cancel
            | Self::MoveFocus { .. } => ActionStateScope::TransientUi,
            Self::Export => ActionStateScope::ReadOnly,
            Self::Pan { .. }
            | Self::Zoom { .. }
            | Self::BoxZoom { .. }
            | Self::Home
            | Self::Navigate { .. }
            | Self::History { .. }
            | Self::ToggleGrid
            | Self::ToggleSeriesVisibility { .. }
            | Self::Legend { .. }
            | Self::Annotation { .. } => ActionStateScope::PlotState,
        }
    }

    /// Returns whether the action must remain outside ordinary exports.
    pub(crate) const fn is_transient(self) -> bool {
        matches!(self.state_scope(), ActionStateScope::TransientUi)
    }
}

/// A normalized input event.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) enum InputEvent {
    /// A pointer gesture or transient pointer update.
    Pointer(PointerEvent),
    /// A normalized keyboard press.
    Keyboard(KeyboardEvent),
}

/// Presentation preference supplied by a caller without changing semantics.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) enum MotionPreference {
    /// Animated/interpolated presentation is permitted by the host.
    Normal,
    /// Animated/interpolated presentation should be removed or made immediate.
    Reduced,
}

/// Machine-readable input-routing failure.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum InputRouteErrorKind {
    /// The host supplied an unnormalized press/move/release phase.
    UnsupportedPointerPhase,
    /// A button-bearing phase omitted its button.
    MissingPointerButton,
    /// A buttonless phase supplied a button.
    UnexpectedPointerButton,
    /// The button is not accepted for the addressed phase.
    UnsupportedPointerButton,
    /// The target is not valid for the addressed operation.
    UnsupportedPointerTarget,
    /// Modifiers do not have an unambiguous meaning for the operation.
    UnsupportedModifierCombination,
    /// More than one semantic operation would fit the input and target.
    AmbiguousPointerCombination,
    /// The key is outside the accepted keyboard matrix.
    UnsupportedKeyboardKey,
    /// Modifiers do not have an accepted keyboard meaning for the key.
    UnsupportedKeyboardModifiers,
    /// The command needs a focus target but none is present.
    FocusRequired,
    /// The focused target cannot perform the requested command.
    UnsupportedFocusTarget,
    /// The key/focus pair admits no single safe semantic interpretation.
    AmbiguousKeyboardCombination,
}

/// Sanitized error returned when no unique semantic action can be selected.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct InputRouteError {
    kind: InputRouteErrorKind,
    message: &'static str,
}

impl InputRouteError {
    const fn new(kind: InputRouteErrorKind, message: &'static str) -> Self {
        Self { kind, message }
    }

    /// Returns the machine-readable failure kind.
    pub const fn kind(self) -> InputRouteErrorKind {
        self.kind
    }

    /// Returns sanitized human-readable detail.
    pub const fn message(self) -> &'static str {
        self.message
    }
}

impl fmt::Display for InputRouteError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.message)
    }
}

impl std::error::Error for InputRouteError {}

/// Routes an input using the supplied transient UI observations.
///
/// The function is pure: it does not mutate `state`, infer missing gesture
/// phases, consult a clock, or perform a scene/export operation.
pub(crate) fn route(
    event: InputEvent,
    state: TransientUiState,
) -> Result<SemanticAction, InputRouteError> {
    match event {
        InputEvent::Pointer(event) => route_pointer(event),
        InputEvent::Keyboard(event) => route_keyboard(event, state),
    }
}

/// Routes a pointer event without reading transient focus state.
pub(crate) fn route_pointer(event: PointerEvent) -> Result<SemanticAction, InputRouteError> {
    match event.phase {
        PointerPhase::Hover => {
            require_no_button(event.button)?;
            require_no_modifiers(event.modifiers)?;
            if !event.target.is_context_target() {
                return Err(InputRouteError::new(
                    InputRouteErrorKind::UnsupportedPointerTarget,
                    "hover target is outside the runtime semantic surface",
                ));
            }
            Ok(SemanticAction::Hover {
                target: event.target,
            })
        }
        PointerPhase::Cancel => {
            require_no_button(event.button)?;
            require_no_modifiers(event.modifiers)?;
            Ok(SemanticAction::Cancel)
        }
        PointerPhase::Drag => route_drag(event),
        PointerPhase::Wheel | PointerPhase::Trackpad => route_scroll(event),
        PointerPhase::Click => route_click(event),
        PointerPhase::DoubleClick => route_double_click(event),
        PointerPhase::Press | PointerPhase::Move | PointerPhase::Release => {
            Err(InputRouteError::new(
                InputRouteErrorKind::UnsupportedPointerPhase,
                "press, move, and release must be normalized to a gesture phase",
            ))
        }
    }
}

fn route_drag(event: PointerEvent) -> Result<SemanticAction, InputRouteError> {
    let button = require_button(event.button)?;
    if button != PointerButton::Left {
        return Err(InputRouteError::new(
            InputRouteErrorKind::UnsupportedPointerButton,
            "only the left button starts a pan or box-zoom drag",
        ));
    }

    let axis = event.target.gesture_axis()?;
    match event.modifiers {
        ModifierKeys::NONE => Ok(SemanticAction::Pan { axis }),
        ModifierKeys::SHIFT => Ok(SemanticAction::BoxZoom { axis }),
        _ => Err(InputRouteError::new(
            InputRouteErrorKind::UnsupportedModifierCombination,
            "drag modifiers must be empty for pan or exactly Shift for box zoom",
        )),
    }
}

fn route_scroll(event: PointerEvent) -> Result<SemanticAction, InputRouteError> {
    require_no_button(event.button)?;
    let axis = event.target.gesture_axis()?;
    require_no_modifiers(event.modifiers)?;
    Ok(SemanticAction::Zoom {
        axis,
        anchor: ZoomAnchor::Pointer,
    })
}

fn route_click(event: PointerEvent) -> Result<SemanticAction, InputRouteError> {
    let button = require_button(event.button)?;
    require_no_modifiers(event.modifiers)?;

    match button {
        PointerButton::Left => match event.target {
            PointerTarget::PlotBackground => Ok(SemanticAction::ClearSelection),
            PointerTarget::Series(series) => Ok(SemanticAction::Select {
                target: SelectionTarget::Series(series),
            }),
            PointerTarget::LegendEntry(series) => Ok(SemanticAction::Legend {
                action: LegendAction::ToggleVisibility { series },
            }),
            PointerTarget::Annotation(annotation) => Ok(SemanticAction::Select {
                target: SelectionTarget::Annotation(annotation),
            }),
            PointerTarget::XAxis
            | PointerTarget::YAxis
            | PointerTarget::Legend
            | PointerTarget::Other => Err(InputRouteError::new(
                InputRouteErrorKind::UnsupportedPointerTarget,
                "single click has no accepted selection operation for this target",
            )),
        },
        PointerButton::Right => {
            if !event.target.is_context_target() {
                return Err(InputRouteError::new(
                    InputRouteErrorKind::UnsupportedPointerTarget,
                    "context action needs a recognized semantic target",
                ));
            }
            Ok(SemanticAction::Context {
                target: event.target,
            })
        }
        PointerButton::Middle | PointerButton::Other(_) => Err(InputRouteError::new(
            InputRouteErrorKind::UnsupportedPointerButton,
            "the button is outside the accepted click matrix",
        )),
    }
}

fn route_double_click(event: PointerEvent) -> Result<SemanticAction, InputRouteError> {
    let button = require_button(event.button)?;
    if button != PointerButton::Left {
        return Err(InputRouteError::new(
            InputRouteErrorKind::UnsupportedPointerButton,
            "only the left button has an accepted double-click meaning",
        ));
    }
    require_no_modifiers(event.modifiers)?;

    match event.target {
        PointerTarget::PlotBackground
        | PointerTarget::Series(_)
        | PointerTarget::XAxis
        | PointerTarget::YAxis => Ok(SemanticAction::Home),
        PointerTarget::LegendEntry(series) => Ok(SemanticAction::Legend {
            action: LegendAction::Solo { series },
        }),
        PointerTarget::Annotation(_) | PointerTarget::Legend | PointerTarget::Other => {
            Err(InputRouteError::new(
                InputRouteErrorKind::AmbiguousPointerCombination,
                "double click has no unique operation for this target",
            ))
        }
    }
}

fn require_button(button: Option<PointerButton>) -> Result<PointerButton, InputRouteError> {
    button.ok_or_else(|| {
        InputRouteError::new(
            InputRouteErrorKind::MissingPointerButton,
            "this pointer phase requires an explicit button",
        )
    })
}

fn require_no_button(button: Option<PointerButton>) -> Result<(), InputRouteError> {
    if button.is_some() {
        Err(InputRouteError::new(
            InputRouteErrorKind::UnexpectedPointerButton,
            "this pointer phase must not carry a button",
        ))
    } else {
        Ok(())
    }
}

fn require_no_modifiers(modifiers: ModifierKeys) -> Result<(), InputRouteError> {
    if modifiers == ModifierKeys::NONE {
        Ok(())
    } else {
        Err(InputRouteError::new(
            InputRouteErrorKind::UnsupportedModifierCombination,
            "this semantic operation has no accepted modifier combination",
        ))
    }
}

/// Routes a normalized keyboard event using transient focus state.
pub fn route_keyboard(
    event: KeyboardEvent,
    state: TransientUiState,
) -> Result<SemanticAction, InputRouteError> {
    let focus = state.focus();
    match event.key {
        KeyboardKey::ArrowLeft
        | KeyboardKey::ArrowRight
        | KeyboardKey::ArrowUp
        | KeyboardKey::ArrowDown => {
            require_no_modifiers(event.modifiers)?;
            let direction = match event.key {
                KeyboardKey::ArrowLeft => NavigationDirection::Left,
                KeyboardKey::ArrowRight => NavigationDirection::Right,
                KeyboardKey::ArrowUp => NavigationDirection::Up,
                KeyboardKey::ArrowDown => NavigationDirection::Down,
                _ => unreachable!("the outer match limits navigation keys"),
            };
            Ok(SemanticAction::Navigate { direction })
        }
        KeyboardKey::PageUp => {
            require_no_modifiers(event.modifiers)?;
            Ok(SemanticAction::History {
                direction: HistoryDirection::Previous,
            })
        }
        KeyboardKey::PageDown => {
            require_no_modifiers(event.modifiers)?;
            Ok(SemanticAction::History {
                direction: HistoryDirection::Next,
            })
        }
        KeyboardKey::Home => {
            require_no_modifiers(event.modifiers)?;
            Ok(SemanticAction::Home)
        }
        KeyboardKey::Tab => match event.modifiers {
            ModifierKeys::NONE => Ok(SemanticAction::MoveFocus {
                direction: FocusDirection::Next,
            }),
            ModifierKeys::SHIFT => Ok(SemanticAction::MoveFocus {
                direction: FocusDirection::Previous,
            }),
            _ => Err(InputRouteError::new(
                InputRouteErrorKind::UnsupportedKeyboardModifiers,
                "focus movement accepts no modifier or exactly Shift",
            )),
        },
        KeyboardKey::Escape => {
            require_no_modifiers(event.modifiers)?;
            Ok(SemanticAction::Cancel)
        }
        KeyboardKey::G => {
            require_no_modifiers(event.modifiers)?;
            Ok(SemanticAction::ToggleGrid)
        }
        KeyboardKey::C => {
            require_no_modifiers(event.modifiers)?;
            Ok(SemanticAction::ToggleCursor)
        }
        KeyboardKey::E => {
            require_no_modifiers(event.modifiers)?;
            Ok(SemanticAction::Export)
        }
        KeyboardKey::V => {
            require_no_modifiers(event.modifiers)?;
            let series = focused_series(focus)?;
            Ok(SemanticAction::ToggleSeriesVisibility { series })
        }
        KeyboardKey::L => {
            require_no_modifiers(event.modifiers)?;
            let series = focused_legend_entry(focus)?;
            Ok(SemanticAction::Legend {
                action: LegendAction::ToggleVisibility { series },
            })
        }
        KeyboardKey::R => {
            require_no_modifiers(event.modifiers)?;
            let series = focused_legend_entry(focus)?;
            Ok(SemanticAction::Legend {
                action: LegendAction::Restore { series },
            })
        }
        KeyboardKey::A => {
            require_no_modifiers(event.modifiers)?;
            let action = match focus {
                Some(FocusTarget::Plot) => AnnotationAction::Create,
                Some(FocusTarget::Annotation(annotation)) => AnnotationAction::Edit { annotation },
                None => return Err(focus_required()),
                Some(FocusTarget::Legend)
                | Some(FocusTarget::LegendEntry(_))
                | Some(FocusTarget::Series(_)) => return Err(unsupported_focus()),
            };
            Ok(SemanticAction::Annotation { action })
        }
        KeyboardKey::Enter => {
            require_no_modifiers(event.modifiers)?;
            match focus {
                Some(FocusTarget::LegendEntry(series)) => Ok(SemanticAction::Legend {
                    action: LegendAction::ToggleVisibility { series },
                }),
                Some(FocusTarget::Annotation(annotation)) => Ok(SemanticAction::Annotation {
                    action: AnnotationAction::Edit { annotation },
                }),
                None => Err(focus_required()),
                Some(FocusTarget::Plot)
                | Some(FocusTarget::Legend)
                | Some(FocusTarget::Series(_)) => Err(InputRouteError::new(
                    InputRouteErrorKind::AmbiguousKeyboardCombination,
                    "Enter has no unique activation for this focused target",
                )),
            }
        }
        KeyboardKey::Space => {
            require_no_modifiers(event.modifiers)?;
            match focus {
                Some(FocusTarget::LegendEntry(series)) => Ok(SemanticAction::Legend {
                    action: LegendAction::ToggleVisibility { series },
                }),
                None => Err(focus_required()),
                Some(FocusTarget::Plot)
                | Some(FocusTarget::Legend)
                | Some(FocusTarget::Series(_))
                | Some(FocusTarget::Annotation(_)) => Err(unsupported_focus()),
            }
        }
        KeyboardKey::Delete => {
            require_no_modifiers(event.modifiers)?;
            match focus {
                Some(FocusTarget::Annotation(annotation)) => Ok(SemanticAction::Annotation {
                    action: AnnotationAction::Delete { annotation },
                }),
                None => Err(focus_required()),
                Some(FocusTarget::Plot)
                | Some(FocusTarget::Legend)
                | Some(FocusTarget::LegendEntry(_))
                | Some(FocusTarget::Series(_)) => Err(unsupported_focus()),
            }
        }
        KeyboardKey::Other(_) => Err(InputRouteError::new(
            InputRouteErrorKind::UnsupportedKeyboardKey,
            "keyboard key is outside the accepted semantic matrix",
        )),
    }
}

fn focused_series(focus: Option<FocusTarget>) -> Result<u64, InputRouteError> {
    match focus {
        Some(FocusTarget::Series(series)) | Some(FocusTarget::LegendEntry(series)) => Ok(series),
        None => Err(focus_required()),
        Some(FocusTarget::Plot) | Some(FocusTarget::Legend) | Some(FocusTarget::Annotation(_)) => {
            Err(unsupported_focus())
        }
    }
}

fn focused_legend_entry(focus: Option<FocusTarget>) -> Result<u64, InputRouteError> {
    match focus {
        Some(FocusTarget::LegendEntry(series)) => Ok(series),
        None => Err(focus_required()),
        Some(FocusTarget::Plot)
        | Some(FocusTarget::Legend)
        | Some(FocusTarget::Series(_))
        | Some(FocusTarget::Annotation(_)) => Err(unsupported_focus()),
    }
}

fn focus_required() -> InputRouteError {
    InputRouteError::new(
        InputRouteErrorKind::FocusRequired,
        "the keyboard operation requires a focused semantic target",
    )
}

fn unsupported_focus() -> InputRouteError {
    InputRouteError::new(
        InputRouteErrorKind::UnsupportedFocusTarget,
        "the focused target cannot perform this keyboard operation",
    )
}

/// Routes with an explicit motion preference while preserving action identity.
///
/// The preference belongs to a later presentation layer. Both values are
/// intentionally ignored here: an implementation may make a view transition
/// immediate for reduced motion, but it must execute the same semantic action.
pub(crate) fn route_with_motion(
    event: InputEvent,
    state: TransientUiState,
    motion: MotionPreference,
) -> Result<SemanticAction, InputRouteError> {
    let _ = motion;
    route(event, state)
}

// M4-B1 private host-event normalization plus headless view application.
//
// Hosts supply raw numeric reports; this layer maps them to the normalized
// gesture/key events above without inferring drags, clicks, double clicks, or
// trackpad gestures from a time-ordered stream and without consulting a
// clock. Pointer-coordinate conversion, drag state, and double-click timing
// policy remain future work and are never claimed here. View math below is a
// deterministic headless step (fixed fractions around the center) so
// pan/zoom/box/Home/history/cancel/focus can be exercised with exactly-once
// history semantics; real pointer-anchored geometry remains a later layer.
// Cursor/measurement, Legend/annotation state, text, and accessibility work
// are M5 and are never added here. `PlotScene` stays outside this crate: the
// caller applies a returned viewport through its own transaction and records
// exactly one revision per committed semantic transition.

/// Raw pointer report from a host event source.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) struct HostPointerReport {
    phase_code: u8,
    button_code: Option<u16>,
    modifier_bits: u8,
    target_code: u8,
    target_key: u64,
}

impl HostPointerReport {
    /// Constructs a raw host pointer report.
    pub(crate) const fn new(
        phase_code: u8,
        button_code: Option<u16>,
        modifier_bits: u8,
        target_code: u8,
        target_key: u64,
    ) -> Self {
        Self {
            phase_code,
            button_code,
            modifier_bits,
            target_code,
            target_key,
        }
    }

    /// Normalizes this report to a gesture-level event without timing inference.
    pub(crate) const fn normalize(self) -> Result<PointerEvent, InputRouteError> {
        let Some(phase) = decode_pointer_phase(self.phase_code) else {
            return Err(InputRouteError::new(
                InputRouteErrorKind::UnsupportedPointerPhase,
                "host pointer phase code is outside the accepted matrix",
            ));
        };
        let button = match self.button_code {
            None => None,
            Some(0) => Some(PointerButton::Left),
            Some(1) => Some(PointerButton::Right),
            Some(2) => Some(PointerButton::Middle),
            Some(other) => Some(PointerButton::Other(other)),
        };
        let Some(modifiers) = ModifierKeys::from_bits(self.modifier_bits) else {
            return Err(InputRouteError::new(
                InputRouteErrorKind::UnsupportedModifierCombination,
                "host modifier bits are outside the accepted matrix",
            ));
        };
        let target = match self.target_code {
            0 => PointerTarget::PlotBackground,
            1 => PointerTarget::Series(self.target_key),
            2 => PointerTarget::XAxis,
            3 => PointerTarget::YAxis,
            4 => PointerTarget::Legend,
            5 => PointerTarget::LegendEntry(self.target_key),
            6 => PointerTarget::Annotation(self.target_key),
            7 => PointerTarget::Other,
            _ => {
                return Err(InputRouteError::new(
                    InputRouteErrorKind::UnsupportedPointerTarget,
                    "host pointer target code is outside the accepted matrix",
                ));
            }
        };
        Ok(PointerEvent::new(phase, button, modifiers, target))
    }
}

const fn decode_pointer_phase(code: u8) -> Option<PointerPhase> {
    match code {
        0 => Some(PointerPhase::Hover),
        1 => Some(PointerPhase::Drag),
        2 => Some(PointerPhase::Click),
        3 => Some(PointerPhase::DoubleClick),
        4 => Some(PointerPhase::Wheel),
        5 => Some(PointerPhase::Trackpad),
        6 => Some(PointerPhase::Cancel),
        7 => Some(PointerPhase::Press),
        8 => Some(PointerPhase::Move),
        9 => Some(PointerPhase::Release),
        _ => None,
    }
}

/// Raw keyboard report from a host event source.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) struct HostKeyboardReport {
    key_code: u32,
    modifier_bits: u8,
}

impl HostKeyboardReport {
    /// Constructs a raw host keyboard report.
    pub(crate) const fn new(key_code: u32, modifier_bits: u8) -> Self {
        Self {
            key_code,
            modifier_bits,
        }
    }

    /// Normalizes this report to a key-press event.
    pub(crate) const fn normalize(self) -> Result<KeyboardEvent, InputRouteError> {
        let key = match self.key_code {
            0 => KeyboardKey::ArrowLeft,
            1 => KeyboardKey::ArrowRight,
            2 => KeyboardKey::ArrowUp,
            3 => KeyboardKey::ArrowDown,
            4 => KeyboardKey::PageUp,
            5 => KeyboardKey::PageDown,
            6 => KeyboardKey::Home,
            7 => KeyboardKey::Tab,
            8 => KeyboardKey::Enter,
            9 => KeyboardKey::Space,
            10 => KeyboardKey::Escape,
            11 => KeyboardKey::Delete,
            12 => KeyboardKey::A,
            13 => KeyboardKey::C,
            14 => KeyboardKey::E,
            15 => KeyboardKey::G,
            16 => KeyboardKey::L,
            17 => KeyboardKey::R,
            18 => KeyboardKey::V,
            other => KeyboardKey::Other(other),
        };
        let Some(modifiers) = ModifierKeys::from_bits(self.modifier_bits) else {
            return Err(InputRouteError::new(
                InputRouteErrorKind::UnsupportedKeyboardModifiers,
                "host modifier bits are outside the accepted matrix",
            ));
        };
        Ok(KeyboardEvent::new(key, modifiers))
    }
}

/// Maximum retained view-history entries for the headless B1 slice.
pub(crate) const VIEW_HISTORY_LIMIT: usize = 64;

/// Headless view history with forward-tail truncation on new commits.
#[derive(Clone, Debug, PartialEq)]
pub(crate) struct ViewHistory {
    entries: Vec<[f64; 4]>,
    index: usize,
}

impl ViewHistory {
    /// Starts a history at the stored canonical view.
    pub(crate) fn new(canonical: [f64; 4]) -> Self {
        Self {
            entries: vec![canonical],
            index: 0,
        }
    }

    /// Returns the current history entry.
    pub(crate) fn current(&self) -> [f64; 4] {
        self.entries[self.index]
    }

    /// Returns the number of retained entries.
    pub(crate) fn len(&self) -> usize {
        self.entries.len()
    }

    /// Pushes a committed view, truncating any forward tail. No-op views
    /// return `false` and must not advance a scene revision.
    pub(crate) fn push(&mut self, view: [f64; 4]) -> bool {
        if self.entries[self.index] == view {
            return false;
        }
        self.entries.truncate(self.index + 1);
        self.entries.push(view);
        self.index += 1;
        if self.entries.len() > VIEW_HISTORY_LIMIT {
            self.entries.remove(0);
            self.index -= 1;
        }
        true
    }

    /// Steps to the previous entry, if any.
    pub(crate) fn previous(&mut self) -> Option<[f64; 4]> {
        if self.index == 0 {
            None
        } else {
            self.index -= 1;
            Some(self.entries[self.index])
        }
    }

    /// Steps to the next entry, if any.
    pub(crate) fn next(&mut self) -> Option<[f64; 4]> {
        if self.index + 1 >= self.entries.len() {
            None
        } else {
            self.index += 1;
            Some(self.entries[self.index])
        }
    }
}

/// Applies a deterministic headless pan step (one tenth of the span).
pub(crate) const fn pan_viewport(current: [f64; 4], axis: AxisRestriction) -> [f64; 4] {
    let x_shift = (current[1] - current[0]) * 0.1;
    let y_shift = (current[3] - current[2]) * 0.1;
    match axis {
        AxisRestriction::Both => [
            current[0] + x_shift,
            current[1] + x_shift,
            current[2] + y_shift,
            current[3] + y_shift,
        ],
        AxisRestriction::X => [
            current[0] + x_shift,
            current[1] + x_shift,
            current[2],
            current[3],
        ],
        AxisRestriction::Y => [
            current[0],
            current[1],
            current[2] + y_shift,
            current[3] + y_shift,
        ],
    }
}

/// Applies a deterministic headless zoom step (0.8 around the center).
pub(crate) const fn zoom_viewport(current: [f64; 4], axis: AxisRestriction) -> [f64; 4] {
    const FACTOR: f64 = 0.8;
    let center_x = (current[0] + current[1]) * 0.5;
    let center_y = (current[2] + current[3]) * 0.5;
    let half_x = (current[1] - current[0]) * 0.5 * FACTOR;
    let half_y = (current[3] - current[2]) * 0.5 * FACTOR;
    match axis {
        AxisRestriction::Both => [
            center_x - half_x,
            center_x + half_x,
            center_y - half_y,
            center_y + half_y,
        ],
        AxisRestriction::X => [center_x - half_x, center_x + half_x, current[2], current[3]],
        AxisRestriction::Y => [current[0], current[1], center_y - half_y, center_y + half_y],
    }
}

/// Applies a deterministic headless box step (centered half extent).
pub(crate) const fn box_viewport(current: [f64; 4], axis: AxisRestriction) -> [f64; 4] {
    let center_x = (current[0] + current[1]) * 0.5;
    let center_y = (current[2] + current[3]) * 0.5;
    let quarter_x = (current[1] - current[0]) * 0.25;
    let quarter_y = (current[3] - current[2]) * 0.25;
    match axis {
        AxisRestriction::Both => [
            center_x - quarter_x,
            center_x + quarter_x,
            center_y - quarter_y,
            center_y + quarter_y,
        ],
        AxisRestriction::X => [
            center_x - quarter_x,
            center_x + quarter_x,
            current[2],
            current[3],
        ],
        AxisRestriction::Y => [
            current[0],
            current[1],
            center_y - quarter_y,
            center_y + quarter_y,
        ],
    }
}

/// Applies a deterministic headless keyboard-navigation step.
pub(crate) const fn navigate_viewport(
    current: [f64; 4],
    direction: NavigationDirection,
) -> [f64; 4] {
    let x_shift = (current[1] - current[0]) * 0.1;
    let y_shift = (current[3] - current[2]) * 0.1;
    match direction {
        NavigationDirection::Left => [
            current[0] - x_shift,
            current[1] - x_shift,
            current[2],
            current[3],
        ],
        NavigationDirection::Right => [
            current[0] + x_shift,
            current[1] + x_shift,
            current[2],
            current[3],
        ],
        NavigationDirection::Up => [
            current[0],
            current[1],
            current[2] + y_shift,
            current[3] + y_shift,
        ],
        NavigationDirection::Down => [
            current[0],
            current[1],
            current[2] - y_shift,
            current[3] - y_shift,
        ],
    }
}

/// Returns the stored canonical view for a Home transition.
pub(crate) const fn home_viewport(canonical: [f64; 4]) -> [f64; 4] {
    canonical
}

/// Advances focus through the B1 headless order (plot then Legend).
pub const fn next_focus(current: Option<FocusTarget>) -> Option<FocusTarget> {
    match current {
        None => Some(FocusTarget::Plot),
        Some(FocusTarget::Plot) => Some(FocusTarget::Legend),
        Some(FocusTarget::Legend) => Some(FocusTarget::Plot),
        Some(_) => Some(FocusTarget::Plot),
    }
}

/// Moves focus backward through the B1 headless order.
pub const fn previous_focus(current: Option<FocusTarget>) -> Option<FocusTarget> {
    match current {
        None => Some(FocusTarget::Legend),
        Some(FocusTarget::Plot) => Some(FocusTarget::Legend),
        Some(FocusTarget::Legend) => Some(FocusTarget::Plot),
        Some(_) => Some(FocusTarget::Plot),
    }
}

/// Buffers consecutive gesture steps so one commit covers one semantic gesture.
#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct PendingGesture {
    base: [f64; 4],
    pending: Option<[f64; 4]>,
}

impl PendingGesture {
    /// Starts a gesture buffer at the current committed view.
    pub(crate) const fn new(current: [f64; 4]) -> Self {
        Self {
            base: current,
            pending: None,
        }
    }

    /// Returns the view under construction, if any.
    pub(crate) const fn pending(self) -> Option<[f64; 4]> {
        self.pending
    }

    /// Buffers one pan step without committing history.
    pub(crate) const fn buffer_pan(mut self, axis: AxisRestriction) -> Self {
        let current = match self.pending {
            Some(view) => view,
            None => self.base,
        };
        self.pending = Some(pan_viewport(current, axis));
        self
    }

    /// Buffers one navigation step without committing history.
    pub(crate) const fn buffer_navigate(mut self, direction: NavigationDirection) -> Self {
        let current = match self.pending {
            Some(view) => view,
            None => self.base,
        };
        self.pending = Some(navigate_viewport(current, direction));
        self
    }

    /// Discards buffered steps without touching history.
    pub(crate) const fn cancel(mut self) -> Self {
        self.pending = None;
        self
    }

    /// Commits buffered steps as at most one history entry. Returns `true`
    /// only when history advanced and the caller must advance its scene
    /// revision exactly once.
    pub(crate) fn commit(&mut self, history: &mut ViewHistory) -> bool {
        let Some(view) = self.pending else {
            return false;
        };
        self.pending = None;
        if history.push(view) {
            self.base = view;
            true
        } else {
            false
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pointer(
        phase: PointerPhase,
        button: Option<PointerButton>,
        modifiers: ModifierKeys,
        target: PointerTarget,
    ) -> InputEvent {
        InputEvent::Pointer(PointerEvent::new(phase, button, modifiers, target))
    }

    fn keyboard(key: KeyboardKey, modifiers: ModifierKeys) -> InputEvent {
        InputEvent::Keyboard(KeyboardEvent::new(key, modifiers))
    }

    fn route_ok(event: InputEvent, state: TransientUiState) -> SemanticAction {
        route(event, state).expect("accepted semantic route")
    }

    fn route_err(event: InputEvent, state: TransientUiState) -> InputRouteErrorKind {
        route(event, state)
            .expect_err("route should reject the unsupported or ambiguous input")
            .kind()
    }

    #[test]
    fn modifier_bits_are_checked_and_composable() {
        let cases = [
            (ModifierKeys::NONE, 0),
            (ModifierKeys::SHIFT, 1),
            (ModifierKeys::CONTROL, 2),
            (ModifierKeys::ALT, 4),
            (ModifierKeys::SUPER, 8),
            (ModifierKeys::SHIFT.union(ModifierKeys::CONTROL), 1 | 2),
        ];
        for (modifiers, bits) in cases {
            assert_eq!(modifiers.bits(), bits);
            assert_eq!(ModifierKeys::from_bits(bits), Some(modifiers));
        }
        assert_eq!(ModifierKeys::from_bits(0b1_0000), None);
        assert_eq!(ModifierKeys::from_key(ModifierKey::Alt), ModifierKeys::ALT);
        assert_eq!(
            ModifierKeys::from_key(ModifierKey::Super),
            ModifierKeys::SUPER
        );
        assert_eq!(
            ModifierKeys::SHIFT.with(ModifierKey::Alt),
            ModifierKeys::SHIFT.union(ModifierKeys::ALT)
        );
        assert!(ModifierKeys::SHIFT.contains(ModifierKey::Shift));
        assert!(!ModifierKeys::SHIFT.contains(ModifierKey::Control));
        assert!(ModifierKeys::empty().is_empty());

        let _: Modifiers = ModifierKeys::NONE;
        let _: AxisConstraint = AxisRestriction::Both;
    }

    #[test]
    fn accepted_pointer_matrix_is_table_driven() {
        let cases = [
            (
                "plot pan",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                SemanticAction::Pan {
                    axis: AxisRestriction::Both,
                },
            ),
            (
                "series pan",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::Series(4),
                ),
                SemanticAction::Pan {
                    axis: AxisRestriction::Both,
                },
            ),
            (
                "x-axis pan",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::XAxis,
                ),
                SemanticAction::Pan {
                    axis: AxisRestriction::X,
                },
            ),
            (
                "y-axis pan",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::YAxis,
                ),
                SemanticAction::Pan {
                    axis: AxisRestriction::Y,
                },
            ),
            (
                "plot box zoom",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::SHIFT,
                    PointerTarget::PlotBackground,
                ),
                SemanticAction::BoxZoom {
                    axis: AxisRestriction::Both,
                },
            ),
            (
                "x-axis box zoom",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::SHIFT,
                    PointerTarget::XAxis,
                ),
                SemanticAction::BoxZoom {
                    axis: AxisRestriction::X,
                },
            ),
            (
                "y-axis box zoom",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::SHIFT,
                    PointerTarget::YAxis,
                ),
                SemanticAction::BoxZoom {
                    axis: AxisRestriction::Y,
                },
            ),
            (
                "wheel zoom",
                pointer(
                    PointerPhase::Wheel,
                    None,
                    ModifierKeys::NONE,
                    PointerTarget::Series(4),
                ),
                SemanticAction::Zoom {
                    axis: AxisRestriction::Both,
                    anchor: ZoomAnchor::Pointer,
                },
            ),
            (
                "trackpad x-axis zoom",
                pointer(
                    PointerPhase::Trackpad,
                    None,
                    ModifierKeys::NONE,
                    PointerTarget::XAxis,
                ),
                SemanticAction::Zoom {
                    axis: AxisRestriction::X,
                    anchor: ZoomAnchor::Pointer,
                },
            ),
            (
                "line selection",
                pointer(
                    PointerPhase::Click,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::Series(4),
                ),
                SemanticAction::Select {
                    target: SelectionTarget::Series(4),
                },
            ),
            (
                "background clear",
                pointer(
                    PointerPhase::Click,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                SemanticAction::ClearSelection,
            ),
            (
                "double-click home",
                pointer(
                    PointerPhase::DoubleClick,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                SemanticAction::Home,
            ),
            (
                "right-click context",
                pointer(
                    PointerPhase::Click,
                    Some(PointerButton::Right),
                    ModifierKeys::NONE,
                    PointerTarget::Series(4),
                ),
                SemanticAction::Context {
                    target: PointerTarget::Series(4),
                },
            ),
            (
                "Legend entry click",
                pointer(
                    PointerPhase::Click,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::LegendEntry(4),
                ),
                SemanticAction::Legend {
                    action: LegendAction::ToggleVisibility { series: 4 },
                },
            ),
            (
                "Legend entry double-click",
                pointer(
                    PointerPhase::DoubleClick,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::LegendEntry(4),
                ),
                SemanticAction::Legend {
                    action: LegendAction::Solo { series: 4 },
                },
            ),
            (
                "hover remains semantic and transient",
                pointer(
                    PointerPhase::Hover,
                    None,
                    ModifierKeys::NONE,
                    PointerTarget::Series(4),
                ),
                SemanticAction::Hover {
                    target: PointerTarget::Series(4),
                },
            ),
            (
                "pointer cancellation",
                pointer(
                    PointerPhase::Cancel,
                    None,
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                SemanticAction::Cancel,
            ),
        ];

        for (name, event, expected) in cases {
            assert_eq!(route_ok(event, TransientUiState::new()), expected, "{name}");
        }
    }

    #[test]
    fn pointer_rejections_are_explicit_and_table_driven() {
        let cases = [
            (
                "raw press",
                pointer(
                    PointerPhase::Press,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                InputRouteErrorKind::UnsupportedPointerPhase,
            ),
            (
                "raw move",
                pointer(
                    PointerPhase::Move,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                InputRouteErrorKind::UnsupportedPointerPhase,
            ),
            (
                "raw release",
                pointer(
                    PointerPhase::Release,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                InputRouteErrorKind::UnsupportedPointerPhase,
            ),
            (
                "drag without button",
                pointer(
                    PointerPhase::Drag,
                    None,
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                InputRouteErrorKind::MissingPointerButton,
            ),
            (
                "scroll with button",
                pointer(
                    PointerPhase::Wheel,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                InputRouteErrorKind::UnexpectedPointerButton,
            ),
            (
                "middle drag",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Middle),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                InputRouteErrorKind::UnsupportedPointerButton,
            ),
            (
                "right drag",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Right),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                InputRouteErrorKind::UnsupportedPointerButton,
            ),
            (
                "control drag",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::CONTROL,
                    PointerTarget::PlotBackground,
                ),
                InputRouteErrorKind::UnsupportedModifierCombination,
            ),
            (
                "shift-control drag",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::SHIFT.union(ModifierKeys::CONTROL),
                    PointerTarget::PlotBackground,
                ),
                InputRouteErrorKind::UnsupportedModifierCombination,
            ),
            (
                "shift wheel",
                pointer(
                    PointerPhase::Wheel,
                    None,
                    ModifierKeys::SHIFT,
                    PointerTarget::PlotBackground,
                ),
                InputRouteErrorKind::UnsupportedModifierCombination,
            ),
            (
                "drag Legend",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::Legend,
                ),
                InputRouteErrorKind::UnsupportedPointerTarget,
            ),
            (
                "scroll Legend entry",
                pointer(
                    PointerPhase::Trackpad,
                    None,
                    ModifierKeys::NONE,
                    PointerTarget::LegendEntry(4),
                ),
                InputRouteErrorKind::UnsupportedPointerTarget,
            ),
            (
                "axis click",
                pointer(
                    PointerPhase::Click,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::XAxis,
                ),
                InputRouteErrorKind::UnsupportedPointerTarget,
            ),
            (
                "ambiguous annotation double-click",
                pointer(
                    PointerPhase::DoubleClick,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::Annotation(7),
                ),
                InputRouteErrorKind::AmbiguousPointerCombination,
            ),
            (
                "unknown target context",
                pointer(
                    PointerPhase::Click,
                    Some(PointerButton::Right),
                    ModifierKeys::NONE,
                    PointerTarget::Other,
                ),
                InputRouteErrorKind::UnsupportedPointerTarget,
            ),
            (
                "right double-click",
                pointer(
                    PointerPhase::DoubleClick,
                    Some(PointerButton::Right),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                InputRouteErrorKind::UnsupportedPointerButton,
            ),
            (
                "other button click",
                pointer(
                    PointerPhase::Click,
                    Some(PointerButton::Other(8)),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                InputRouteErrorKind::UnsupportedPointerButton,
            ),
        ];

        for (name, event, expected) in cases {
            let error = route(event, TransientUiState::new())
                .expect_err("route should reject the unsupported or ambiguous input");
            assert_eq!(error.kind(), expected, "{name}");
            assert!(!error.message().is_empty(), "{name}");
        }
    }

    #[test]
    fn accepted_keyboard_matrix_is_table_driven() {
        let legend_entry = TransientUiState::with_focus(Some(FocusTarget::LegendEntry(9)));
        let annotation = TransientUiState::with_focus(Some(FocusTarget::Annotation(3)));
        let plot = TransientUiState::with_focus(Some(FocusTarget::Plot));
        let series = TransientUiState::with_focus(Some(FocusTarget::Series(9)));
        let cases = [
            (
                "left navigation",
                keyboard(KeyboardKey::ArrowLeft, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::Navigate {
                    direction: NavigationDirection::Left,
                },
            ),
            (
                "up navigation",
                keyboard(KeyboardKey::ArrowUp, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::Navigate {
                    direction: NavigationDirection::Up,
                },
            ),
            (
                "right navigation",
                keyboard(KeyboardKey::ArrowRight, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::Navigate {
                    direction: NavigationDirection::Right,
                },
            ),
            (
                "down navigation",
                keyboard(KeyboardKey::ArrowDown, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::Navigate {
                    direction: NavigationDirection::Down,
                },
            ),
            (
                "history previous",
                keyboard(KeyboardKey::PageUp, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::History {
                    direction: HistoryDirection::Previous,
                },
            ),
            (
                "history next",
                keyboard(KeyboardKey::PageDown, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::History {
                    direction: HistoryDirection::Next,
                },
            ),
            (
                "keyboard Home",
                keyboard(KeyboardKey::Home, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::Home,
            ),
            (
                "grid",
                keyboard(KeyboardKey::G, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::ToggleGrid,
            ),
            (
                "cursor",
                keyboard(KeyboardKey::C, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::ToggleCursor,
            ),
            (
                "export",
                keyboard(KeyboardKey::E, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::Export,
            ),
            (
                "Legend keyboard operation",
                keyboard(KeyboardKey::L, ModifierKeys::NONE),
                legend_entry,
                SemanticAction::Legend {
                    action: LegendAction::ToggleVisibility { series: 9 },
                },
            ),
            (
                "Legend Enter",
                keyboard(KeyboardKey::Enter, ModifierKeys::NONE),
                legend_entry,
                SemanticAction::Legend {
                    action: LegendAction::ToggleVisibility { series: 9 },
                },
            ),
            (
                "Legend Space",
                keyboard(KeyboardKey::Space, ModifierKeys::NONE),
                legend_entry,
                SemanticAction::Legend {
                    action: LegendAction::ToggleVisibility { series: 9 },
                },
            ),
            (
                "Legend restore",
                keyboard(KeyboardKey::R, ModifierKeys::NONE),
                legend_entry,
                SemanticAction::Legend {
                    action: LegendAction::Restore { series: 9 },
                },
            ),
            (
                "series visibility",
                keyboard(KeyboardKey::V, ModifierKeys::NONE),
                series,
                SemanticAction::ToggleSeriesVisibility { series: 9 },
            ),
            (
                "annotation create",
                keyboard(KeyboardKey::A, ModifierKeys::NONE),
                plot,
                SemanticAction::Annotation {
                    action: AnnotationAction::Create,
                },
            ),
            (
                "annotation edit",
                keyboard(KeyboardKey::A, ModifierKeys::NONE),
                annotation,
                SemanticAction::Annotation {
                    action: AnnotationAction::Edit { annotation: 3 },
                },
            ),
            (
                "annotation Enter",
                keyboard(KeyboardKey::Enter, ModifierKeys::NONE),
                annotation,
                SemanticAction::Annotation {
                    action: AnnotationAction::Edit { annotation: 3 },
                },
            ),
            (
                "annotation delete",
                keyboard(KeyboardKey::Delete, ModifierKeys::NONE),
                annotation,
                SemanticAction::Annotation {
                    action: AnnotationAction::Delete { annotation: 3 },
                },
            ),
            (
                "cancel",
                keyboard(KeyboardKey::Escape, ModifierKeys::NONE),
                legend_entry,
                SemanticAction::Cancel,
            ),
            (
                "focus next",
                keyboard(KeyboardKey::Tab, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::MoveFocus {
                    direction: FocusDirection::Next,
                },
            ),
            (
                "focus previous",
                keyboard(KeyboardKey::Tab, ModifierKeys::SHIFT),
                TransientUiState::new(),
                SemanticAction::MoveFocus {
                    direction: FocusDirection::Previous,
                },
            ),
        ];

        for (name, event, state, expected) in cases {
            assert_eq!(route_ok(event, state), expected, "{name}");
        }
    }

    #[test]
    fn keyboard_rejections_never_choose_a_focus_or_modifier_implicitly() {
        let cases = [
            (
                "unknown key",
                keyboard(KeyboardKey::Other(0xdead), ModifierKeys::NONE),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedKeyboardKey,
            ),
            (
                "control navigation",
                keyboard(KeyboardKey::ArrowLeft, ModifierKeys::CONTROL),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedModifierCombination,
            ),
            (
                "alt grid",
                keyboard(KeyboardKey::G, ModifierKeys::ALT),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedModifierCombination,
            ),
            (
                "control shift Tab",
                keyboard(
                    KeyboardKey::Tab,
                    ModifierKeys::SHIFT.union(ModifierKeys::CONTROL),
                ),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedKeyboardModifiers,
            ),
            (
                "Legend without focus",
                keyboard(KeyboardKey::L, ModifierKeys::NONE),
                TransientUiState::new(),
                InputRouteErrorKind::FocusRequired,
            ),
            (
                "Legend with plot focus",
                keyboard(KeyboardKey::L, ModifierKeys::NONE),
                TransientUiState::with_focus(Some(FocusTarget::Plot)),
                InputRouteErrorKind::UnsupportedFocusTarget,
            ),
            (
                "visibility without focus",
                keyboard(KeyboardKey::V, ModifierKeys::NONE),
                TransientUiState::new(),
                InputRouteErrorKind::FocusRequired,
            ),
            (
                "annotation delete on Legend",
                keyboard(KeyboardKey::Delete, ModifierKeys::NONE),
                TransientUiState::with_focus(Some(FocusTarget::LegendEntry(9))),
                InputRouteErrorKind::UnsupportedFocusTarget,
            ),
            (
                "annotation create on Legend",
                keyboard(KeyboardKey::A, ModifierKeys::NONE),
                TransientUiState::with_focus(Some(FocusTarget::Legend)),
                InputRouteErrorKind::UnsupportedFocusTarget,
            ),
            (
                "Enter on plot",
                keyboard(KeyboardKey::Enter, ModifierKeys::NONE),
                TransientUiState::with_focus(Some(FocusTarget::Plot)),
                InputRouteErrorKind::AmbiguousKeyboardCombination,
            ),
            (
                "Space on annotation",
                keyboard(KeyboardKey::Space, ModifierKeys::NONE),
                TransientUiState::with_focus(Some(FocusTarget::Annotation(3))),
                InputRouteErrorKind::UnsupportedFocusTarget,
            ),
        ];

        for (name, event, state, expected) in cases {
            assert_eq!(route_err(event, state), expected, "{name}");
        }
    }

    #[test]
    fn transient_state_is_observable_but_never_part_of_plot_actions() {
        let state = TransientUiState::new()
            .with_cursor(Some(PointerTarget::Series(1)))
            .with_hover(Some(PointerTarget::Series(2)))
            .with_context(Some(PointerTarget::LegendEntry(3)))
            .with_focus_target(Some(FocusTarget::LegendEntry(3)));
        assert_eq!(state.cursor(), Some(PointerTarget::Series(1)));
        assert_eq!(state.hover(), Some(PointerTarget::Series(2)));
        assert_eq!(state.context(), Some(PointerTarget::LegendEntry(3)));
        assert_eq!(state.focus(), Some(FocusTarget::LegendEntry(3)));

        let transient = [
            SemanticAction::Select {
                target: SelectionTarget::Series(1),
            },
            SemanticAction::ClearSelection,
            SemanticAction::Hover {
                target: PointerTarget::Series(2),
            },
            SemanticAction::Context {
                target: PointerTarget::LegendEntry(3),
            },
            SemanticAction::ToggleCursor,
            SemanticAction::Cancel,
            SemanticAction::MoveFocus {
                direction: FocusDirection::Next,
            },
        ];
        for action in transient {
            assert_eq!(action.state_scope(), ActionStateScope::TransientUi);
            assert!(action.is_transient());
        }
        assert_eq!(
            SemanticAction::Export.state_scope(),
            ActionStateScope::ReadOnly
        );
        assert_eq!(
            SemanticAction::ToggleGrid.state_scope(),
            ActionStateScope::PlotState
        );
    }

    #[test]
    fn reduced_motion_changes_presentation_preference_not_action_identity() {
        let cases = [
            (
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::XAxis,
                ),
                TransientUiState::new(),
            ),
            (
                pointer(
                    PointerPhase::Wheel,
                    None,
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
            ),
            (
                keyboard(KeyboardKey::Home, ModifierKeys::NONE),
                TransientUiState::new(),
            ),
            (
                keyboard(KeyboardKey::PageUp, ModifierKeys::NONE),
                TransientUiState::new(),
            ),
            (
                keyboard(KeyboardKey::L, ModifierKeys::NONE),
                TransientUiState::with_focus(Some(FocusTarget::LegendEntry(6))),
            ),
        ];

        for (event, state) in cases {
            let normal = route_with_motion(event, state, MotionPreference::Normal);
            let reduced = route_with_motion(event, state, MotionPreference::Reduced);
            assert_eq!(normal, reduced);
            assert_eq!(normal, route(event, state));
        }
    }

    // AT-REVIEW-A11Y (LP-UX-032 preference fixture): reduced motion must
    // preserve every accepted route. Both preferences delegate to `route`,
    // so Normal and Reduced agree on each action outcome and each error
    // kind/message, and both agree with the bare `route` result.
    #[test]
    fn at_review_a11y_reduced_motion_preserves_every_accepted_route() {
        assert_ne!(
            MotionPreference::Normal,
            MotionPreference::Reduced,
            "fixture must exercise two distinct preference values"
        );
        let legend_entry_9 = TransientUiState::with_focus(Some(FocusTarget::LegendEntry(9)));
        let legend_entry_6 = TransientUiState::with_focus(Some(FocusTarget::LegendEntry(6)));
        let annotation_3 = TransientUiState::with_focus(Some(FocusTarget::Annotation(3)));
        let plot = TransientUiState::with_focus(Some(FocusTarget::Plot));
        let series_9 = TransientUiState::with_focus(Some(FocusTarget::Series(9)));
        let legend_focus = TransientUiState::with_focus(Some(FocusTarget::Legend));
        let ok_cases = [
            (
                "plot pan",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                SemanticAction::Pan {
                    axis: AxisRestriction::Both,
                },
            ),
            (
                "series pan",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::Series(4),
                ),
                TransientUiState::new(),
                SemanticAction::Pan {
                    axis: AxisRestriction::Both,
                },
            ),
            (
                "x-axis pan",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::XAxis,
                ),
                TransientUiState::new(),
                SemanticAction::Pan {
                    axis: AxisRestriction::X,
                },
            ),
            (
                "y-axis pan",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::YAxis,
                ),
                TransientUiState::new(),
                SemanticAction::Pan {
                    axis: AxisRestriction::Y,
                },
            ),
            (
                "plot box zoom",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::SHIFT,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                SemanticAction::BoxZoom {
                    axis: AxisRestriction::Both,
                },
            ),
            (
                "series box zoom",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::SHIFT,
                    PointerTarget::Series(4),
                ),
                TransientUiState::new(),
                SemanticAction::BoxZoom {
                    axis: AxisRestriction::Both,
                },
            ),
            (
                "x-axis box zoom",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::SHIFT,
                    PointerTarget::XAxis,
                ),
                TransientUiState::new(),
                SemanticAction::BoxZoom {
                    axis: AxisRestriction::X,
                },
            ),
            (
                "y-axis box zoom",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::SHIFT,
                    PointerTarget::YAxis,
                ),
                TransientUiState::new(),
                SemanticAction::BoxZoom {
                    axis: AxisRestriction::Y,
                },
            ),
            (
                "wheel zoom plot",
                pointer(
                    PointerPhase::Wheel,
                    None,
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                SemanticAction::Zoom {
                    axis: AxisRestriction::Both,
                    anchor: ZoomAnchor::Pointer,
                },
            ),
            (
                "wheel zoom series",
                pointer(
                    PointerPhase::Wheel,
                    None,
                    ModifierKeys::NONE,
                    PointerTarget::Series(4),
                ),
                TransientUiState::new(),
                SemanticAction::Zoom {
                    axis: AxisRestriction::Both,
                    anchor: ZoomAnchor::Pointer,
                },
            ),
            (
                "wheel zoom x-axis",
                pointer(
                    PointerPhase::Wheel,
                    None,
                    ModifierKeys::NONE,
                    PointerTarget::XAxis,
                ),
                TransientUiState::new(),
                SemanticAction::Zoom {
                    axis: AxisRestriction::X,
                    anchor: ZoomAnchor::Pointer,
                },
            ),
            (
                "wheel zoom y-axis",
                pointer(
                    PointerPhase::Wheel,
                    None,
                    ModifierKeys::NONE,
                    PointerTarget::YAxis,
                ),
                TransientUiState::new(),
                SemanticAction::Zoom {
                    axis: AxisRestriction::Y,
                    anchor: ZoomAnchor::Pointer,
                },
            ),
            (
                "trackpad zoom plot",
                pointer(
                    PointerPhase::Trackpad,
                    None,
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                SemanticAction::Zoom {
                    axis: AxisRestriction::Both,
                    anchor: ZoomAnchor::Pointer,
                },
            ),
            (
                "trackpad zoom x-axis",
                pointer(
                    PointerPhase::Trackpad,
                    None,
                    ModifierKeys::NONE,
                    PointerTarget::XAxis,
                ),
                TransientUiState::new(),
                SemanticAction::Zoom {
                    axis: AxisRestriction::X,
                    anchor: ZoomAnchor::Pointer,
                },
            ),
            (
                "line selection",
                pointer(
                    PointerPhase::Click,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::Series(4),
                ),
                TransientUiState::new(),
                SemanticAction::Select {
                    target: SelectionTarget::Series(4),
                },
            ),
            (
                "background clear",
                pointer(
                    PointerPhase::Click,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                SemanticAction::ClearSelection,
            ),
            (
                "legend entry click",
                pointer(
                    PointerPhase::Click,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::LegendEntry(4),
                ),
                TransientUiState::new(),
                SemanticAction::Legend {
                    action: LegendAction::ToggleVisibility { series: 4 },
                },
            ),
            (
                "annotation select",
                pointer(
                    PointerPhase::Click,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::Annotation(7),
                ),
                TransientUiState::new(),
                SemanticAction::Select {
                    target: SelectionTarget::Annotation(7),
                },
            ),
            (
                "context series",
                pointer(
                    PointerPhase::Click,
                    Some(PointerButton::Right),
                    ModifierKeys::NONE,
                    PointerTarget::Series(4),
                ),
                TransientUiState::new(),
                SemanticAction::Context {
                    target: PointerTarget::Series(4),
                },
            ),
            (
                "context background",
                pointer(
                    PointerPhase::Click,
                    Some(PointerButton::Right),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                SemanticAction::Context {
                    target: PointerTarget::PlotBackground,
                },
            ),
            (
                "context x-axis",
                pointer(
                    PointerPhase::Click,
                    Some(PointerButton::Right),
                    ModifierKeys::NONE,
                    PointerTarget::XAxis,
                ),
                TransientUiState::new(),
                SemanticAction::Context {
                    target: PointerTarget::XAxis,
                },
            ),
            (
                "context legend entry",
                pointer(
                    PointerPhase::Click,
                    Some(PointerButton::Right),
                    ModifierKeys::NONE,
                    PointerTarget::LegendEntry(4),
                ),
                TransientUiState::new(),
                SemanticAction::Context {
                    target: PointerTarget::LegendEntry(4),
                },
            ),
            (
                "context annotation",
                pointer(
                    PointerPhase::Click,
                    Some(PointerButton::Right),
                    ModifierKeys::NONE,
                    PointerTarget::Annotation(7),
                ),
                TransientUiState::new(),
                SemanticAction::Context {
                    target: PointerTarget::Annotation(7),
                },
            ),
            (
                "double-click home background",
                pointer(
                    PointerPhase::DoubleClick,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                SemanticAction::Home,
            ),
            (
                "double-click home series",
                pointer(
                    PointerPhase::DoubleClick,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::Series(4),
                ),
                TransientUiState::new(),
                SemanticAction::Home,
            ),
            (
                "double-click home x-axis",
                pointer(
                    PointerPhase::DoubleClick,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::XAxis,
                ),
                TransientUiState::new(),
                SemanticAction::Home,
            ),
            (
                "double-click home y-axis",
                pointer(
                    PointerPhase::DoubleClick,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::YAxis,
                ),
                TransientUiState::new(),
                SemanticAction::Home,
            ),
            (
                "legend entry double-click solo",
                pointer(
                    PointerPhase::DoubleClick,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::LegendEntry(4),
                ),
                TransientUiState::new(),
                SemanticAction::Legend {
                    action: LegendAction::Solo { series: 4 },
                },
            ),
            (
                "hover series",
                pointer(
                    PointerPhase::Hover,
                    None,
                    ModifierKeys::NONE,
                    PointerTarget::Series(4),
                ),
                TransientUiState::new(),
                SemanticAction::Hover {
                    target: PointerTarget::Series(4),
                },
            ),
            (
                "hover background",
                pointer(
                    PointerPhase::Hover,
                    None,
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                SemanticAction::Hover {
                    target: PointerTarget::PlotBackground,
                },
            ),
            (
                "pointer cancellation",
                pointer(
                    PointerPhase::Cancel,
                    None,
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                SemanticAction::Cancel,
            ),
            (
                "left navigation",
                keyboard(KeyboardKey::ArrowLeft, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::Navigate {
                    direction: NavigationDirection::Left,
                },
            ),
            (
                "right navigation",
                keyboard(KeyboardKey::ArrowRight, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::Navigate {
                    direction: NavigationDirection::Right,
                },
            ),
            (
                "up navigation",
                keyboard(KeyboardKey::ArrowUp, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::Navigate {
                    direction: NavigationDirection::Up,
                },
            ),
            (
                "down navigation",
                keyboard(KeyboardKey::ArrowDown, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::Navigate {
                    direction: NavigationDirection::Down,
                },
            ),
            (
                "history previous",
                keyboard(KeyboardKey::PageUp, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::History {
                    direction: HistoryDirection::Previous,
                },
            ),
            (
                "history next",
                keyboard(KeyboardKey::PageDown, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::History {
                    direction: HistoryDirection::Next,
                },
            ),
            (
                "keyboard home",
                keyboard(KeyboardKey::Home, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::Home,
            ),
            (
                "focus next",
                keyboard(KeyboardKey::Tab, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::MoveFocus {
                    direction: FocusDirection::Next,
                },
            ),
            (
                "focus previous",
                keyboard(KeyboardKey::Tab, ModifierKeys::SHIFT),
                TransientUiState::new(),
                SemanticAction::MoveFocus {
                    direction: FocusDirection::Previous,
                },
            ),
            (
                "keyboard cancel",
                keyboard(KeyboardKey::Escape, ModifierKeys::NONE),
                legend_entry_9,
                SemanticAction::Cancel,
            ),
            (
                "grid",
                keyboard(KeyboardKey::G, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::ToggleGrid,
            ),
            (
                "cursor",
                keyboard(KeyboardKey::C, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::ToggleCursor,
            ),
            (
                "export",
                keyboard(KeyboardKey::E, ModifierKeys::NONE),
                TransientUiState::new(),
                SemanticAction::Export,
            ),
            (
                "series visibility via series focus",
                keyboard(KeyboardKey::V, ModifierKeys::NONE),
                series_9,
                SemanticAction::ToggleSeriesVisibility { series: 9 },
            ),
            (
                "series visibility via legend entry focus",
                keyboard(KeyboardKey::V, ModifierKeys::NONE),
                legend_entry_9,
                SemanticAction::ToggleSeriesVisibility { series: 9 },
            ),
            (
                "legend keyboard operation",
                keyboard(KeyboardKey::L, ModifierKeys::NONE),
                legend_entry_9,
                SemanticAction::Legend {
                    action: LegendAction::ToggleVisibility { series: 9 },
                },
            ),
            (
                "legend restore",
                keyboard(KeyboardKey::R, ModifierKeys::NONE),
                legend_entry_9,
                SemanticAction::Legend {
                    action: LegendAction::Restore { series: 9 },
                },
            ),
            (
                "annotation create",
                keyboard(KeyboardKey::A, ModifierKeys::NONE),
                plot,
                SemanticAction::Annotation {
                    action: AnnotationAction::Create,
                },
            ),
            (
                "annotation edit via A",
                keyboard(KeyboardKey::A, ModifierKeys::NONE),
                annotation_3,
                SemanticAction::Annotation {
                    action: AnnotationAction::Edit { annotation: 3 },
                },
            ),
            (
                "legend enter",
                keyboard(KeyboardKey::Enter, ModifierKeys::NONE),
                legend_entry_9,
                SemanticAction::Legend {
                    action: LegendAction::ToggleVisibility { series: 9 },
                },
            ),
            (
                "annotation enter",
                keyboard(KeyboardKey::Enter, ModifierKeys::NONE),
                annotation_3,
                SemanticAction::Annotation {
                    action: AnnotationAction::Edit { annotation: 3 },
                },
            ),
            (
                "legend space",
                keyboard(KeyboardKey::Space, ModifierKeys::NONE),
                legend_entry_9,
                SemanticAction::Legend {
                    action: LegendAction::ToggleVisibility { series: 9 },
                },
            ),
            (
                "annotation delete",
                keyboard(KeyboardKey::Delete, ModifierKeys::NONE),
                annotation_3,
                SemanticAction::Annotation {
                    action: AnnotationAction::Delete { annotation: 3 },
                },
            ),
        ];
        let err_cases = [
            (
                "raw press",
                pointer(
                    PointerPhase::Press,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedPointerPhase,
            ),
            (
                "raw move",
                pointer(
                    PointerPhase::Move,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedPointerPhase,
            ),
            (
                "raw release",
                pointer(
                    PointerPhase::Release,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedPointerPhase,
            ),
            (
                "drag without button",
                pointer(
                    PointerPhase::Drag,
                    None,
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                InputRouteErrorKind::MissingPointerButton,
            ),
            (
                "scroll with button",
                pointer(
                    PointerPhase::Wheel,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                InputRouteErrorKind::UnexpectedPointerButton,
            ),
            (
                "middle drag",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Middle),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedPointerButton,
            ),
            (
                "right drag",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Right),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedPointerButton,
            ),
            (
                "control drag",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::CONTROL,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedModifierCombination,
            ),
            (
                "shift-control drag",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::SHIFT.union(ModifierKeys::CONTROL),
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedModifierCombination,
            ),
            (
                "shift wheel",
                pointer(
                    PointerPhase::Wheel,
                    None,
                    ModifierKeys::SHIFT,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedModifierCombination,
            ),
            (
                "drag legend",
                pointer(
                    PointerPhase::Drag,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::Legend,
                ),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedPointerTarget,
            ),
            (
                "scroll legend entry",
                pointer(
                    PointerPhase::Trackpad,
                    None,
                    ModifierKeys::NONE,
                    PointerTarget::LegendEntry(4),
                ),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedPointerTarget,
            ),
            (
                "axis click",
                pointer(
                    PointerPhase::Click,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::XAxis,
                ),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedPointerTarget,
            ),
            (
                "ambiguous annotation double-click",
                pointer(
                    PointerPhase::DoubleClick,
                    Some(PointerButton::Left),
                    ModifierKeys::NONE,
                    PointerTarget::Annotation(7),
                ),
                TransientUiState::new(),
                InputRouteErrorKind::AmbiguousPointerCombination,
            ),
            (
                "unknown target context",
                pointer(
                    PointerPhase::Click,
                    Some(PointerButton::Right),
                    ModifierKeys::NONE,
                    PointerTarget::Other,
                ),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedPointerTarget,
            ),
            (
                "right double-click",
                pointer(
                    PointerPhase::DoubleClick,
                    Some(PointerButton::Right),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedPointerButton,
            ),
            (
                "other button click",
                pointer(
                    PointerPhase::Click,
                    Some(PointerButton::Other(8)),
                    ModifierKeys::NONE,
                    PointerTarget::PlotBackground,
                ),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedPointerButton,
            ),
            (
                "unknown key",
                keyboard(KeyboardKey::Other(0xdead), ModifierKeys::NONE),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedKeyboardKey,
            ),
            (
                "control navigation",
                keyboard(KeyboardKey::ArrowLeft, ModifierKeys::CONTROL),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedModifierCombination,
            ),
            (
                "alt grid",
                keyboard(KeyboardKey::G, ModifierKeys::ALT),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedModifierCombination,
            ),
            (
                "control shift tab",
                keyboard(
                    KeyboardKey::Tab,
                    ModifierKeys::SHIFT.union(ModifierKeys::CONTROL),
                ),
                TransientUiState::new(),
                InputRouteErrorKind::UnsupportedKeyboardModifiers,
            ),
            (
                "legend without focus",
                keyboard(KeyboardKey::L, ModifierKeys::NONE),
                TransientUiState::new(),
                InputRouteErrorKind::FocusRequired,
            ),
            (
                "legend with plot focus",
                keyboard(KeyboardKey::L, ModifierKeys::NONE),
                plot,
                InputRouteErrorKind::UnsupportedFocusTarget,
            ),
            (
                "visibility without focus",
                keyboard(KeyboardKey::V, ModifierKeys::NONE),
                TransientUiState::new(),
                InputRouteErrorKind::FocusRequired,
            ),
            (
                "annotation delete on legend",
                keyboard(KeyboardKey::Delete, ModifierKeys::NONE),
                legend_entry_9,
                InputRouteErrorKind::UnsupportedFocusTarget,
            ),
            (
                "annotation create on legend",
                keyboard(KeyboardKey::A, ModifierKeys::NONE),
                legend_focus,
                InputRouteErrorKind::UnsupportedFocusTarget,
            ),
            (
                "enter on plot",
                keyboard(KeyboardKey::Enter, ModifierKeys::NONE),
                plot,
                InputRouteErrorKind::AmbiguousKeyboardCombination,
            ),
            (
                "space on annotation",
                keyboard(KeyboardKey::Space, ModifierKeys::NONE),
                annotation_3,
                InputRouteErrorKind::UnsupportedFocusTarget,
            ),
        ];
        assert_eq!(
            ok_cases.len(),
            54,
            "fixture must pin its accepted-route count"
        );
        assert_eq!(err_cases.len(), 28, "fixture must pin its rejection count");
        let mut ok_seen = 0usize;
        for (name, event, state, expected) in ok_cases {
            let normal = route_with_motion(event, state, MotionPreference::Normal);
            let reduced = route_with_motion(event, state, MotionPreference::Reduced);
            assert_eq!(normal, reduced, "{name}");
            assert_eq!(normal, route(event, state), "{name}");
            assert_eq!(normal, Ok(expected), "{name}");
            ok_seen += 1;
        }
        let mut err_seen = 0usize;
        for (name, event, state, expected) in err_cases {
            let normal = route_with_motion(event, state, MotionPreference::Normal);
            let reduced = route_with_motion(event, state, MotionPreference::Reduced);
            assert_eq!(normal, reduced, "{name}");
            assert_eq!(normal, route(event, state), "{name}");
            let normal_err = normal.expect_err("route should reject the input");
            let reduced_err = reduced.expect_err("route should reject the input");
            assert_eq!(normal_err.kind(), expected, "{name}");
            assert_eq!(reduced_err.kind(), expected, "{name}");
            assert_eq!(normal_err.message(), reduced_err.message(), "{name}");
            assert!(!normal_err.message().is_empty(), "{name}");
            err_seen += 1;
        }
        assert_eq!(
            ok_seen, 54,
            "every accepted route must run under both motions"
        );
        assert_eq!(err_seen, 28, "every rejection must run under both motions");
        // The legend-entry focus used below keeps the fixture honest about the
        // second accepted focus source for the preference path.
        let focused = route_with_motion(
            keyboard(KeyboardKey::L, ModifierKeys::NONE),
            legend_entry_6,
            MotionPreference::Reduced,
        );
        assert_eq!(
            focused,
            Ok(SemanticAction::Legend {
                action: LegendAction::ToggleVisibility { series: 6 },
            })
        );
    }

    #[test]
    fn routes_are_deterministic_and_do_not_mutate_transient_input() {
        let state = TransientUiState::with_focus(Some(FocusTarget::LegendEntry(12)));
        let event = keyboard(KeyboardKey::L, ModifierKeys::NONE);
        let before = state;
        let first = route(event, state);
        let second = route(event, state);
        assert_eq!(first, second);
        assert_eq!(state, before);

        let keyboard_event = KeyboardEvent::new(KeyboardKey::G, ModifierKeys::SHIFT);
        assert_eq!(keyboard_event.key(), KeyboardKey::G);
        assert_eq!(keyboard_event.modifiers(), ModifierKeys::SHIFT);

        let pointer_event = PointerEvent::new(
            PointerPhase::Trackpad,
            None,
            ModifierKeys::NONE,
            PointerTarget::YAxis,
        );
        assert_eq!(pointer_event.phase(), PointerPhase::Trackpad);
        assert_eq!(pointer_event.button(), None);
        assert_eq!(pointer_event.modifiers(), ModifierKeys::NONE);
        assert_eq!(pointer_event.target(), PointerTarget::YAxis);
    }

    #[test]
    fn host_pointer_reports_normalize_without_timing_inference() {
        let drag = HostPointerReport::new(1, Some(0), 0, 0, 0)
            .normalize()
            .expect("drag report");
        assert_eq!(drag.phase(), PointerPhase::Drag);
        assert_eq!(drag.button(), Some(PointerButton::Left));
        assert_eq!(drag.target(), PointerTarget::PlotBackground);
        assert_eq!(
            route_pointer(drag).expect("drag route"),
            SemanticAction::Pan {
                axis: AxisRestriction::Both,
            }
        );

        let box_drag = HostPointerReport::new(1, Some(0), 1, 0, 0)
            .normalize()
            .expect("box report");
        assert_eq!(
            route_pointer(box_drag).expect("box route"),
            SemanticAction::BoxZoom {
                axis: AxisRestriction::Both,
            }
        );

        let wheel = HostPointerReport::new(4, None, 0, 1, 7)
            .normalize()
            .expect("wheel report");
        assert_eq!(
            route_pointer(wheel).expect("wheel route"),
            SemanticAction::Zoom {
                axis: AxisRestriction::Both,
                anchor: ZoomAnchor::Pointer,
            }
        );

        // Raw press/move/release normalize but never route: hosts must supply
        // an explicit gesture phase.
        for code in [7, 8, 9] {
            let raw = HostPointerReport::new(code, Some(0), 0, 0, 0)
                .normalize()
                .expect("raw phase normalizes");
            assert_eq!(
                route_pointer(raw)
                    .expect_err("raw phase must not route")
                    .kind(),
                InputRouteErrorKind::UnsupportedPointerPhase
            );
        }

        assert_eq!(
            HostPointerReport::new(99, None, 0, 0, 0)
                .normalize()
                .expect_err("unknown phase")
                .kind(),
            InputRouteErrorKind::UnsupportedPointerPhase
        );
        assert_eq!(
            HostPointerReport::new(1, Some(0), 0, 99, 0)
                .normalize()
                .expect_err("unknown target")
                .kind(),
            InputRouteErrorKind::UnsupportedPointerTarget
        );
        assert_eq!(
            HostPointerReport::new(1, Some(0), 0b1_0000, 0, 0)
                .normalize()
                .expect_err("unknown modifiers")
                .kind(),
            InputRouteErrorKind::UnsupportedModifierCombination
        );
    }

    #[test]
    fn host_keyboard_reports_normalize_with_checked_modifiers() {
        let home = HostKeyboardReport::new(6, 0)
            .normalize()
            .expect("home report");
        assert_eq!(home.key(), KeyboardKey::Home);
        assert_eq!(
            route_keyboard(home, TransientUiState::new()).expect("home route"),
            SemanticAction::Home
        );

        let focus_next = HostKeyboardReport::new(7, 0)
            .normalize()
            .expect("tab report");
        assert_eq!(
            route_keyboard(focus_next, TransientUiState::new()).expect("focus route"),
            SemanticAction::MoveFocus {
                direction: FocusDirection::Next,
            }
        );

        let other = HostKeyboardReport::new(0xdead, 0)
            .normalize()
            .expect("unknown key normalizes");
        assert_eq!(
            route_keyboard(other, TransientUiState::new())
                .expect_err("unknown key")
                .kind(),
            InputRouteErrorKind::UnsupportedKeyboardKey
        );
        assert_eq!(
            HostKeyboardReport::new(6, 0b1_0000)
                .normalize()
                .expect_err("unknown modifiers")
                .kind(),
            InputRouteErrorKind::UnsupportedKeyboardModifiers
        );
    }

    #[test]
    fn view_history_truncates_forward_tail_and_rejects_noops() {
        let canonical = [0.0, 10.0, 0.0, 10.0];
        let first = [1.0, 9.0, 1.0, 9.0];
        let second = [2.0, 8.0, 2.0, 8.0];
        let third = [3.0, 7.0, 3.0, 7.0];
        let mut history = ViewHistory::new(canonical);
        assert_eq!(history.current(), canonical);
        assert_eq!(history.len(), 1);

        assert!(history.push(first));
        assert!(history.push(second));
        assert_eq!(history.len(), 3);
        assert!(
            !history.push(second),
            "no-op commits must not advance history"
        );

        assert_eq!(history.previous(), Some(first));
        assert_eq!(history.current(), first);
        // A new commit truncates the forward tail.
        assert!(history.push(third));
        assert_eq!(history.len(), 3);
        assert_eq!(history.current(), third);
        assert_eq!(history.next(), None);
        assert_eq!(history.previous(), Some(first));
        assert_eq!(history.previous(), Some(canonical));
        assert_eq!(history.previous(), None);
    }

    #[test]
    fn headless_view_steps_are_deterministic_and_axis_scoped() {
        let current = [0.0, 10.0, 0.0, 10.0];
        assert_eq!(
            pan_viewport(current, AxisRestriction::Both),
            [1.0, 11.0, 1.0, 11.0]
        );
        assert_eq!(
            pan_viewport(current, AxisRestriction::X),
            [1.0, 11.0, 0.0, 10.0]
        );
        assert_eq!(
            pan_viewport(current, AxisRestriction::Y),
            [0.0, 10.0, 1.0, 11.0]
        );
        assert_eq!(
            zoom_viewport(current, AxisRestriction::Both),
            [1.0, 9.0, 1.0, 9.0]
        );
        assert_eq!(
            box_viewport(current, AxisRestriction::Both),
            [2.5, 7.5, 2.5, 7.5]
        );
        assert_eq!(
            navigate_viewport(current, NavigationDirection::Left),
            [-1.0, 9.0, 0.0, 10.0]
        );
        assert_eq!(
            navigate_viewport(current, NavigationDirection::Up),
            [0.0, 10.0, 1.0, 11.0]
        );
        assert_eq!(home_viewport(current), current);
        assert_eq!(VIEW_HISTORY_LIMIT, 64);
    }

    #[test]
    fn pending_gesture_coalesces_to_exactly_one_history_entry_and_cancel_is_free() {
        let canonical = [0.0, 10.0, 0.0, 10.0];
        let mut history = ViewHistory::new(canonical);
        let mut gesture = PendingGesture::new(canonical);
        assert_eq!(gesture.pending(), None);

        gesture = gesture.buffer_pan(AxisRestriction::Both);
        let once = gesture.pending().expect("buffered pan");
        gesture = gesture.buffer_navigate(NavigationDirection::Right);
        let twice = gesture.pending().expect("buffered navigation");
        assert_ne!(once, twice);

        assert!(gesture.commit(&mut history), "one commit for two buffers");
        assert_eq!(history.len(), 2);
        assert_eq!(history.current(), twice);
        assert_eq!(gesture.pending(), None);
        assert!(
            !gesture.commit(&mut history),
            "empty commit advances nothing"
        );

        let mut cancelled = PendingGesture::new(twice).buffer_pan(AxisRestriction::X);
        assert!(cancelled.pending().is_some());
        cancelled = cancelled.cancel();
        assert_eq!(cancelled.pending(), None);
        assert!(
            !cancelled.commit(&mut history),
            "cancel leaves history alone"
        );
        assert_eq!(history.len(), 2);
    }

    #[test]
    fn focus_cycle_is_explicit_and_bounded() {
        assert_eq!(next_focus(None), Some(FocusTarget::Plot));
        assert_eq!(
            next_focus(Some(FocusTarget::Plot)),
            Some(FocusTarget::Legend)
        );
        assert_eq!(
            next_focus(Some(FocusTarget::Legend)),
            Some(FocusTarget::Plot)
        );
        assert_eq!(previous_focus(None), Some(FocusTarget::Legend));
        assert_eq!(
            previous_focus(Some(FocusTarget::Plot)),
            Some(FocusTarget::Legend)
        );
        // Keyed targets collapse to the headless order; full Legend focus
        // state remains M5.
        assert_eq!(
            next_focus(Some(FocusTarget::LegendEntry(4))),
            Some(FocusTarget::Plot)
        );
    }
}
