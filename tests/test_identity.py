#!/usr/bin/env python3
"""Instance identity: same-named siblings and references never resolve silently wrong.

Roblox allows siblings with the same name, and real files are full of them ("Frame",
"Part", "Attachment"). The IR gives every node a numeric `id` and a unique `path`
in which same-named siblings are all indexed (`Card[1]`, `Card[2]`); references
(Attachment0/1, Adornee, PrimaryPart) carry the target's id in `refs`.

  * layout: both same-named Cards keep their own rect (one used to overwrite the other)
  * paths: a bare name that matches indexed siblings is an error naming them
  * --focus: the CLI refuses an ambiguous path instead of framing either node
  * Beam: Attachment0 is `RefScene.Post.A` by full name, shared by two attachments;
    the render must match the unambiguous scene, not the other post, and IR without
    ids must draw no beam rather than guess

    python tests/test_identity.py
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
DUPLICATE_NAMES = ROOT / "tests" / "fixtures" / "duplicate_names.rbxmx"
DUPLICATE_REFS = ROOT / "tests" / "fixtures" / "duplicate_refs.rbxmx"

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([*RHR, *args], cwd=ROOT, capture_output=True, text=True, timeout=180)


def walk(node: dict):
    yield node
    for child in node.get("children") or []:
        yield from walk(child)


def render(ir: dict, tmp: Path, name: str) -> bytes:
    source = tmp / f"{name}.json"
    out = tmp / f"{name}.png"
    source.write_text(json.dumps(ir), encoding="utf-8")
    proc = run(["scene", str(source), "--viewport", "320x240", "--camera", "0,2,-16",
                "--look-at", "0,2,0", "--out", str(out)])
    assert proc.returncode == 0, proc.stderr
    return out.read_bytes()


def pixels(png: bytes):
    import io

    from PIL import Image

    with Image.open(io.BytesIO(png)) as image:
        return list(image.convert("RGB").get_flattened_data())


def main() -> int:
    from rhr.ir import resolve_path

    with tempfile.TemporaryDirectory(prefix="rhr-identity-") as directory:
        tmp = Path(directory)

        print("identity: layout keeps same-named siblings apart")
        proc = run(["layout", str(DUPLICATE_NAMES), "--viewport", "400x300", "--topbar-height", "0"])
        assert proc.returncode == 0, proc.stderr
        layout = json.loads(proc.stdout)["rects"]
        first = layout.get("DuplicateNames/Root/Card[1]")
        second = layout.get("DuplicateNames/Root/Card[2]")
        check(first is not None and (first["x"], first["y"]) == (10.0, 10.0), f"Card[1] at (10, 10): {first}")
        check(second is not None and (second["x"], second["y"]) == (200.0, 150.0), f"Card[2] at (200, 150): {second}")
        check("DuplicateNames/Root/Card" not in layout, "no unindexed Card key")

        print("identity: IR ids, paths and refs")
        ir_path = tmp / "refs.json"
        proc = run(["ir", str(DUPLICATE_REFS), "--out", str(ir_path)])
        assert proc.returncode == 0, proc.stderr
        ir = json.loads(ir_path.read_text(encoding="utf-8"))
        nodes = [node for root in ir["roots"] for node in walk(root)]
        by_path = {node["path"]: node for node in nodes}
        check(len({node["id"] for node in nodes}) == len(nodes), "every node has a unique id")
        check({"RefScene/Post[1]/A", "RefScene/Post[2]/A"} <= set(by_path), "duplicate Posts are indexed")
        beam = by_path["RefScene/Hub/Link"]
        check(beam["props"]["Attachment0"] == "RefScene.Post.A", "full name alone is ambiguous")
        check(beam["refs"]["Attachment0"] == by_path["RefScene/Post[1]/A"]["id"], "ref id targets Post[1]/A")

        try:
            resolve_path(ir["roots"], "RefScene/Post")
            check(False, "bare Post should be ambiguous")
        except ValueError as exc:
            check("Post[1]" in str(exc) and "Post[2]" in str(exc), f"ambiguous path names candidates: {exc}")

        proc = run(["scene", str(ir_path), "--viewport", "160x120", "--focus", "RefScene/Post",
                    "--out", str(tmp / "focus.png")])
        check(proc.returncode != 0 and "ambiguous" in proc.stderr, "--focus refuses an ambiguous path")
        proc = run(["scene", str(ir_path), "--viewport", "160x120", "--focus", "RefScene/Post[2]",
                    "--out", str(tmp / "focus.png")])
        check(proc.returncode == 0, "--focus accepts an indexed path")

        print("identity: Beam resolves its attachment by id")
        actual = render(ir, tmp, "actual")

        def unambiguous(target: str) -> dict:
            # The same scene with unique names and no ids: resolution by name is exact.
            plain = copy.deepcopy(ir)
            for node in (n for root in plain["roots"] for n in walk(root)):
                node.pop("id", None)
                node.pop("path", None)
                node.pop("refs", None)
            posts = [n for root in plain["roots"] for n in walk(root) if n["name"] == "Post"]
            posts[0]["name"], posts[1]["name"] = "PostLeft", "PostRight"
            link = next(n for root in plain["roots"] for n in walk(root) if n["className"] == "Beam")
            link["props"]["Attachment0"] = f"RefScene.{target}.A"
            return plain

        expected = render(unambiguous("PostLeft"), tmp, "expected")
        wrong = render(unambiguous("PostRight"), tmp, "wrong")
        check(pixels(expected) != pixels(wrong), "the two posts produce different beams (test can tell)")
        check(pixels(actual) == pixels(expected), "beam attaches to Post[1], the referenced attachment")

        legacy = copy.deepcopy(ir)
        for node in (n for root in legacy["roots"] for n in walk(root)):
            node.pop("id", None)
            node.pop("path", None)
            node.pop("refs", None)
        guessed = render(legacy, tmp, "legacy")
        check(pixels(guessed) not in (pixels(expected), pixels(wrong)),
              "without ids an ambiguous full name draws no beam instead of guessing")

    print(f"identity: {len(failures)} failed" if failures else "identity: ok")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
