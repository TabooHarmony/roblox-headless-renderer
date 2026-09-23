# in-world UI semantics

This note records the current Creator Hub API surface before implementing
projection. It is deliberately limited to properties verified in the official
references. Rendering behavior not stated here remains a Studio-measured
question.

## BillboardGui

Source: <https://create.roblox.com/docs/reference/engine/classes/BillboardGui>

The current reference lists these properties:

- `Adornee`: the Instance the GUI is attached to.
- `AlwaysOnTop`: ordering behavior relative to 3D geometry.
- `Size`: a `UDim2`; the pixel offsets and scale components are part of the
  instance contract. A Roblox-specific interpretation of the scale components
  must be measured against Studio before treating them as world units.
- `SizeOffset`: `Vector2` size adjustment in studs.
- `StudsOffset`: `Vector3` offset in the adornee's local space.
- `StudsOffsetWorldSpace`: `Vector3` offset in world space.
- `ExtentsOffset` and `ExtentsOffsetWorldSpace`: additional 3D offsets.
- `MaxDistance`: distance limit for display.
- `LightInfluence` and `Brightness`: lighting controls for the in-world UI.
- `ClipsDescendants`: clipping behavior for GUI descendants.
- `Active`: interaction state.

`PlayerToHideFrom` and the deprecated distance-step/lower/upper properties are
also listed, but are outside the offline renderer's current contract.

## SurfaceGui

Sources:

- <https://create.roblox.com/docs/reference/engine/classes/SurfaceGui>
- <https://create.roblox.com/docs/reference/engine/classes/SurfaceGuiBase>
- <https://create.roblox.com/docs/reference/engine/enums/NormalId>
- <https://create.roblox.com/docs/reference/engine/enums/SurfaceGuiSizingMode>

`SurfaceGuiBase` supplies `Adornee`, `Face`, and `Active`. `Face` is a
`NormalId`: `Right`, `Top`, `Back`, `Left`, `Bottom`, or `Front`.

The current `SurfaceGui` reference lists:

- `CanvasSize`: the canvas dimensions used by fixed-size rendering.
- `PixelsPerStud`: the density used by world-sized rendering.
- `SizingMode`: `FixedSize` renders at the fixed `CanvasSize`; `PixelsPerStud`
  renders at a variable size based on `PixelsPerStud` and the SurfaceGui's size
  in studs.
- `ZOffset`: offset from the surface.
- `AlwaysOnTop`, `LightInfluence`, `Brightness`, `MaxDistance`, and
  `ClipsDescendants`.

The docs list the properties and enum meanings, but they do not fully specify
pixel rounding, face UV orientation, clipping at oblique angles, or how the
offline renderer should treat missing `Adornee`. Those are Studio comparison
gates, not assumptions.

## Implementation boundary

The first projection module will implement a deterministic pinhole projection
for a BillboardGui attached to a known world point. It will reject missing or
invalid camera/adornee data instead of silently inventing a placement. SurfaceGui
face mapping and full BillboardGui GUI composition remain separate steps.
