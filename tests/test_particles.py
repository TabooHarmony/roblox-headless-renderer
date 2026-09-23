#!/usr/bin/env python3
"""Deterministic particle math: curves, seeds, and fixed-step motion."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
PARTICLE_FIXTURE = REPO / "tests" / "fixtures" / "particle_scene.rbxmx"

SCRIPT = r'''
import {sampleNumberSequence, sampleColorSequence, flipbookLayout, flipbookFrame, applyLocalTransparency, simulateEmitter} from './src/rhr/particles/sim.js';
const number = {keypoints: [{Time: 1, Value: 1}, {Time: 0, Value: 0}]};
const color = {keypoints: [
  {Time: 1, Value: {R: 0, G: 0, B: 1}},
  {Time: 0, Value: {R: 1, G: 0, B: 0}},
]};
if (sampleNumberSequence(number, 0.5) !== 0.5) throw new Error('number interpolation');
const rgb = sampleColorSequence(color, 0.5);
if (rgb.some((value, i) => Math.abs(value - [0.5, 0, 0.5][i]) > 1e-9)) throw new Error('color interpolation');
if (Math.abs(applyLocalTransparency(0.4, 0.25) - 0.55) > 1e-9) throw new Error('local transparency formula');
if (applyLocalTransparency(-1, 2) !== 1) throw new Error('local transparency clamp');
const emitter = {
  Acceleration: {X: 0, Y: -4, Z: 0},
  Color: {keypoints: [
    {Time: 0, Value: {R: 1, G: 0, B: 0}},
    {Time: 1, Value: {R: 1, G: 1, B: 0}},
  ]},
  Drag: 0.25,
  Enabled: true,
  Lifetime: {Min: 1, Max: 2},
  Rate: 12,
  Rotation: {Min: 0, Max: 360},
  RotSpeed: {Min: -90, Max: 90},
  Size: {keypoints: [{Time: 0, Value: 1}, {Time: 1, Value: 0}]},
  Speed: {Min: 4, Max: 8},
  SpreadAngle: {X: 20, Y: 20},
  Transparency: {keypoints: [{Time: 0, Value: 0}, {Time: 1, Value: 1}]},
};
const a = simulateEmitter(emitter, {duration: 1, dt: 1 / 30, seed: 7, origin: [0, 2, 0]});
const b = simulateEmitter(emitter, {duration: 1, dt: 1 / 30, seed: 7, origin: [0, 2, 0]});
if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error('seed is not deterministic');
if (a.length !== 31 || a.at(-1).particles.length === 0) throw new Error('fixed-step emission');
if (!a.at(-1).particles.some(p => p.position[1] !== 2)) throw new Error('particle did not move');
if (!a.at(-1).particles.some(p => Array.isArray(p.velocity) && p.velocity.length === 3)) throw new Error('particle velocity snapshot');
if (!a.at(-1).particles.some(p => Math.abs(p.position[0]) > 1e-6 || Math.abs(p.position[2]) > 1e-6)) throw new Error('spread angle did not affect direction');
const inheritedEmitter = {...emitter, Acceleration: {X: 0, Y: 0, Z: 0}, Drag: 0, Rate: 0, VelocityInheritance: 0.5, Speed: {Min: 0, Max: 0}, Lifetime: {Min: 2, Max: 2}};
const inheritedParticle = simulateEmitter(inheritedEmitter, {duration: 0, dt: 1 / 60, seed: 8, burst: 1, parentVelocity: [4, 0, 0]})[0].particles[0];
if (Math.abs(inheritedParticle.velocity[0] - 2) > 1e-9 || inheritedParticle.velocity[1] !== 0 || inheritedParticle.velocity[2] !== 0) throw new Error('velocity inheritance');
const lockedEmitter = {...inheritedEmitter, LockedToPart: true, VelocityInheritance: 0};
const lockedParticle = simulateEmitter(lockedEmitter, {duration: 0, dt: 1, seed: 8, burst: 1, parentVelocity: [4, 0, 0]})[0].particles[0];
if (Math.abs(lockedParticle.position[0] - 4) > 1e-9 || lockedParticle.velocity[0] !== 0) throw new Error('locked-to-part motion');
const unlockedParticle = simulateEmitter({...lockedEmitter, LockedToPart: false}, {duration: 0, dt: 1, seed: 8, burst: 1, parentVelocity: [4, 0, 0]})[0].particles[0];
if (Math.abs(unlockedParticle.position[0]) > 1e-9) throw new Error('unlocked particle moved with parent');
const capped = simulateEmitter({...emitter, Rate: 1000, Lifetime: {Min: 10, Max: 10}}, {duration: 1, dt: 1 / 60, seed: 1, maxParticles: 5});
if (capped.at(-1).particles.length > 5) throw new Error('particle cap');
const sphere = {...emitter, Shape: {name: 'Sphere'}, ShapeStyle: {name: 'Volume'}, ShapeInOut: {name: 'Outward'}, Speed: {Min: 0, Max: 0}, Lifetime: {Min: 10, Max: 10}};
const sphereFrame = simulateEmitter(sphere, {duration: 0, dt: 1 / 60, seed: 3, burst: 20, emitterSize: [10, 10, 10]})[0];
if (sphereFrame.particles.length !== 20) throw new Error('sphere burst count');
if (sphereFrame.particles.some(p => Math.hypot(...p.position) > 5 + 1e-9)) throw new Error('sphere volume bounds');
if (!sphereFrame.particles.some(p => Math.hypot(...p.position) > 1e-6)) throw new Error('sphere volume was not sampled');
const dome = {...sphere, ShapePartial: 0.5};
const domeFrame = simulateEmitter(dome, {duration: 0, dt: 1 / 60, seed: 4, burst: 50, emitterSize: [10, 10, 10]})[0];
if (domeFrame.particles.some(p => p.position[1] < -1e-9)) throw new Error('sphere partial cap');
const disc = {...sphere, Shape: {name: 'Disc'}, ShapePartial: 0.5};
const discFrame = simulateEmitter(disc, {duration: 0, dt: 1 / 60, seed: 5, burst: 50, emitterSize: [10, 10, 10]})[0];
if (discFrame.particles.some(p => Math.hypot(p.position[0], p.position[2]) < 2.5 - 1e-9)) throw new Error('disc partial annulus');
const flip = {FlipbookLayout: {name: 'Grid2x2'}, FlipbookFramerate: {Min: 4, Max: 4}, FlipbookMode: {name: 'Loop'}};
if (flipbookLayout(flip).join(',') !== '2,2') throw new Error('flipbook grid layout');
if (flipbookFrame(flip, 0, 2).index !== 0 || flipbookFrame(flip, 0.25, 2).index !== 1) throw new Error('flipbook loop timing');
if (flipbookFrame({...flip, FlipbookMode: {name: 'OneShot'}}, 1.99, 2).index !== 3) throw new Error('flipbook one-shot timing');
if (flipbookFrame({...flip, FlipbookMode: {name: 'PingPong'}}, 0.75, 2).index !== 3) throw new Error('flipbook ping-pong timing');
const custom = {FlipbookLayout: {name: 'Custom'}, FlipbookSizeX: 3, FlipbookSizeY: 2};
if (flipbookFrame(custom, 0, 1, 4).index !== 4 || flipbookFrame(custom, 0, 1, 4).columns !== 3) throw new Error('custom flipbook layout');
const squashEmitter = {...emitter, Squash: {keypoints: [{Time: 0, Value: 0}, {Time: 1, Value: 1}]}, Lifetime: {Min: 2, Max: 2}, Rate: 0, Speed: {Min: 0, Max: 0}};
const squashParticle = simulateEmitter(squashEmitter, {duration: 0, dt: 1, seed: 2, burst: 1})[0].particles[0];
if (Math.abs(squashParticle.squash - 0.5) > 1e-9) throw new Error('squash curve sampling');
console.log(`frames=${a.length} final_particles=${a.at(-1).particles.length}`);
'''


def main() -> int:
    node = shutil.which("node")
    if node is None:
        print("particle sim: FAIL: node is not on PATH")
        return 1
    result = subprocess.run(
        [node, "--input-type=module", "-e", SCRIPT],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
        return result.returncode
    print(f"particle sim: {result.stdout.strip()}")

    with tempfile.TemporaryDirectory(prefix="rhr-particles-test-") as directory:
        first = Path(directory) / "first.png"
        second = Path(directory) / "second.png"
        atlas = Path(directory) / "atlas.png"
        command = [
            *RHR, "particles", str(PARTICLE_FIXTURE),
            "--viewport", "300x200", "--times", "0,0.5,1", "--seed", "7", "--burst", "10",
        ]
        results = []
        for output in (first, second):
            run = subprocess.run(command + ["--out", str(output)], cwd=REPO,
                                  capture_output=True, text=True, timeout=60)
            if run.returncode:
                print(run.stdout, end="")
                print(run.stderr, end="", file=sys.stderr)
                return run.returncode
            results.append(run.stderr)
        atlas_run = subprocess.run(
            command + ["--texture-dir", str(REPO / "tests" / "fixtures" / "particle-textures"), "--out", str(atlas)],
            cwd=REPO, capture_output=True, text=True, timeout=60,
        )
        if atlas_run.returncode:
            print(atlas_run.stdout, end="")
            print(atlas_run.stderr, end="", file=sys.stderr)
            return atlas_run.returncode
        with Image.open(first) as image:
            first_pixels = image.convert("RGB").tobytes()
            dimensions = image.size
        with Image.open(second) as image:
            second_pixels = image.convert("RGB").tobytes()
        with Image.open(atlas) as image:
            atlas_pixels = image.convert("RGB").tobytes()
        warm = sum(
            1 for red, green, blue in zip(first_pixels[0::3], first_pixels[1::3], first_pixels[2::3])
            if red > green * 1.5 and red > blue * 1.5
        )
        checks = [
            (dimensions == (300, 600), "CLI contact sheet dimensions are correct"),
            (warm > 0, "CLI contact sheet contains visible particle pixels"),
            (first_pixels == second_pixels, "CLI particle pixels are deterministic"),
            (atlas_pixels != first_pixels and len(set(atlas_pixels)) > len(set(first_pixels)),
             "local flipbook atlas changes rendered pixels"),
            (all("3 frames" in stderr and "burst=10" in stderr for stderr in results),
             "CLI reports the frame count and burst trigger"),
        ]
        for ok, message in checks:
            print(f"  {'ok  ' if ok else 'FAIL'} {message}")
        if not all(ok for ok, _ in checks):
            return 1
    print("particle capture: ok")
    print("particle sim: ok")
    return 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
