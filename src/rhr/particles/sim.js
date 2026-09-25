// Deterministic ParticleEmitter primitives for the browser preview.

// Parsed once per sequence: a still frame samples each one for every particle at every
// step while it looks for the fullest moment.
const keypointCache = new WeakMap();
function keypoints(sequence) {
  if (sequence && typeof sequence === 'object') {
    let points = keypointCache.get(sequence);
    if (!points) {
      points = parseKeypoints(sequence);
      keypointCache.set(sequence, points);
    }
    return points;
  }
  return parseKeypoints(sequence);
}

function parseKeypoints(sequence) {
  const points = (sequence?.keypoints || []).map((point, index) => ({
    time: Number(point.Time ?? point.time ?? 0),
    value: point.Value ?? point.value ?? 0,
    index,
  }));
  return points.sort((a, b) => a.time - b.time || a.index - b.index);
}

function bracket(points, time) {
  if (!points.length) return null;
  if (time <= points[0].time) return [points[0], points[0], 0];
  const last = points[points.length - 1];
  if (time >= last.time) return [last, last, 0];
  for (let i = 1; i < points.length; i += 1) {
    if (time <= points[i].time) {
      const a = points[i - 1];
      const b = points[i];
      const span = b.time - a.time;
      return [a, b, span === 0 ? 1 : (time - a.time) / span];
    }
  }
  return [last, last, 0];
}

export function sampleNumberSequence(sequence, time) {
  const pair = bracket(keypoints(sequence), Math.max(0, Math.min(1, Number(time))));
  if (!pair) return 0;
  const [a, b, alpha] = pair;
  return Number(a.value) + (Number(b.value) - Number(a.value)) * alpha;
}

export function sampleColorSequence(sequence, time) {
  const pair = bracket(keypoints(sequence), Math.max(0, Math.min(1, Number(time))));
  if (!pair) return [1, 1, 1];
  const [a, b, alpha] = pair;
  const av = a.value || {};
  const bv = b.value || {};
  return ["R", "G", "B"].map(channel =>
    Number(av[channel] ?? av[channel.toLowerCase()] ?? 1) +
      (Number(bv[channel] ?? bv[channel.toLowerCase()] ?? 1) -
        Number(av[channel] ?? av[channel.toLowerCase()] ?? 1)) * alpha,
  );
}

export function applyLocalTransparency(transparency, modifier = 0) {
  const value = Math.max(0, Math.min(1, Number(transparency)));
  const local = Math.max(0, Math.min(1, Number(modifier)));
  return 1 - ((1 - value) * (1 - local));
}

