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
pub(crate) struct ModifierKeys(u8);

impl ModifierKeys {
    /// No modifiers are held.
    pub(crate) const NONE: Self = Self(0);
    /// Shift is held.
    pub(crate) const SHIFT: Self = Self(1 << 0);
    /// Control is held.
    pub(crate) const CONTROL: Self = Self(1 << 1);
    /// Alt/Option is held.
    pub(crate) const ALT: Self = Self(1 << 2);
    /// Super/Command/Windows is held.
    pub(crate) const SUPER: Self = Self(1 << 3);

    const KNOWN_BITS: u8 = Self::SHIFT.0 | Self::CONTROL.0 | Self::ALT.0 | Self::SUPER.0;

    /// Returns an empty modifier set.
    pub(crate) const fn empty() -> Self {
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
    pub(crate) const fn from_bits(bits: u8) -> Option<Self> {
        if bits & !Self::KNOWN_BITS == 0 {
            Some(Self(bits))
        } else {
            None
        }
    }

    /// Returns the checked bit representation.
    pub(crate) const fn bits(self) -> u8 {
        self.0
    }

    /// Returns whether a modifier is present.
    pub(crate) const fn contains(self, key: ModifierKey) -> bool {
        self.0 & Self::from_key(key).0 != 0
    }

    /// Returns whether no modifier is present.
    pub(crate) const fn is_empty(self) -> bool {
        self.0 == 0
    }

    /// Adds one modifier to this set.
    pub(crate) const fn with(self, key: ModifierKey) -> Self {
        Self(self.0 | Self::from_key(key).0)
    }

    /// Combines two checked modifier sets.
    pub(crate) const fn union(self, other: Self) -> Self {
        Self(self.0 | other.0)
    }
}

/// Compatibility spelling for code that calls the set `Modifiers`.
pub(crate) type Modifiers = ModifierKeys;

/// Axis scope attached to a pan, zoom, or box-zoom action.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) enum AxisRestriction {
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
pub(crate) enum PointerTarget {
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
pub(crate) enum KeyboardKey {
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
pub(crate) struct KeyboardEvent {
    key: KeyboardKey,
    modifiers: ModifierKeys,
}

impl KeyboardEvent {
    /// Constructs a normalized key-press event.
    pub(crate) const fn new(key: KeyboardKey, modifiers: ModifierKeys) -> Self {
        Self { key, modifiers }
    }

    /// Returns the normalized key.
    pub(crate) const fn key(self) -> KeyboardKey {
        self.key
    }

    /// Returns the modifier set.
    pub(crate) const fn modifiers(self) -> ModifierKeys {
        self.modifiers
    }
}

/// A focusable transient UI target.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) enum FocusTarget {
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
pub(crate) struct TransientUiState {
    cursor: Option<PointerTarget>,
    hover: Option<PointerTarget>,
    context: Option<PointerTarget>,
    focus: Option<FocusTarget>,
}

impl TransientUiState {
    /// Creates an empty transient UI state.
    pub(crate) const fn new() -> Self {
        Self {
            cursor: None,
            hover: None,
            context: None,
            focus: None,
        }
    }

    /// Returns a state with the supplied focus target.
    pub(crate) const fn with_focus(focus: Option<FocusTarget>) -> Self {
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
    pub(crate) const fn focus(self) -> Option<FocusTarget> {
        self.focus
    }
}

/// The two ways focus can move through the semantic control order.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) enum FocusDirection {
    /// Move to the next focusable target.
    Next,
    /// Move to the previous focusable target.
    Previous,
}

/// Direction for keyboard view navigation.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) enum NavigationDirection {
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
pub(crate) enum HistoryDirection {
    /// Restore the prior view entry.
    Previous,
    /// Restore the next view entry.
    Next,
}

/// An operation on the formal publication Legend.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) enum LegendAction {
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
pub(crate) enum AnnotationAction {
    /// Begin creation of an annotation.
    Create,
    /// Begin editing an existing annotation.
    Edit { annotation: u64 },
    /// Delete an existing annotation.
    Delete { annotation: u64 },
}

/// A selectable target for a transient selection highlight.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) enum SelectionTarget {
    /// A line/series target.
    Series(u64),
    /// An annotation target.
    Annotation(u64),
}

/// The required anchor semantics for pointer zoom.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) enum ZoomAnchor {
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
pub(crate) enum SemanticAction {
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
pub(crate) enum InputRouteErrorKind {
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
pub(crate) struct InputRouteError {
    kind: InputRouteErrorKind,
    message: &'static str,
}

impl InputRouteError {
    const fn new(kind: InputRouteErrorKind, message: &'static str) -> Self {
        Self { kind, message }
    }

    /// Returns the machine-readable failure kind.
    pub(crate) const fn kind(self) -> InputRouteErrorKind {
        self.kind
    }

    /// Returns sanitized human-readable detail.
    pub(crate) const fn message(self) -> &'static str {
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
pub(crate) fn route_keyboard(
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
}
