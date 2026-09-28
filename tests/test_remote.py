#!/usr/bin/env python3
"""Roblox asset ids and links as inputs (rhr.remote).

Which texts name an asset, and what `resolve` does with one: download it into the
cache named by its content, use it again without asking Roblox for a while, ask
again after that and download only a changed asset, refuse what is not a model or
place, and work offline from the cache. Roblox is faked: nothing here needs a login
or the network.

    python tests/test_remote.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


MODEL = b"<roblox!\x89\xff\r\n\x1a\n" + b"\0" * 16


def references(remote) -> None:
    print("which texts name an asset")
    cases = {
        "2810302648": "2810302648",
        "rbxassetid://2810302648": "2810302648",
        "https://create.roblox.com/store/asset/2810302648/a-CAR": "2810302648",
        "create.roblox.com/marketplace/asset/2810302648": "2810302648",
        "https://www.roblox.com/library/2810302648/a-CAR": "2810302648",
        "https://www.roblox.com/catalog/18711508268/Hat": "18711508268",
        "https://www.roblox.com/games/920587237/Adopt-Me?x=1": "920587237",
        "https://assetdelivery.roblox.com/v1/asset/?id=42": "42",
        "model.rbxm": None,
        "https://example.com/store/asset/1": None,
        "12abc": None,
    }
    for text, expected in cases.items():
        got = remote.asset_reference(text)
        check(got == expected, f"{text!r} -> {got!r}")


class Roblox:
    """A fake asset delivery: one asset, whose content can change."""

    def __init__(self, fetch, remote):
        self.fetch, self.remote = fetch, remote
        self.payload, self.key, self.type = MODEL, "v1", 10
        self.asked = self.downloads = 0
        self.saved = (fetch.answers_signed_in, fetch.answers_public, fetch._download, remote._details)

    def __enter__(self):
        def signed_in(ids):
            self.asked += 1
            return {i: {"location": f"https://cdn.example/{self.key}?sig=1", "type": self.type} for i in ids}

        def download(location):
            self.downloads += 1
            return self.payload

        self.fetch.answers_signed_in, self.fetch._download = signed_in, download
        self.fetch.answers_public = lambda ids: {}
        self.remote._details = lambda asset, out: out.update(name="Thing", creator="Someone", type=self.type)
        return self

    def __exit__(self, *exc):
        self.fetch.answers_signed_in, self.fetch.answers_public, self.fetch._download, self.remote._details = self.saved


def resolving(fetch, remote) -> None:
    asset = "990002001"
    for path in remote.MODEL_CACHE.glob(f"{asset}.*"):
        path.unlink()
    said: list[str] = []
    log = said.append

    print("the first use downloads; the next ones use the cache")
    with Roblox(fetch, remote) as roblox:
        first = remote.resolve(asset, log=log)
        check(first == remote.MODEL_CACHE / f"{asset}.rbxm", f"a binary model is cached as {first.name}")
        check(first.read_bytes() == MODEL, "with the downloaded bytes")
        check("\"Thing\" by Someone" in said[-1] and "downloaded" in said[-1], said[-1])
        again = remote.resolve(f"rbxassetid://{asset}", log=log)
        check(again == first and roblox.asked == 1, "used again without asking Roblox")

        print("after the wait: asked again, downloaded only when the content changed")
        meta = remote._load_meta(asset)
        meta["checked"] -= remote.REVALIDATE_AFTER + 1
        remote._save_meta(asset, meta)
        remote.resolve(asset, log=log)
        check(roblox.asked == 2 and roblox.downloads == 1, "unchanged: asked, not downloaded")
        check("unchanged" in said[-1], said[-1])
        meta = remote._load_meta(asset)
        meta["checked"] -= remote.REVALIDATE_AFTER + 1
        remote._save_meta(asset, meta)
        roblox.key, roblox.payload = "v2", b"<roblox xmlns:xmime='x'>" + b" " * 8
        changed = remote.resolve(asset, log=log)
        check(roblox.downloads == 2 and changed.suffix == ".rbxmx", f"changed: downloaded again ({changed.name})")
        check(not first.exists(), "the old binary copy is gone")

        print("offline: the cache, else a clear refusal")
        meta = remote._load_meta(asset)
        meta["checked"] -= remote.REVALIDATE_AFTER + 1
        remote._save_meta(asset, meta)
        os.environ["RHR_OFFLINE"] = "1"
        try:
            check(remote.resolve(asset, log=log) == changed and roblox.asked == 3, "offline uses the cache")
            try:
                remote.resolve("990002002", log=log)
                check(False, "an uncached asset offline is refused")
            except remote.AssetError as exc:
                check("--offline" in str(exc), str(exc))
        finally:
            del os.environ["RHR_OFFLINE"]

        print("not a model: refused with what it is")
        roblox.payload, roblox.type = b"version 2.00\n", 4
        try:
            remote.resolve("990002003", log=log)
            check(False, "a mesh is refused")
        except remote.AssetError as exc:
            check("is a mesh, not a model or place" in str(exc), str(exc))

        print("a place is cached as .rbxl")
        roblox.payload, roblox.type = MODEL, remote.PLACE_TYPE
        check(remote.resolve("990002004", log=log).suffix == ".rbxl", "a place keeps its kind")

    for path in remote.MODEL_CACHE.glob("99000200*.*"):
        path.unlink()


def main() -> int:
    from rhr import fetch, remote

    saved = os.environ.pop("RHR_OFFLINE", None)  # (the suite's switch; Roblox is faked here)
    try:
        references(remote)
        resolving(fetch, remote)
    finally:
        if saved is not None:
            os.environ["RHR_OFFLINE"] = saved
    if failures:
        print(f"{len(failures)} failure(s)")
        return 1
    print("remote: ok")
    return 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
