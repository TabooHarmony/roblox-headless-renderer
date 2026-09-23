import * as THREE from '../../../vendor/three/three.module.js';
import {applyLocalTransparency, simulateEmitter} from './sim.js';

const params = new URLSearchParams(location.search);
const tileWidth = Math.max(1, Number(params.get('width') || 400));
const tileHeight = Math.max(1, Number(params.get('height') || 300));
const times = (params.get('times') || '0,0.5,1').split(',').map(Number).filter(Number.isFinite);
const requestedTimes = times.length ? times : [0];
const maxTime = Math.max(...requestedTimes, 0);
const seed = Number(params.get('seed') || 0);
const burst = Math.max(0, Math.floor(Number(params.get('burst') || 0)));
const effectsOnly = params.get('effectsOnly') === '1';
const canvas = document.querySelector('#rhr-particles');
const particleTextureCache = new Map();
const particleAssetManifest = fetch('/__rhr_assets__.json')
  .then(response => response.ok ? response.json() : {})
  .catch(() => ({}));
if (effectsOnly) {
  document.documentElement.style.background = 'transparent';
  document.body.style.background = 'transparent';
}
canvas.width = tileWidth;
canvas.height = tileHeight * requestedTimes.length;
const renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: effectsOnly});
renderer.setPixelRatio(1);
renderer.setSize(canvas.width, canvas.height, false);
renderer.setScissorTest(true);
renderer.autoClear = false;
renderer.setClearColor(effectsOnly ? 0x000000 : 0x20242b, effectsOnly ? 0 : 1);

const scene = new THREE.Scene();
function walk(node, visit, parentPosition = [0, 0, 0], parentSize = [0, 0, 0], parentVelocity = [0, 0, 0]) {
  let position = parentPosition;
  let size = parentSize;
  let velocity = parentVelocity;
  if (node.className === 'Part' || node.className === 'MeshPart' || node.className === 'Camera') {
    const cf = node.props?.CFrame;
    if (cf) position = [Number(cf.X), Number(cf.Y), Number(cf.Z)];
    if (node.className !== 'Camera') size = dimensions(node.props?.Size);
    const pv = node.props?.AssemblyLinearVelocity;
    if (pv) velocity = [Number(pv.X ?? 0), Number(pv.Y ?? 0), Number(pv.Z ?? 0)];
  }
  if (node.className === 'Attachment') {
    const p = node.props?.Position;
    if (p) position = [position[0] + Number(p.X), position[1] + Number(p.Y), position[2] + Number(p.Z)];
  }
  visit(node, position, size, velocity);
  for (const child of Object.values(node.children || {})) walk(child, visit, position, size, velocity);
}
function findCamera(roots) {
  let fallback = null;
  let current = null;
  for (const root of roots) {
    walk(root, node => {
      if (node.className !== 'Camera') return;
      if (!fallback) fallback = node;
      if (!current && node.name === 'CurrentCamera' && root.className === 'Workspace') current = node;
    });
  }
  return current || fallback;
}

function parseVectorParam(name) {
  const raw = params.get(name);
  if (!raw) return null;
  const values = raw.split(',').map(Number);
  if (values.length !== 3 || values.some(value => !Number.isFinite(value))) {
    throw new Error(`invalid ${name} vector: ${raw}`);
  }
  return new THREE.Vector3(...values);
}
function cframeMatrix(cf) {
  return new THREE.Matrix4().set(
    cf.R00, cf.R01, cf.R02, cf.X,
    cf.R10, cf.R11, cf.R12, cf.Y,
    cf.R20, cf.R21, cf.R22, cf.Z,
    0, 0, 0, 1,
  );
}
function colorValue(value) {
  return new THREE.Color(Number(value?.R ?? 1), Number(value?.G ?? 1), Number(value?.B ?? 1));
}
function dimensions(value) {
  return [Number(value?.X ?? 1), Number(value?.Y ?? 1), Number(value?.Z ?? 1)];
}
function contentAssetId(uri) {
  const text = String(uri || '');
  const direct = text.match(/rbxassetid:\/\/(\d+)/i) || text.match(/[?&]id=(\d+)/i);
  if (direct) return direct[1];
  const matches = [...text.matchAll(/(\d+)/g)];
  return matches.length ? matches.at(-1)[1] : null;
}

