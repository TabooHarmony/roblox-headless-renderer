"""Where a ScreenGui's content area actually is, per Roblox's screen insets.

`ScreenGui.ScreenInsets` (Enum.ScreenInsets, docs: create.roblox.com/enums/ScreenInsets)
shrinks and shifts the region a ScreenGui's descendants are laid out in. The default,
`CoreUISafeInsets`, reserves the top bar. A renderer that ignores it puts every child
that many pixels too high, which in a ground-truth diff against Studio reads as a
uniform offset bug rather than a missing feature. This module is that offset.

Reference environment (see docs/known-approximations.md for sources):

    Roblox desktop, current top bar, no notch:  top 58, left/right/bottom 0

Device insets are zero there, which is why `None`, `DeviceSafeInsets` and
`FullscreenExtension` all resolve to the full viewport: on desktop they differ from
each other only on notched devices. Only the top bar changes the geometry.

`TopbarSafeInsets` is the one mode we do not model: its area is dynamic (it flexes
around the top bar's own controls at runtime), so any constant we picked would be
invented. It resolves to `CoreUISafeInsets` and says so, rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass

# Roblox's current desktop top bar. Sources, and why not 36, in
# docs/known-approximations.md.
REFERENCE_TOPBAR_HEIGHT = 58.0

MODES = {
    0: "None",
    1: "DeviceSafeInsets",
    2: "CoreUISafeInsets",
    3: "TopbarSafeInsets",
}

# Roblox's own default for a ScreenGui that does not say (and the value
# `IgnoreGuiInset = false`, the default, implies).
DEFAULT_MODE = "CoreUISafeInsets"


@dataclass(frozen=True)
class Inset:
    """A resolved content area: offsets in pixels plus how it was decided."""

    left: float
    top: float
    right: float
    bottom: float
    mode: str
    note: str = ""

    @property
    def is_noop(self) -> bool:
        return not any((self.left, self.top, self.right, self.bottom))

    def rect(self, width: float, height: float) -> tuple[float, float, float, float]:
        """(x, y, w, h) of the content area inside a width x height viewport."""
        return (
            self.left,
            self.top,
            max(0.0, width - self.left - self.right),
            max(0.0, height - self.top - self.bottom),
        )

    def describe(self) -> str:
        parts = [f"{name} {value:g}" for name, value in
                 (("top", self.top), ("left", self.left), ("right", self.right),
                  ("bottom", self.bottom)) if value]
        body = ", ".join(parts) if parts else "no inset"
        return f"{self.mode}: {body}" + (f" ({self.note})" if self.note else "")


def _truthy(value) -> bool:
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _mode_from_value(raw) -> str:
    """The enum's name from any of the shapes the IR may carry it in."""
    if isinstance(raw, dict):
        named = raw.get("name")
        if isinstance(named, str) and named in MODES.values():
            return named
        value = raw.get("value")
        if isinstance(value, int) and value in MODES:
            return MODES[value]
    elif isinstance(raw, str):
        tail = raw.rsplit(".", 1)[-1]
        if tail in MODES.values():
            return tail
    elif isinstance(raw, int) and raw in MODES:
        return MODES[raw]
    return DEFAULT_MODE


def mode_of(props: dict) -> str:
    """The ScreenGui's inset mode, from the IR's several possible shapes.

    The emitter writes enums as `{"_t": "EnumItem", "enum": ..., "name": ...,
    "value": ...}`; the adapter may have kept that dict or flattened it.

    An absent property means Roblox's own default, `CoreUISafeInsets`.
    `IgnoreGuiInset` is Roblox's deprecated flag, documented as setting
    `ScreenInsets` to `DeviceSafeInsets` when it is `true`. It is honoured only
    when the mode would otherwise be the default, so an explicit modern value
    always wins. On the desktop reference this changes nothing (device insets are
    zero), but it is what old place files mean, so the flag is respected.
    """
    raw = props.get("ScreenInsets")
    mode = _mode_from_value(raw) if raw is not None else DEFAULT_MODE
    if mode == DEFAULT_MODE and _truthy(props.get("IgnoreGuiInset")):
        return "DeviceSafeInsets"
    return mode


def resolve(mode: str, topbar_height: float = REFERENCE_TOPBAR_HEIGHT) -> Inset:
    """The inset for one mode in the reference environment."""
    if mode == "CoreUISafeInsets":
        return Inset(0.0, float(topbar_height), 0.0, 0.0, mode)
    if mode == "TopbarSafeInsets":
        return Inset(
            0.0,
            float(topbar_height),
            0.0,
            0.0,
            mode,
            "not modelled: dynamic, resolves to CoreUISafeInsets",
        )
    # None and DeviceSafeInsets: nothing on a desktop, no notch, no home bar.
    return Inset(0.0, 0.0, 0.0, 0.0, mode, "desktop: device insets are zero")


def for_nodes(
    nodes: list[dict],
    topbar_height: float = REFERENCE_TOPBAR_HEIGHT,
) -> Inset:
    """The inset of the ScreenGui the pipeline will draw, from raw engine nodes.

    `nodes` must already be in paint order (rhr.adapter.ir_to_raw_nodes), so the
    first ScreenGui here is the one `find_renderable` picks. Without a ScreenGui
    there is no container to inset.
    """
    for node in nodes:
        if node.get("className") == "ScreenGui":
            return resolve(mode_of(node.get("properties") or {}), topbar_height)
    return Inset(0.0, 0.0, 0.0, 0.0, "no ScreenGui", "nothing to inset")