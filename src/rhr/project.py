"""Deterministic pinhole projection for in-world GUI placement."""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Vec3:
    x: float
    y: float
    z: float

    def __sub__(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def dot(self, other: "Vec3") -> float:
        return self.x * other.x + self.y * other.y + self.z * other.z


@dataclass(frozen=True)
class Camera:
    position: Vec3
    right: Vec3
    up: Vec3
    forward: Vec3
    field_of_view: float


@dataclass(frozen=True)
class ProjectedPoint:
    x: float
    y: float
    depth: float


@dataclass(frozen=True)
class ProjectedRect:
    x: float
    y: float
    width: float
    height: float


def camera_from_cframe(cframe: dict, field_of_view: float = 70.0) -> Camera:
    """Build a camera from the IR CFrame's position and rotation matrix."""
    required = ("X", "Y", "Z", "R00", "R01", "R02", "R10", "R11", "R12", "R20", "R21", "R22")
    if any(key not in cframe for key in required):
        raise ValueError("camera CFrame is incomplete")
    return Camera(
        position=Vec3(float(cframe["X"]), float(cframe["Y"]), float(cframe["Z"])),
        right=Vec3(float(cframe["R00"]), float(cframe["R10"]), float(cframe["R20"])),
        up=Vec3(float(cframe["R01"]), float(cframe["R11"]), float(cframe["R21"])),
        forward=Vec3(-float(cframe["R02"]), -float(cframe["R12"]), -float(cframe["R22"])),
        field_of_view=float(field_of_view),
    )


def _validate(camera: Camera, viewport: tuple[int, int]) -> tuple[float, float, float]:
    width, height = viewport
    if width <= 0 or height <= 0:
        raise ValueError("viewport must be positive")
    if not 0 < camera.field_of_view < 180:
        raise ValueError("field of view must be between 0 and 180 degrees")
    scale = height / (2.0 * math.tan(math.radians(camera.field_of_view) / 2.0))
    return float(width), float(height), scale


def project_point(point: Vec3, camera: Camera, viewport: tuple[int, int]) -> ProjectedPoint | None:
    """Project a world point; return None when it is behind the camera."""
    width, height, scale = _validate(camera, viewport)
    relative = point - camera.position
    depth = relative.dot(camera.forward)
    if depth <= 0:
        return None
    camera_x = relative.dot(camera.right)
    camera_y = relative.dot(camera.up)
    return ProjectedPoint(width / 2.0 + camera_x * scale / depth, height / 2.0 - camera_y * scale / depth, depth)


def project_billboard(
    center: Vec3,
    size_studs: tuple[float, float],
    camera: Camera,
    viewport: tuple[int, int],
    max_distance: float | None = None,
) -> ProjectedRect | None:
    """Project a camera-facing billboard and clip it to the pixel viewport."""
    _, _, scale = _validate(camera, viewport)
    width_studs, height_studs = size_studs
    if width_studs < 0 or height_studs < 0:
        raise ValueError("billboard size must be non-negative")
    projected = project_point(center, camera, viewport)
    if projected is None or (max_distance is not None and projected.depth > max_distance):
        return None
    pixel_width = width_studs * scale / projected.depth
    pixel_height = height_studs * scale / projected.depth
    x = projected.x - pixel_width / 2.0
    y = projected.y - pixel_height / 2.0
    viewport_width, viewport_height = viewport
    left = max(0.0, x)
    top = max(0.0, y)
    right = min(float(viewport_width), x + pixel_width)
    bottom = min(float(viewport_height), y + pixel_height)
    if right <= left or bottom <= top:
        return None
    return ProjectedRect(left, top, right - left, bottom - top)
