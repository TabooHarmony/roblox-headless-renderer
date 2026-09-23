"""Pixel diff between two renders, for the parity gates.

Composites both images over the same background before comparing so that alpha
differences count, instead of being invisible wherever a pixel is transparent.
"""

from __future__ import annotations

from pathlib import Path


def compare(ref_path, out_path, bg=(255, 255, 255), silhouette_threshold: float = 8.0) -> dict:
    """Return deterministic image-change metrics between two renders.

    Besides pixel deltas, silhouette IoU thresholds each flattened image away from
    the requested background. This separates geometry/coverage changes from pure
    shading or color changes for agent iteration and Studio calibration alike.
    """
    import numpy as np
    from PIL import Image

    ref = Image.open(ref_path).convert("RGBA")
    out = Image.open(out_path).convert("RGBA")
    result = {
        "ref": str(ref_path),
        "out": str(out_path),
        "ref_size": ref.size,
        "out_size": out.size,
        "size_match": ref.size == out.size,
    }
    if ref.size != out.size:
        return result

    a = np.asarray(ref).astype(np.int16)
    b = np.asarray(out).astype(np.int16)
    result["identical_pct"] = round(100.0 * float((np.abs(a - b).max(axis=2) == 0).mean()), 4)

    bg_arr = np.array(bg, dtype=np.float64)

    def composite(x):
        alpha = x[..., 3:4].astype(np.float64) / 255.0
        return x[..., :3].astype(np.float64) * alpha + bg_arr * (1.0 - alpha)

    delta = np.abs(composite(a) - composite(b)).max(axis=2)
    result["within2_pct"] = round(100.0 * float((delta <= 2).mean()), 4)
    result["within8_pct"] = round(100.0 * float((delta <= 8).mean()), 4)
    result["max_delta"] = int(delta.max())
    result["mean_delta"] = round(float(delta.mean()), 4)
    result["changed_pct"] = round(100.0 * float((delta > 8).mean()), 4)

    composite_a = composite(a)
    composite_b = composite(b)
    silhouette_a = np.abs(composite_a - bg_arr).max(axis=2) > silhouette_threshold
    silhouette_b = np.abs(composite_b - bg_arr).max(axis=2) > silhouette_threshold
    intersection = int(np.logical_and(silhouette_a, silhouette_b).sum())
    union = int(np.logical_or(silhouette_a, silhouette_b).sum())
    result["silhouette"] = {
        "threshold": silhouette_threshold,
        "ref_pixels": int(silhouette_a.sum()),
        "out_pixels": int(silhouette_b.sum()),
        "intersection_pixels": intersection,
        "union_pixels": union,
        "iou": round(intersection / union, 6) if union else 1.0,
    }

    ys, xs = np.where(delta > 8)
    result["diff_bbox"] = (
        {"x": [int(xs.min()), int(xs.max())], "y": [int(ys.min()), int(ys.max())], "px": int(len(ys))}
        if len(ys)
        else None
    )
    result["non_transparent_pct"] = {
        "ref": round(100.0 * float((a[..., 3] > 0).mean()), 3),
        "out": round(100.0 * float((b[..., 3] > 0).mean()), 3),
    }
    return result


def format_report(metrics: dict) -> str:
    if not metrics.get("size_match", False):
        return (
            f"SIZE MISMATCH: ref {metrics['ref_size']} vs out {metrics['out_size']}\n"
            f"  ref={metrics['ref']}\n  out={metrics['out']}"
        )
    lines = [
        f"ref {metrics['ref_size']} vs out {metrics['out_size']} — identical {metrics['identical_pct']}%",
        f"  within 2/255 {metrics['within2_pct']}%   within 8/255 {metrics['within8_pct']}%",
        f"  max delta {metrics['max_delta']}   mean {metrics['mean_delta']}   changed {metrics['changed_pct']}%",
        f"  silhouette IoU {metrics['silhouette']['iou']:.6f} "
        f"({metrics['silhouette']['ref_pixels']} -> {metrics['silhouette']['out_pixels']} px)",
        f"  non-transparent: ref {metrics['non_transparent_pct']['ref']}%  out {metrics['non_transparent_pct']['out']}%",
    ]
    if metrics["diff_bbox"]:
        b = metrics["diff_bbox"]
        lines.append(f"  differing region: x {b['x'][0]}-{b['x'][1]}, y {b['y'][0]}-{b['y'][1]} ({b['px']} px)")
    else:
        lines.append("  no pixel differs by more than 8/255")
    return "\n".join(lines)