async function loadParticleTexture(uri) {
  const assetId = contentAssetId(uri);
  if (!assetId) return null;
  if (particleTextureCache.has(assetId)) return particleTextureCache.get(assetId);
  const promise = (async () => {
    const manifest = await particleAssetManifest;
    const url = manifest[assetId];
    if (!url) return null;
    const loader = new THREE.TextureLoader();
    return await new Promise(resolve => loader.load(url, resolve, undefined, () => resolve(null)));
  })();
  particleTextureCache.set(assetId, promise);
  return promise;
}
function atlasMap(texture, frame) {
  if (!texture || !frame || frame.columns <= 1 && frame.rows <= 1) return texture;
  const map = texture.clone();
  map.repeat.set(1 / frame.columns, 1 / frame.rows);
  const column = frame.index % frame.columns;
  const row = Math.floor(frame.index / frame.columns);
  map.offset.set(column / frame.columns, 1 - (row + 1) / frame.rows);
  map.needsUpdate = true;
  return map;
}
function addSceneNode(node, parent) {
  const group = node.className === 'Model' ? new THREE.Group() : parent;
  if (group !== parent) parent.add(group);
  if (['Part', 'WedgePart', 'CornerWedgePart', 'MeshPart', 'UnionOperation'].includes(node.className)) {
    const cf = node.props?.CFrame;
    if (cf) {
      const [x, y, z] = dimensions(node.props?.Size);
      const mesh = new THREE.Mesh(
        new THREE.BoxGeometry(x, y, z),
        new THREE.MeshBasicMaterial({color: colorValue(node.props?.Color), transparent: true, opacity: Math.max(0, 1 - Number(node.props?.Transparency ?? 0))}),
      );
      mesh.matrixAutoUpdate = false;
      mesh.matrix.copy(cframeMatrix(cf));
      mesh.matrixWorldNeedsUpdate = true;
      group.add(mesh);
    }
  }
  for (const child of Object.values(node.children || {})) addSceneNode(child, group);
}
function configureCamera(camera, node) {
  if (node?.props?.CFrame) {
    const matrix = cframeMatrix(node.props.CFrame);
    matrix.decompose(camera.position, camera.quaternion, camera.scale);
  } else {
    camera.position.set(0, 4, 14);
    camera.lookAt(0, 1, 0);
  }
  const requestedFov = Number(params.get('fov'));
  camera.fov = Number.isFinite(requestedFov) && requestedFov > 1 && requestedFov < 179
    ? requestedFov
    : Number(node?.props?.FieldOfView ?? 70);
  const cameraOverride = parseVectorParam('camera');
  const lookAtOverride = parseVectorParam('lookAt');
  const quaternionRaw = params.get('cameraQuaternion');
  let quaternionOverride = null;
  if (quaternionRaw) {
    const values = quaternionRaw.split(',').map(Number);
    if (values.length !== 4 || values.some(value => !Number.isFinite(value))) {
      throw new Error(`invalid cameraQuaternion: ${quaternionRaw}`);
    }
    quaternionOverride = new THREE.Quaternion(...values).normalize();
  }
  if (cameraOverride) camera.position.copy(cameraOverride);
  if (quaternionOverride) camera.quaternion.copy(quaternionOverride);
  else if (lookAtOverride) camera.lookAt(lookAtOverride);
  camera.near = 0.05;
  camera.far = 10000;
  camera.updateMatrixWorld(true);
}

