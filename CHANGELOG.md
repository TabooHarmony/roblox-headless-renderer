# Changelog

All notable changes are recorded here. The repository has not been tagged yet, so
these notes describe the current unreleased tree.

## Unreleased

### Added

- CLI commands for IR emission, PNG rendering, layout dumps, model checks, hitmaps,
  image comparison, scene inspection, composed previews, and particle previews.
- Full-fidelity typed IR for Roblox model and place files, with explicit reporting for
  unreadable and unmapped properties.
- Static 3D scene rendering through a local THREE.js bundle, including primitives,
  cameras, materials, saved Lighting, optional shadows, decals, textures, Sky,
  Atmosphere, local mesh assets, Beam and Trail ribbons, and in-world UI baselines.
- ViewportFrame previews and deterministic ParticleEmitter simulation with bursts,
  shape volumes, flipbooks, brightness, transparency, and depth offset.
- Studio ground-truth fixtures, pixel and silhouette comparison tools, and a
  deterministic end-to-end test suite.

### Changed

- Model scaling now preserves authored WorldPivot, PrimaryPart, PivotOffset, nested
  scales, deformed wedge bounds, loaded mesh vertices, and analytic Ball/Cylinder
  bounds in the static scene path.
- Browser-backed rendering supports explicit camera controls and an optional
  persistent Chromium worker for repeated local renders.
- Third-party notices, vendored patches, and asset-cache boundaries are documented
  in the repository.

### Known limits

- This is a local authoring preview, not a replacement for Roblox Studio rendering.
  Studio remains the source of truth for parity measurements.
- UnionOperation and missing-asset geometry use explicit fallback paths, and the
  static lighting model remains an approximation.
