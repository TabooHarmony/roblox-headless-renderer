#!/usr/bin/env python3
"""The cache stays under its limit: least recently used first, recent files kept; --clear."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-cache-test-") as directory:
        cache_dir = Path(directory)
        env = dict(os.environ, RHR_CACHE_DIR=str(cache_dir), PYTHONPATH=str(ROOT / "src"))
        images = cache_dir / "cache" / "icons"
        images.mkdir(parents=True)
        (cache_dir / "bin").mkdir()
        (cache_dir / "bin" / "lune").write_bytes(b"x" * 1000)  # never pruned
        now = time.time()
        for i in range(10):  # 10 files of 100 kB, one day apart; file 9 is from now
            path = images / f"{i}.png"
            path.write_bytes(b"x" * 100_000)
            stamp = now - (9 - i) * 86400
            os.utime(path, (stamp, stamp))
        code = """
import json
from rhr import cache
freed = cache.prune(limit=500_000)
print(json.dumps({"freed": freed, "left": sorted(p.name for p in cache.AREAS["images"].iterdir())}))
"""
        proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr
        result = json.loads(proc.stdout)
        # Down to 80% of the limit: 4 files; the oldest went, the newest stayed.
        assert result["left"] == ["6.png", "7.png", "8.png", "9.png"], result
        assert result["freed"] == 600_000, result
        assert (cache_dir / "bin" / "lune").is_file(), "pinned tools were pruned"

        listing = subprocess.run([sys.executable, "-m", "rhr", "cache"], env=env, capture_output=True, text=True, timeout=60)
        assert listing.returncode == 0 and "images" in listing.stdout and "0.4 MB" in listing.stdout, listing.stdout
        cleared = subprocess.run([sys.executable, "-m", "rhr", "cache", "--clear", "all"], env=env,
                                 capture_output=True, text=True, timeout=60)
        assert cleared.returncode == 0, cleared.stderr
        assert not images.exists() and (cache_dir / "bin" / "lune").is_file(), "clear all removed tools or kept images"
    print("cache: pruned least recently used to 80% of the limit, tools kept, --clear all")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
