#!/usr/bin/env python3
"""`--device`: a player's screen, as measured in Studio's emulator (rhr.devices).

A phone is 852x393 with 59 px notch insets and a 21 px home bar; CoreUISafeInsets
keeps a ScreenGui's content out of them and below the 58 px top bar. On a touch
screen a button where the jump button is, or reaching into the notch, is a finding;
on a desktop it is not.

    python tests/test_devices.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]

FIXTURE = """<roblox version="4">
  <Item class="ScreenGui" referent="A"><Properties><string name="Name">Hud</string></Properties>
    <Item class="TextButton" referent="B"><Properties><string name="Name">UnderJump</string>
      <UDim2 name="Position"><XS>0</XS><XO>638</XO><YS>0</YS><YO>222</YO></UDim2>
      <UDim2 name="Size"><XS>0</XS><XO>70</XO><YS>0</YS><YO>70</YO></UDim2></Properties></Item>
  </Item>
  <Item class="ScreenGui" referent="C"><Properties><string name="Name">Edge</string>
      <token name="ScreenInsets">0</token></Properties>
    <Item class="TextButton" referent="D"><Properties><string name="Name">InNotch</string>
      <UDim2 name="Position"><XS>0</XS><XO>10</XO><YS>0</YS><YO>100</YO></UDim2>
      <UDim2 name="Size"><XS>0</XS><XO>80</XO><YS>0</YS><YO>60</YO></UDim2></Properties></Item>
  </Item>
</roblox>
"""


def run(*args: str) -> dict:
    proc = subprocess.run([*RHR, *args], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode in (0, 1), proc.stderr[-500:]
    return json.loads(proc.stdout)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-devices-") as directory:
        ui = Path(directory) / "device.rbxmx"
        ui.write_text(FIXTURE, encoding="utf-8")
        layout = run("layout", str(ui), "--device", "phone")
        assert layout["viewport"] == [852, 393], layout["viewport"]
        # CoreUISafeInsets on the phone: left 59 (notch), top 58 (top bar).
        assert layout["rects"]["Hud/UnderJump"] == {"x": 697.0, "y": 280.0, "w": 70.0, "h": 70.0}, layout["rects"]
        # ScreenInsets None: the whole screen, notch included.
        assert layout["rects"]["Edge/InNotch"]["x"] == 10.0, layout["rects"]["Edge/InNotch"]

        phone = {(f["check"], f["paths"][0]) for f in run("check", str(ui), "--device", "phone")["findings"]}
        assert ("under-touch-controls", "Hud/UnderJump") in phone, phone
        assert ("under-notch", "Edge/InNotch") in phone, phone
        desktop = {f["check"] for f in run("check", str(ui))["findings"]}
        assert not desktop & {"under-touch-controls", "under-notch"}, desktop

        every = run("check", str(ui), "--devices", "all")["findings"]
        jump = [f for f in every if f["check"] == "under-touch-controls" and f["paths"][0] == "Hud/UnderJump"]
        assert jump and "phone" in jump[0]["devices"] and "desktop" not in jump[0]["devices"], jump
    print("devices: phone viewport and safe area, touch-control and notch checks, --devices all")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