export function seededRandom(seed = 0) {
  let state = (Number(seed) >>> 0) || 0x6d2b79f5;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let value = Math.imul(state ^ (state >>> 15), 1 | state);
    value ^= value + Math.imul(value ^ (value >>> 7), 61 | value);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

export function sampleRange(range, random) {
  const min = Number(range?.Min ?? range?.min ?? range ?? 0);
  const max = Number(range?.Max ?? range?.max ?? range ?? min);
  return min + (max - min) * random();
}

export function flipbookLayout(emitter) {
  const layout = emitter?.FlipbookLayout?.name || "None";
  if (layout === "Grid2x2") return [2, 2];
  if (layout === "Grid4x4") return [4, 4];
  if (layout === "Grid8x8") return [8, 8];
  if (layout === "Custom") return [Math.max(1, Number(emitter?.FlipbookSizeX ?? 1)), Math.max(1, Number(emitter?.FlipbookSizeY ?? 1))];
  return [1, 1];
}

export function flipbookFrame(emitter, age, lifetime, startFrame = 0) {
  const [columns, rows] = flipbookLayout(emitter);
  const count = columns * rows;
  if (count <= 1) return {index: 0, columns, rows};
  const progress = Math.max(0, Math.min(1, Number(age) / Math.max(1e-6, Number(lifetime))));
  const elapsed = Math.max(0, Number(age));
  const mode = emitter?.FlipbookMode?.name || "Loop";
  const framerate = sampleRange(emitter?.FlipbookFramerate, () => 0.5);
  let index;
  if (mode === "OneShot") {
    index = Math.min(count - 1, Math.floor(progress * count));
  } else if (mode === "PingPong") {
    const cycle = Math.max(1, count * 2 - 2);
    const step = Math.floor(elapsed * Math.max(1, framerate));
    const position = (step + startFrame) % cycle;
    index = position < count ? position : cycle - position;
  } else {
    index = (Math.floor(elapsed * Math.max(1, framerate)) + startFrame) % count;
  }
  return {index, columns, rows};
}

function vector(value, fallback = [0, 0, 0]) {
  if (Array.isArray(value)) return value.map(component => Number(component));
  return [
    Number(value?.X ?? value?.x ?? fallback[0]),
    Number(value?.Y ?? value?.y ?? fallback[1]),
    Number(value?.Z ?? value?.z ?? fallback[2]),
  ];
}

function add(a, b) { return a.map((value, i) => value + b[i]); }
function scale(a, amount) { return a.map(value => value * amount); }

function emissionDirection(emitter) {
  const direction = emitter?.EmissionDirection?.name;
  if (direction === "Bottom") return [0, -1, 0];
  if (direction === "Left") return [-1, 0, 0];
  if (direction === "Right") return [1, 0, 0];
  if (direction === "Back") return [0, 0, 1];
  if (direction === "Front") return [0, 0, -1];
  return [0, 1, 0];
}

function normalize(value) {
  const length = Math.hypot(...value) || 1;
  return value.map(component => component / length);
}

function cross(a, b) {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}

function directionWithSpread(emitter, random) {
  const direction = emissionDirection(emitter);
  const reference = Math.abs(direction[1]) > 0.9 ? [0, 0, 1] : [0, 1, 0];
  const horizontal = normalize(cross(reference, direction));
  const vertical = normalize(cross(direction, horizontal));
  const spread = vector(emitter?.SpreadAngle, [0, 0, 0]);
  const yaw = (random() * 2 - 1) * Math.tan((spread[0] * Math.PI) / 360);
  const pitch = (random() * 2 - 1) * Math.tan((spread[1] * Math.PI) / 360);
  return normalize(add(direction, add(scale(horizontal, yaw), scale(vertical, pitch))));
}

function shapeOffset(emitter, random, size) {
  const [sx, sy, sz] = size.map(value => Math.max(0, Number(value || 0)));
  const shape = emitter?.Shape?.name || "Box";
  const partial = Math.max(0, Math.min(1, Number(emitter?.ShapePartial ?? 1)));
  const surface = emitter?.ShapeStyle?.name === "Surface";
  if (shape === "Sphere") {
    const zMin = Math.cos(partial * Math.PI);
    const z = zMin + random() * (1 - zMin);
    const angle = random() * Math.PI * 2;
    const radius = surface ? 1 : Math.cbrt(random());
    const ring = Math.sqrt(Math.max(0, 1 - z * z));
    return [Math.cos(angle) * ring * radius * sx / 2, z * radius * sy / 2, Math.sin(angle) * ring * radius * sz / 2];
  }
  if (shape === "Cylinder" || shape === "Disc") {
    const angle = random() * Math.PI * 2;
    if (shape === "Disc") {
      const inner = partial;
      const radius = surface ? 1 : Math.sqrt(inner * inner + random() * (1 - inner * inner));
      return [Math.cos(angle) * radius * sx / 2, 0, Math.sin(angle) * radius * sz / 2];
    }
    const y = surface ? (random() < 0.5 ? -1 : 1) : (random() * 2 - 1);
    const topScale = 1 - Math.max(0, y) * (1 - partial);
    const radius = (surface ? 1 : Math.sqrt(random())) * topScale;
    return [Math.cos(angle) * radius * sx / 2, y * sy / 2, Math.sin(angle) * radius * sz / 2];
  }
  if (!surface) return [(random() * 2 - 1) * sx / 2, (random() * 2 - 1) * sy / 2, (random() * 2 - 1) * sz / 2];
  const face = Math.floor(random() * 6);
  const point = [(random() * 2 - 1) * sx / 2, (random() * 2 - 1) * sy / 2, (random() * 2 - 1) * sz / 2];
  if (face === 0) point[0] = -sx / 2;
  if (face === 1) point[0] = sx / 2;
  if (face === 2) point[1] = -sy / 2;
  if (face === 3) point[1] = sy / 2;
  if (face === 4) point[2] = -sz / 2;
  if (face === 5) point[2] = sz / 2;
  return point;
}

function velocityDirection(emitter, random, offset) {
  const mode = emitter?.ShapeInOut?.name || "Outward";
  if ((emitter?.Shape?.name || "Box") !== "Box" && Math.hypot(...offset) > 1e-9) {
    let direction = normalize(offset);
    if (mode === "Inward" || (mode === "InAndOut" && random() >= 0.5)) direction = scale(direction, -1);
    return direction;
  }
  return directionWithSpread(emitter, random);
}

export function simulateEmitter(emitter, options = {}) {
  const duration = Math.max(0, Number(options.duration ?? 1));
  const dt = Math.max(1e-4, Number(options.dt ?? 1 / 60));
  const random = seededRandom(options.seed ?? 0);
  const particles = [];
  const frames = [];
  const maxParticles = Math.max(1, Math.floor(Number(options.maxParticles ?? 1000)));
  const origin = vector(options.origin);
  const acceleration = vector(emitter?.Acceleration);
  const parentVelocity = vector(options.parentVelocity);
  const inheritance = Math.max(0, Math.min(1, Number(emitter?.VelocityInheritance ?? 0)));
  const lockedToPart = emitter?.LockedToPart === true;
  const rate = Math.max(0, Number(emitter?.Rate ?? 0));
  const enabled = emitter?.Enabled !== false;
  const timeScale = Math.max(0, Number(emitter?.TimeScale ?? 1));
  let accumulator = Number(options.burst ?? 0);
  let elapsed = 0;

  while (elapsed <= duration + 1e-9) {
    if (enabled) accumulator += rate * dt * timeScale;
    while (accumulator >= 1) {
      accumulator -= 1;
      if (particles.length >= maxParticles) continue;
      const life = sampleRange(emitter?.Lifetime, random);
      const speed = sampleRange(emitter?.Speed, random);
      const offset = shapeOffset(emitter, random, vector(options.emitterSize));
      const [columns, rows] = flipbookLayout(emitter);
      const frameCount = columns * rows;
      const startFrame = emitter?.FlipbookStartRandom ? Math.floor(random() * frameCount) : 0;
      particles.push({
        age: 0,
        lifetime: Math.max(1e-4, life),
        position: add(origin, offset),
        velocity: add(scale(velocityDirection(emitter, random, offset), speed), scale(parentVelocity, inheritance)),
        rotation: sampleRange(emitter?.Rotation, random),
        rotSpeed: sampleRange(emitter?.RotSpeed, random),
        startFrame,
      });
    }

    const visible = [];
    const alive = [];
    for (const particle of particles) {
      particle.age += dt * timeScale;
      const drag = Math.max(0, Number(emitter?.Drag ?? 0));
      particle.velocity = add(
        scale(particle.velocity, Math.exp(-drag * dt * timeScale)),
        scale(acceleration, dt * timeScale),
      );
      particle.position = add(particle.position, scale(particle.velocity, dt * timeScale));
      if (lockedToPart) particle.position = add(particle.position, scale(parentVelocity, dt));
      particle.rotation += particle.rotSpeed * dt * timeScale;
      if (particle.age < particle.lifetime) {
        alive.push(particle);
        const lifeAlpha = particle.age / particle.lifetime;
        visible.push({
          age: particle.age,
          lifetime: particle.lifetime,
          frame: flipbookFrame(emitter, particle.age, particle.lifetime, particle.startFrame),
          position: [...particle.position],
          velocity: [...particle.velocity],
          rotation: particle.rotation,
          size: sampleNumberSequence(emitter?.Size, lifeAlpha),
          squash: sampleNumberSequence(emitter?.Squash, lifeAlpha),
          transparency: sampleNumberSequence(emitter?.Transparency, lifeAlpha),
          color: sampleColorSequence(emitter?.Color, lifeAlpha),
        });
      }
    }
    particles.length = 0;
    particles.push(...alive);
    frames.push({ time: elapsed, particles: visible });
    elapsed += dt;
  }
  return frames;
}

// ---------------------------------------------------------------------------
// Playing an effect for a still frame inside the 3D scene.
//
// Most VFX are not left running: the emitters are disabled and a script plays them
// with :Emit(). The community's convention keeps how to play each emitter in its
// attributes: EmitCount (particles emitted at once), EmitDelay (seconds after the
// effect starts) and EmitDuration (seconds the emitter is switched on at its Rate).
// RHR runs no scripts; it reads these and plays the emitters itself. An emitter that
// is Enabled also streams the whole time, as it does when the model sits in a place.

export function playSchedule(props, attributes) {
  const number = key => {
    const value = Number(attributes?.[key]);
    return attributes && key in attributes && Number.isFinite(value) ? value : null;
  };
  const count = number('EmitCount');
  const delay = Math.max(0, number('EmitDelay') ?? 0);
  const duration = number('EmitDuration');
  const rate = Math.max(0, Number(props?.Rate ?? 0));
  const bursts = [];
  const windows = [];
  if (count !== null && count >= 1) bursts.push({time: delay, count: Math.min(Math.floor(count), 5000)});
  if (duration !== null && duration > 0 && rate > 0) windows.push({start: delay, end: delay + duration});
  const running = props?.Enabled !== false && rate > 0;
  if (running) windows.push({start: -Infinity, end: Infinity});
  const played = bursts.length > 0 || windows.some(window => Number.isFinite(window.end));
  if (!bursts.length && !windows.length) return {kind: 'idle', bursts, windows, running: false, played: false};
  return {kind: played ? 'played' : 'running', bursts, windows, running, played};
}

function lifetimeMax(props) {
  const lifetime = props?.Lifetime;
  return Math.max(0, Number(lifetime?.Max ?? lifetime?.max ?? lifetime ?? 1));
}

// When the effect's own story ends: every burst and stream done and their particles gone.
export function playHorizon(props, schedule) {
  const life = Math.min(lifetimeMax(props), 20);
  let end = 0;
  for (const burst of schedule.bursts) end = Math.max(end, burst.time + life);
  for (const window of schedule.windows) if (Number.isFinite(window.end)) end = Math.max(end, window.end + life);
  return end;
}

// basis: [right, up, back], the parent's rotation columns as world vectors.
function mat3Apply(basis, v) {
  if (!basis) return v;
  return [
    basis[0][0] * v[0] + basis[1][0] * v[1] + basis[2][0] * v[2],
    basis[0][1] * v[0] + basis[1][1] * v[1] + basis[2][1] * v[2],
    basis[0][2] * v[0] + basis[1][2] * v[1] + basis[2][2] * v[2],
  ];
}

function rotateAbout(v, axis, angle) {
  const c = Math.cos(angle);
  const s = Math.sin(angle);
  const d = v[0] * axis[0] + v[1] * axis[1] + v[2] * axis[2];
  const x = cross(axis, v);
  return [0, 1, 2].map(i => v[i] * c + x[i] * s + axis[i] * d * (1 - c));
}

// SpreadAngle (X, Y) turns the direction by up to that many degrees about the two
// axes across it.
function spreadDirection(direction, spread, random) {
  const reference = Math.abs(direction[1]) > 0.9 ? [0, 0, 1] : [0, 1, 0];
  const across = normalize(cross(reference, direction));
  const other = normalize(cross(direction, across));
  let result = direction;
  const a = (random() * 2 - 1) * spread[0] * Math.PI / 180;
  const b = (random() * 2 - 1) * spread[1] * Math.PI / 180;
  if (a) result = rotateAbout(result, other, a);
  if (b) result = rotateAbout(result, across, b);
  return normalize(result);
}

// A seed per emitter from its path, so adding one emitter leaves the others as they were.
export function hashSeed(text, seed = 0) {
  let h = (2166136261 ^ Number(seed)) >>> 0;
  for (const char of String(text)) h = Math.imul(h ^ char.charCodeAt(0), 16777619) >>> 0;
  return h;
}

// Step one emitter from the start of its story to `until`, calling visit(time, particles)
// after every step at or past `from`. Positions and velocities are in world space.
export function playEmitter(props, schedule, options = {}) {
  const dt = Math.max(1e-3, Number(options.dt ?? 1 / 60));
  const random = seededRandom(options.seed ?? 0);
  const origin = vector(options.origin);
  const basis = options.basis || null;
  const size = vector(options.emitterSize);
  const acceleration = vector(props?.Acceleration);
  const drag = Math.max(0, Number(props?.Drag ?? 0));
  const rate = Math.max(0, Number(props?.Rate ?? 0));
  const timeScale = Math.max(0, Number(props?.TimeScale ?? 1));
  const spread = vector(props?.SpreadAngle, [0, 0, 0]);
  const shape = props?.Shape?.name || 'Box';
  const [columns, rows] = flipbookLayout(props);
  const until = Number(options.until ?? 0);
  const from = Number(options.from ?? until);
  const maxParticles = Math.max(1, Math.floor(Number(options.maxParticles ?? 4000)));
  // A running emitter has been on for a while already: start it one lifetime early.
  const start = schedule.running ? -Math.min(lifetimeMax(props), 20) - dt : 0;
  const bursts = schedule.bursts.map(burst => ({...burst, done: false}));
  const particles = [];
  let accumulator = 0;
  let wasOn = false;

  const spawn = () => {
    if (particles.length >= maxParticles) return;
    const lifetime = Math.max(1e-3, sampleRange(props?.Lifetime, random));
    const speed = sampleRange(props?.Speed, random);
    const localOffset = shapeOffset(props, random, size);
    const localDirection = shape !== 'Box' && Math.hypot(...localOffset) > 1e-9
      ? velocityDirection(props, random, localOffset)
      : spreadDirection(emissionDirection(props), spread, random);
    particles.push({
      age: 0,
      lifetime,
      position: add(origin, mat3Apply(basis, localOffset)),
      velocity: scale(mat3Apply(basis, localDirection), speed),
      rotation: sampleRange(props?.Rotation, random),
      rotSpeed: sampleRange(props?.RotSpeed, random),
      startFrame: props?.FlipbookStartRandom ? Math.floor(random() * columns * rows) : 0,
    });
  };

  const steps = Math.max(0, Math.round((until - start) / dt));
  for (let i = 0; i <= steps; i += 1) {
    const time = start + i * dt;
    const step = dt * timeScale;
    for (const burst of bursts) {
      if (!burst.done && time >= burst.time - 1e-9) {
        burst.done = true;
        for (let n = 0; n < burst.count; n += 1) spawn();
      }
    }
    const on = schedule.windows.some(window => time >= window.start - 1e-9 && time < window.end);
    // Switching an emitter on shows a particle straight away.
    if (on && !wasOn) accumulator = Math.max(accumulator, 1);
    wasOn = on;
    if (on) {
      accumulator += rate * step;
      while (accumulator >= 1) {
        accumulator -= 1;
        spawn();
      }
    }
    let alive = 0;
    for (const particle of particles) {
      particle.age += step;
      if (particle.age >= particle.lifetime) continue;
      particle.velocity = add(scale(particle.velocity, Math.exp(-drag * step)), scale(acceleration, step));
      particle.position = add(particle.position, scale(particle.velocity, step));
      particle.rotation += particle.rotSpeed * step;
      particles[alive] = particle;
      alive += 1;
    }
    particles.length = alive;
    if (time >= from - 1e-9 && options.visit) options.visit(time, particles);
  }
  return particles;
}

// What a particle looks like at its age: size, colour, transparency, flipbook frame.
export function particleLook(props, particle) {
  const alpha = particle.age / particle.lifetime;
  return {
    size: sampleNumberSequence(props?.Size, alpha),
    squash: sampleNumberSequence(props?.Squash, alpha),
    // Saved sequences can go past 0 and 1 (Roblox clamps them when drawing).
    transparency: Math.max(0, Math.min(1, sampleNumberSequence(props?.Transparency, alpha))),
    color: sampleColorSequence(props?.Color, alpha),
    frame: flipbookFrame(props, particle.age, particle.lifetime, particle.startFrame),
  };
}
