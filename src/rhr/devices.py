"""Screens players have: `--device desktop|laptop|phone|android|tablet|console`.

Each preset is one of Roblox Studio's device emulator presets, measured in a Studio
playtest on 2026-09-28 (the emulator's viewport; where a full-size Frame lands under
each ScreenInsets mode; the touch controls' positions): the viewport, the device's
safe area (a notch, a home bar), and on touch screens where Roblox puts the jump
button and the thumbstick, which a button under them loses its clicks to. All
landscape. The top bar is 58 px on every device measured.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Device:
    name: str
    studio_preset: str
    viewport: tuple[int, int]
    safe: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # left, top, right, bottom
    touch: bool = False
    # Where Roblox's touch controls are, as (x, y, w, h) in screen pixels.
    touch_controls: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)

    def describe(self) -> dict:
        return {"name": self.name, "studioPreset": self.studio_preset, "viewport": list(self.viewport),
                "safeInsets": dict(zip(("left", "top", "right", "bottom"), self.safe)), "touch": self.touch,
                "touchControls": {k: dict(zip(("x", "y", "w", "h"), v)) for k, v in self.touch_controls.items()}}


# Measured positions are the emulator's AbsolutePosition plus the safe area's origin
# (left inset, 58 px top bar); the thumbstick zone is clamped to the screen.
DEVICES = {
    "desktop": Device("desktop", "hd_1080", (1920, 1080)),
    "laptop": Device("laptop", "average_laptop", (1366, 768)),
    "phone": Device("phone", "iphone_16", (852, 393), safe=(59.0, 0.0, 59.0, 21.0), touch=True, touch_controls={
        "jumpButton": (697.0, 280.0, 70.0, 70.0),
        "thumbstick": (0.0, 162.0, 352.0, 231.0),
    }),
    "android": Device("android", "samsung_galaxy_a16", (780, 360), safe=(47.0, 0.0, 47.0, 21.0), touch=True,
                      touch_controls={
                          "jumpButton": (637.0, 248.0, 70.0, 70.0),
                          "thumbstick": (0.0, 151.0, 321.0, 209.0),
                      }),
    "tablet": Device("tablet", "ipad_10th_generation", (1180, 820), touch=True, touch_controls={
        "jumpButton": (1009.0, 609.0, 120.0, 120.0),
        "thumbstick": (0.0, 312.0, 472.0, 508.0),
    }),
    "console": Device("console", "xbox", (1920, 1080)),
}

# Set by the CLI's --device (the resident server resets it per command).
CURRENT: Device | None = None


def safe_insets() -> tuple[float, float, float, float]:
    """The current device's safe-area insets (none without --device)."""
    return CURRENT.safe if CURRENT is not None else (0.0, 0.0, 0.0, 0.0)
