"""Pixel diff between two renders, for the parity gates.

Composites both images over the same background before comparing so that alpha
differences count, instead of being invisible wherever a pixel is transparent.
"""

from __future__ import annotations


def compare(before_path, after_path, bg=(255, 255, 255), silhouette_threshold: float = 8.0) -> dict:
    """Return deterministic image-change metrics between two renders.

    Besides pixel deltas, silhouette IoU thresholds each flattened image away from
    the requested background. This separates geometry/coverage changes from pure
    shading or color changes for agent iteration and Studio calibration alike.
    """
    import numpy as np
    from PIL import Image

    before = Image.open(before_path).convert("RGBA")
    after = Image.open(after_path).convert("RGBA")
    result = {
        "before": str(before_path),
        "after": str(after_path),
        "beforeSize": list(before.size),
        "afterSize": list(after.size),
        "sizeMatch": before.size == after.size,
    }
    if before.size != after.size:
        return result

    a = np.asarray(before).astype(np.int16)
    b = np.asarray(after).astype(np.int16)
    result["identicalPct"] = round(100.0 * float((np.abs(a - b).max(axis=2) == 0).mean()), 4)

    bg_arr = np.array(bg, dtype=np.float64)

    def composite(x):
        alpha = x[..., 3:4].astype(np.float64) / 255.0
        return x[..., :3].astype(np.float64) * alpha + bg_arr * (1.0 - alpha)

    delta = np.abs(composite(a) - composite(b)).max(axis=2)
    result["within2Pct"] = round(100.0 * float((delta <= 2).mean()), 4)
    result["within8Pct"] = round(100.0 * float((delta <= 8).mean()), 4)
    result["maxDelta"] = int(delta.max())
    result["meanDelta"] = round(float(delta.mean()), 4)
    result["changedPct"] = round(100.0 * float((delta > 8).mean()), 4)

    composite_a = composite(a)
    composite_b = composite(b)
    silhouette_a = np.abs(composite_a - bg_arr).max(axis=2) > silhouette_threshold
    silhouette_b = np.abs(composite_b - bg_arr).max(axis=2) > silhouette_threshold
    intersection = int(np.logical_and(silhouette_a, silhouette_b).sum())
    union = int(np.logical_or(silhouette_a, silhouette_b).sum())
    result["silhouette"] = {
        "threshold": silhouette_threshold,
        "beforePixels": int(silhouette_a.sum()),
        "afterPixels": int(silhouette_b.sum()),
        "intersectionPixels": intersection,
        "unionPixels": union,
        "iou": round(intersection / union, 6) if union else 1.0,
    }

    ys, xs = np.where(delta > 8)
    result["diffBox"] = (
        {"x": [int(xs.min()), int(xs.max())], "y": [int(ys.min()), int(ys.max())], "px": int(len(ys))}
        if len(ys)
        else None
    )
    result["nonTransparentPct"] = {
        "before": round(100.0 * float((a[..., 3] > 0).mean()), 3),
        "after": round(100.0 * float((b[..., 3] > 0).mean()), 3),
    }
    return result


def format_report(metrics: dict) -> str:
    """The same numbers for a person (stderr)."""
    if not metrics.get("sizeMatch", False):
        return (
            f"SIZE MISMATCH: before {metrics['beforeSize']} vs after {metrics['afterSize']}\n"
            f"  before={metrics['before']}\n  after={metrics['after']}"
        )
    lines = [
        f"before {metrics['beforeSize']} vs after {metrics['afterSize']}: identical {metrics['identicalPct']}%",
        f"  within 2/255 {metrics['within2Pct']}%   within 8/255 {metrics['within8Pct']}%",
        f"  max delta {metrics['maxDelta']}   mean {metrics['meanDelta']}   changed {metrics['changedPct']}%",
        f"  silhouette IoU {metrics['silhouette']['iou']:.6f} "
        f"({metrics['silhouette']['beforePixels']} -> {metrics['silhouette']['afterPixels']} px)",
        f"  non-transparent: before {metrics['nonTransparentPct']['before']}%  "
        f"after {metrics['nonTransparentPct']['after']}%",
    ]
    if metrics["diffBox"]:
        b = metrics["diffBox"]
        lines.append(f"  differing region: x {b['x'][0]}-{b['x'][1]}, y {b['y'][0]}-{b['y'][1]} ({b['px']} px)")
    else:
        lines.append("  no pixel differs by more than 8/255")
    return "\n".join(lines)