async function main() {
  const response = await fetch(params.get('ir') || '/__rhr_ir__.json');
  if (!response.ok) throw new Error(`IR request failed: ${response.status}`);
  const ir = await response.json();
  if (!effectsOnly) {
    for (const root of ir.roots || []) addSceneNode(root, scene);
  }
  const camera = new THREE.PerspectiveCamera();
  configureCamera(camera, findCamera(ir.roots || []));
  const cameraForward = camera.getWorldDirection(new THREE.Vector3());
  const cameraRight = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0).normalize();
  const cameraUp = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1).normalize();
  const emitters = [];
  for (const root of ir.roots || []) {
    walk(root, (node, position, size, parentVelocity) => {
      if (node.className === 'ParticleEmitter') {
        emitters.push({props: node.props || {}, texture: null, frames: simulateEmitter(node.props || {}, {duration: maxTime, dt: 1 / 60, seed, burst, origin: position, emitterSize: size, parentVelocity}), position});
      }
    });
  }
  for (const emitter of emitters) emitter.texture = await loadParticleTexture(emitter.props.Texture);
  const counts = [];
  for (let frameIndex = 0; frameIndex < requestedTimes.length; frameIndex += 1) {
    const time = Math.max(0, requestedTimes[frameIndex]);
    const group = new THREE.Group();
    let count = 0;
    for (const emitter of emitters) {
      const index = Math.min(emitter.frames.length - 1, Math.round(time * 60));
      for (const particle of emitter.frames[index]?.particles || []) {
        const localTransparency = Math.max(0, Math.min(1, Number(emitter.props.LocalTransparencyModifier ?? 0)));
        const transparency = applyLocalTransparency(particle.transparency, localTransparency);
        if (particle.size <= 0 || transparency >= 1) continue;
        const map = atlasMap(emitter.texture, particle.frame);
        const lightEmission = Math.max(0, Math.min(1, Number(emitter.props.LightEmission ?? 0)));
        const brightness = Math.max(0, Number(emitter.props.Brightness ?? 1));
        const color = new THREE.Color(...particle.color).multiplyScalar(brightness);
        const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
          map,
          color,
          opacity: Math.max(0, 1 - transparency),
          transparent: true,
          depthWrite: false,
          blending: lightEmission > 0 ? THREE.AdditiveBlending : THREE.NormalBlending,
        }));
        sprite.position.set(...particle.position);
        const zOffset = Number(emitter.props.ZOffset ?? 0);
        sprite.position.addScaledVector(cameraForward, -zOffset);
        const squash = Number(particle.squash || 0);
        const vertical = Math.max(0.05, 1 + squash);
        const horizontal = Math.max(0.05, 1 / vertical);
        sprite.scale.set(particle.size * horizontal, particle.size * vertical, 1);
        let rotation = Number(particle.rotation || 0) * Math.PI / 180;
        const orientation = emitter.props.Orientation?.name;
        if (orientation === 'VelocityParallel' || orientation === 'VelocityPerpendicular') {
          const velocity = new THREE.Vector3(...(particle.velocity || [0, 0, 0]));
          const screenX = velocity.dot(cameraRight);
          const screenY = velocity.dot(cameraUp);
          if (Math.hypot(screenX, screenY) > 1e-9) {
            rotation += Math.atan2(screenY, screenX) - Math.PI / 2;
            if (orientation === 'VelocityPerpendicular') rotation += Math.PI / 2;
          }
        }
        sprite.material.rotation = rotation;
        group.add(sprite);
        count += 1;
      }
    }
    scene.add(group);
    camera.aspect = tileWidth / tileHeight;
    camera.updateProjectionMatrix();
    const y = (requestedTimes.length - frameIndex - 1) * tileHeight;
    renderer.setViewport(0, y, tileWidth, tileHeight);
    renderer.setScissor(0, y, tileWidth, tileHeight);
    renderer.clear(true, true, true);
    renderer.render(scene, camera);
    renderer.render(scene, camera);
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    scene.remove(group);
    for (const child of group.children) child.material.dispose();
    counts.push(count);
  }
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  document.documentElement.dataset.rhrCounts = counts.join(',');
  document.documentElement.dataset.rhrReady = 'true';
}

try {
  await main();
} catch (error) {
  document.documentElement.dataset.rhrError = String(error);
  throw error;
}
