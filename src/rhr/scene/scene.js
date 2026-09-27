import * as THREE from '../vendor/three/three.module.js';
import { SunLight } from '../vendor/three/lights/SunLight.js';
import { flipbookLayout, hashSeed, particleLook, playEmitter, playHorizon, playSchedule, sampleNumberSequence } from '../particles/sim.js';

// The page draws one scene per load, or, in the warm worker, one per rhrRender() call
// on a page that stays loaded (scripts, compiled shaders and decoded textures are kept;
// everything about the scene is reset). `persistent=1` in the address picks the second.
const pageParams = new URLSearchParams(location.search);
const persistentPage = pageParams.get('persistent') === '1';
let params = pageParams;

// Data (the IR, images, meshes, notes) comes from the command's own local server. On a
// persistent page that is another address for every render: `/__rhr_...` paths are
// sent there, for fetch() and for three.js's loaders alike.
let dataBase = '';
const dataUrl = url => (typeof url === 'string' && url.startsWith('/__rhr_') ? dataBase + url : url);
const nativeFetch = window.fetch.bind(window);
window.fetch = (url, options) => nativeFetch(dataUrl(url), options);
THREE.DefaultLoadingManager.setURLModifier(dataUrl);

// RHR_PROFILE: how long each step of the page takes, sent back when it is ready.
let profiling = params.get('profile') === '1';
let pageMarks = [];
let lastMark = 0;
function mark(name) {
  if (!profiling) return;
  const now = performance.now();
  pageMarks.push([name, now - lastMark]);
  lastMark = now;
}
mark('scripts loaded and parsed');
const viewportMode = pageParams.get('mode') === 'viewport';  // never on a persistent page
const canvas = document.querySelector('#rhr-scene');
if (viewportMode) document.body.style.background = 'transparent';
let width = Math.max(1, window.innerWidth);
let height = Math.max(1, window.innerHeight);
const renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: viewportMode, stencil: true});
renderer.setPixelRatio(1);
renderer.setSize(width, height, false);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.shadowMap.type = THREE.PCFShadowMap;
renderer.setClearColor(viewportMode ? 0x000000 : 0x20242b, viewportMode ? 0 : 1);
// Constants fitted against Studio (see configureAtmosphere, configureModernEnvironment).
// The `tune` query parameter (JSON, from RHR_SCENE_TUNE) overrides them while
// calibrating; normal renders never set it.
const TUNE_DEFAULTS = {
  sunK: 1.625, skyK: 1.175, ambK: 0.1, skyBg: 1.0375, fogL: 1.0, fogDecayMix: 0.4375,
  exposure: 1.475, tone: 3, sunR: 1.0, sunG: 0.965, sunB: 0.91, pRough: 0.72, spRough: 0.33, aoK: 1.0, aoReach: 64,
  tBlendH: 0.4, tBlendD: 0.35, tBlendN: 0.25,
  gDensity: 1.0, gMin: 1.8, gMax: 3.6, gLean: 60, gBend: 0, gMargin: 0.15, gWidth: 0.5, gShadeR: 0.30, gShadeG: 0.33, gShadeB: 0.13,
  rGain: 2.5, rW0: 2, rW1: 30, rDensity: 0.9, rDecay: 0.9825, rVeil: 1.15, rSpread: -1, rK: 1.0, rLeak: 0.075, rVeilW: 1.3,
  sunScale: 1.16, sunGain: 0.7, sunBlur: 3.0,
  cTile: 4200, cHeight: 900, cOct: 0.4, cLod: 0.5, cHaze: 0.25, cDensPow: 1.7, cCurve: 0.0004, cEdge: 0.007, cCov0: 0.48, cCov1: 1.4, cSoft: 0.08, cOpacity: 4.0, cBright: 0.87, cCore: 0.68, cDark: 0.64, cCover: -1, cDensity: -1,
  gNear: 40, gFar: 200, gCarpet: 0.75, gCarpetNear: 20, gCarpetFar: 150, gOn: 1,
};
let TUNE = {...TUNE_DEFAULTS};
let shadowsRequested = true;
let flatMaterials = false;

let scene = new THREE.Scene();
const meshByNode = new Map();
const anchorByNode = new Map();
const sceneTextureCache = new Map();
const sceneMeshGeometryCache = new Map();
const meshGeometryJobs = [];
const materialTextureJobs = [];
const jsonOrEmpty = url => fetch(url).then(response => (response.ok ? response.json() : {})).catch(() => ({}));
let sceneAssetManifest = null;
let sceneMeshManifest = null;
let extrasManifest = null;
let robloxMaterialTable = null;
let materialCredits = null;

// What survives between renders on a persistent page, keyed by a file's address and
// version (the server adds `?v=<size>-<mtime>`), so a changed file is read again:
// decoded images and parsed meshes.
const keptLoads = new Map();
function keep(kind, url, load) {
  const key = `${kind}|${url}`;
  if (!keptLoads.has(key)) {
    const promise = load();
    keptLoads.set(key, promise);
    promise.then(value => { if (value == null) keptLoads.delete(key); }, () => keptLoads.delete(key));
  }
  return keptLoads.get(key);
}

function configure(query) {
  params = new URLSearchParams(query);
  profiling = params.get('profile') === '1';
  pageMarks = [];
  lastMark = performance.now();
  TUNE = Object.assign({...TUNE_DEFAULTS}, (() => { try { return JSON.parse(params.get('tune') || '{}'); } catch (_) { return {}; } })());
  // Shadows are on unless the caller turns them off (Studio draws them by default).
  shadowsRequested = !viewportMode && params.get('shadows') !== '0';
  renderer.shadowMap.enabled = shadowsRequested;
  flatMaterials = params.get('flatMaterials') === '1';
  sceneAssetManifest = jsonOrEmpty('/__rhr_assets__.json');
  sceneMeshManifest = jsonOrEmpty('/__rhr_meshes__.json');
  extrasManifest = jsonOrEmpty('/__rhr_extras__.json');
  robloxMaterialTable = flatMaterials
    ? Promise.resolve(null)
    : fetch('./roblox_materials.json').then(r => (r.ok ? r.json() : null)).catch(() => null);
  materialCredits = flatMaterials
    ? Promise.resolve({})
    : fetch('./materials/credits.json').then(r => (r.ok ? r.json() : {})).then(j => j.materials || {}).catch(() => ({}));
}
configure(location.search);

function walk(node, visit) {
  visit(node);
  for (const child of Object.values(node.children || {})) walk(child, visit);
}

// Paths come from the IR (unique: same-named siblings are all indexed, `Card[1]`,
// `Card[2]`); hand-written IR without them gets the same rule here.
function ensurePaths(nodes, parentPath = '') {
  const segment = node => node.name || node.className;
  const counts = new Map();
  for (const node of nodes) counts.set(segment(node), (counts.get(segment(node)) || 0) + 1);
  const seen = new Map();
  for (const node of nodes) {
    if (!node.path) {
      const name = segment(node);
      let part = name;
      if (counts.get(name) > 1) {
        seen.set(name, (seen.get(name) || 0) + 1);
        part = `${name}[${seen.get(name)}]`;
      }
      node.path = parentPath ? `${parentPath}/${part}` : part;
    }
    ensurePaths(Object.values(node.children || {}), node.path);
  }
}

function buildNodeIndex(roots) {
  const byPath = new Map();
  const byId = new Map();
  const byReference = new Map();
  const ambiguousReferences = new Set();
  const byClass = new Map();
  const parentByNode = new Map();
  const rootByNode = new Map();

  ensurePaths(roots);
  function descend(node, parent, referencePath, root) {
    byPath.set(node.path, node);
    if (node.id !== undefined) byId.set(node.id, node);
    // GetFullName() strings are only a fallback for IR without ids; a dotted name
    // shared by two instances resolves to nothing rather than to either one.
    if (byReference.has(referencePath)) ambiguousReferences.add(referencePath);
    else byReference.set(referencePath, node);
    if (!byClass.has(node.className)) byClass.set(node.className, []);
    byClass.get(node.className).push(node);
    if (parent) parentByNode.set(node, parent);
    rootByNode.set(node, root);
    for (const child of Object.values(node.children || {})) {
      descend(child, node, `${referencePath}.${child.name || child.className}`, root);
    }
  }

  for (const root of roots) {
    descend(root, null, root.name || root.className, root);
  }
  return {byPath, byId, byReference, ambiguousReferences, byClass, parentByNode, rootByNode};
}

function nodesOfClass(index, className) {
  return index.byClass.get(className) || [];
}

function cframeMatrix(cf) {
  return new THREE.Matrix4().set(
    cf.R00, cf.R01, cf.R02, cf.X,
    cf.R10, cf.R11, cf.R12, cf.Y,
    cf.R20, cf.R21, cf.R22, cf.Z,
    0, 0, 0, 1,
  );
}

// Roblox Color3 components are sRGB. THREE.Color(r, g, b) takes working-space
// (linear) values, which washed every authored colour out; convert explicitly.
function colorValue(value, fallback = 0xffffff) {
  if (!value) return new THREE.Color(fallback);
  return new THREE.Color().setRGB(Number(value.R ?? 1), Number(value.G ?? 1), Number(value.B ?? 1), THREE.SRGBColorSpace);
}

function dimensions(value) {
  return [Number(value?.X ?? 1), Number(value?.Y ?? 1), Number(value?.Z ?? 1)];
}

// Studio-measured (raycasts onto a WedgePart): the top face slopes along local Z,
// low at the front (-Z) and full height at the back (+Z).
function wedgeGeometry(width, height, depth) {
  const geometry = new THREE.BoxGeometry(width, height, depth);
  const position = geometry.attributes.position;
  for (let index = 0; index < position.count; index += 1) {
    if (position.getZ(index) < 0) position.setY(index, -height / 2);
  }
  position.needsUpdate = true;
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  return geometry;
}

function cornerWedgeGeometry(width, height, depth) {
  const geometry = new THREE.BoxGeometry(width, height, depth);
  const position = geometry.attributes.position;
  for (let index = 0; index < position.count; index += 1) {
    // Studio-measured: the peak stands over the (+X, -Z) corner; every other top
    // vertex drops to the base.
    if (position.getY(index) > 0 && !(position.getX(index) > 0 && position.getZ(index) < 0)) {
      position.setY(index, -height / 2);
    }
  }
  position.needsUpdate = true;
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  return geometry;
}

function specialMeshChild(node) {
  return Object.values(node.children || {}).find(child => child.className === 'SpecialMesh') || null;
}

function contentAssetId(uri) {
  const text = String(uri || '');
  const direct = text.match(/rbxassetid:\/\/(\d+)/i) || text.match(/[?&]id=(\d+)/i);
  if (direct) return direct[1];
  const matches = [...text.matchAll(/(\d+)/g)];
  return matches.length ? matches.at(-1)[1] : null;
}

function meshAssetId(uri) {
  return contentAssetId(uri);
}

// A file the Roblox client ships with (rbxasset://textures/face.png), served from the
// Studio install: its key in the extras manifest, as rhr.studio.content_path spells it.
function contentKey(uri) {
  const text = String(uri || '').trim();
  if (!/^rbxasset:\/\//i.test(text)) return null;
  const key = text.slice(11).replace(/\\/g, '/').replace(/^\/+/, '').toLowerCase();
  return key || null;
}

async function contentUrl(uri) {
  const key = contentKey(uri);
  if (!key) return null;
  return (await extrasManifest).content?.[key] || null;
}

function dataViewString(bytes, start, end) {
  return new TextDecoder().decode(bytes.slice(start, end));
}

function meshVersionAndOffset(bytes) {
  let end = 0;
  while (end < bytes.length && bytes[end] !== 10) end += 1;
  if (end >= bytes.length) throw new Error('mesh asset is missing a version line');
  const version = dataViewString(bytes, 0, end).replace(/\r$/, '').trim();
  return {version, offset: end + 1};
}

function geometryFromExpanded(vertices, normals, uvs) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
  if (normals.length === vertices.length) {
    geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
  }
  if (uvs.length * 3 === vertices.length * 2) {
    geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  }
  if (!geometry.attributes.normal) geometry.computeVertexNormals();
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  return geometry;
}

// Text meshes (1.00 is in half-studs). Unlike binary meshes they keep V from the
// bottom (Studio: old hats with 1.00 meshes, an R6 body package's 1.01 meshes).
function parseMeshV1(bytes, offset, version) {
  const text = dataViewString(bytes, offset, bytes.length);
  const lines = text.split(/\r?\n/);
  const faceCount = Number(lines.shift()?.trim());
  if (!Number.isFinite(faceCount) || faceCount <= 0) throw new Error('invalid v1 mesh face count');
  const vectors = [...lines.join('').matchAll(/\[\s*([^\]]+)\]/g)].map(match =>
    match[1].split(',').map(Number)
  );
  if (vectors.length < faceCount * 9) throw new Error('truncated v1 mesh vertex data');
  const positions = [];
  const normals = [];
  const uvs = [];
  for (let face = 0; face < faceCount; face += 1) {
    for (let corner = 0; corner < 3; corner += 1) {
      const base = face * 9 + corner * 3;
      const p = vectors[base];
      const n = vectors[base + 1];
      const uv = vectors[base + 2];
      const positionScale = version === 'version 1.00' ? 0.5 : 1;
      positions.push(
        Number(p[0]) * positionScale,
        Number(p[1]) * positionScale,
        Number(p[2]) * positionScale,
      );
      normals.push(Number(n[0]), Number(n[1]), Number(n[2]));
      uvs.push(Number(uv[0]), Number(uv[1]));
    }
  }
  return geometryFromExpanded(positions, normals, uvs);
}

function readBinaryVertices(view, vertexOffset, vertexSize, vertexCount) {
  if (vertexSize < 32) throw new Error(`unsupported mesh vertex size ${vertexSize}`);
  const positions = new Float32Array(vertexCount * 3);
  const normals = new Float32Array(vertexCount * 3);
  const uvs = new Float32Array(vertexCount * 2);
  for (let i = 0; i < vertexCount; i += 1) {
    const base = vertexOffset + i * vertexSize;
    if (base + vertexSize > view.byteLength) throw new Error('truncated mesh vertex data');
    positions[i * 3] = view.getFloat32(base, true);
    positions[i * 3 + 1] = view.getFloat32(base + 4, true);
    positions[i * 3 + 2] = view.getFloat32(base + 8, true);
    normals[i * 3] = view.getFloat32(base + 12, true);
    normals[i * 3 + 1] = view.getFloat32(base + 16, true);
    normals[i * 3 + 2] = view.getFloat32(base + 20, true);
    uvs[i * 2] = view.getFloat32(base + 24, true);
    uvs[i * 2 + 1] = 1 - view.getFloat32(base + 28, true);
  }
  return {positions, normals, uvs};
}

function geometryFromBinary(bytes, headerOffset, spec) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const vertexOffset = headerOffset + spec.headerSize;
  const skinningBytes = spec.skinningBytes || 0;
  const faceOffset = vertexOffset + spec.vertexSize * spec.vertexCount + skinningBytes;
  if (faceOffset + spec.faceCount * spec.faceSize > view.byteLength) {
    throw new Error('truncated mesh face data');
  }
  const attrs = readBinaryVertices(view, vertexOffset, spec.vertexSize, spec.vertexCount);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(attrs.positions, 3));
  geometry.setAttribute('normal', new THREE.BufferAttribute(attrs.normals, 3));
  geometry.setAttribute('uv', new THREE.BufferAttribute(attrs.uvs, 2));
  // Meshes from version 3 on list every level of detail's faces one after another,
  // with the offsets after the faces; only the most detailed level is drawn.
  let firstFace = 0;
  let lastFace = spec.faceCount;
  const lodOffset = faceOffset + spec.faceCount * spec.faceSize;
  if (spec.lodCount >= 2 && lodOffset + spec.lodCount * 4 <= view.byteLength) {
    const start = view.getUint32(lodOffset, true);
    const end = view.getUint32(lodOffset + 4, true);
    if (start < end && end <= spec.faceCount) {
      firstFace = start;
      lastFace = end;
    }
  }
  const indices = new Uint32Array((lastFace - firstFace) * 3);
  for (let i = firstFace; i < lastFace; i += 1) {
    const base = faceOffset + i * spec.faceSize;
    const k = (i - firstFace) * 3;
    indices[k] = view.getUint32(base, true);
    indices[k + 1] = view.getUint32(base + 4, true);
    indices[k + 2] = view.getUint32(base + 8, true);
  }
  geometry.setIndex(new THREE.BufferAttribute(indices, 1));
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  return geometry;
}

function parseMeshV2(bytes, offset) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const headerSize = view.getUint16(offset, true);
  const vertexSize = view.getUint8(offset + 2);
  const faceSize = view.getUint8(offset + 3);
  const vertexCount = view.getUint32(offset + 4, true);
  const faceCount = view.getUint32(offset + 8, true);
  return geometryFromBinary(bytes, offset, {
    headerSize, vertexSize, faceSize, vertexCount, faceCount,
  });
}

function parseMeshV3(bytes, offset) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const headerSize = view.getUint16(offset, true);
  const vertexSize = view.getUint8(offset + 2);
  const faceSize = view.getUint8(offset + 3);
  if (headerSize < 16) throw new Error(`unsupported v3 mesh header size ${headerSize}`);
  const lodCount = view.getUint16(offset + 6, true);
  const vertexCount = view.getUint32(offset + 8, true);
  const faceCount = view.getUint32(offset + 12, true);
  return geometryFromBinary(bytes, offset, {
    headerSize, vertexSize, faceSize, vertexCount, faceCount, lodCount,
  });
}

function parseMeshV4(bytes, offset) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const headerSize = view.getUint16(offset, true);
  const vertexCount = view.getUint32(offset + 4, true);
  const faceCount = view.getUint32(offset + 8, true);
  const lodCount = view.getUint16(offset + 12, true);
  const boneCount = view.getUint16(offset + 14, true);
  return geometryFromBinary(bytes, offset, {
    headerSize,
    vertexSize: 40,
    faceSize: 12,
    vertexCount,
    faceCount,
    lodCount,
    skinningBytes: boneCount > 0 ? vertexCount * 8 : 0,
  });
}

// Google's Draco decoder (vendor/draco, Apache-2.0), for version 7 meshes.
let dracoModule = null;
function loadDraco() {
  if (!dracoModule) {
    dracoModule = (async () => {
      await new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = '../vendor/draco/draco_wasm_wrapper.js';
        script.onload = resolve;
        script.onerror = () => reject(new Error('could not load the Draco decoder'));
        document.head.appendChild(script);
      });
      const wasmBinary = await (await fetch('../vendor/draco/draco_decoder.wasm')).arrayBuffer();
      // DracoDecoderModule is the global the wrapper script defines.
      return new Promise(resolve => window.DracoDecoderModule({wasmBinary, onModuleLoaded: resolve}));
    })();
  }
  return dracoModule;
}

async function decodeDraco(bytes) {
  const draco = await loadDraco();
  const decoder = new draco.Decoder();
  const mesh = new draco.Mesh();
  try {
    const input = new Int8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const status = decoder.DecodeArrayToMesh(input, bytes.byteLength, mesh);
    if (!status.ok() || mesh.ptr === 0) throw new Error(`Draco: ${status.error_msg()}`);
    const points = mesh.num_points();
    const attributes = [];
    for (let i = 0; i < mesh.num_attributes(); i += 1) {
      const attribute = decoder.GetAttribute(mesh, i);
      const components = attribute.num_components();
      const float = attribute.data_type() === draco.DT_FLOAT32;
      const length = points * components;
      const byteLength = length * (float ? 4 : 1);
      const ptr = draco._malloc(byteLength);
      decoder.GetAttributeDataArrayForAllPoints(mesh, attribute, float ? draco.DT_FLOAT32 : draco.DT_UINT8, byteLength, ptr);
      const values = float
        ? new Float32Array(draco.HEAPF32.buffer, ptr, length).slice()
        : new Uint8Array(draco.HEAPU8.buffer, ptr, length).slice();
      draco._free(ptr);
      attributes.push({components, float, values});
    }
    const faces = mesh.num_faces();
    const indexBytes = faces * 12;
    const ptr = draco._malloc(indexBytes);
    decoder.GetTrianglesUInt32Array(mesh, indexBytes, ptr);
    const indices = new Uint32Array(draco.HEAPU32.buffer, ptr, faces * 3).slice();
    draco._free(ptr);
    return {points, attributes, indices};
  } finally {
    draco.destroy(mesh);
    draco.destroy(decoder);
  }
}

// Version 6 and 7 meshes are a list of chunks: an 8-byte name, a u32 version, a u32
// size and the data. COREMESH holds the geometry (version 1: 40-byte vertices then
// faces; version 2: a Draco bitstream whose float attributes are position, normal
// and uv), LODS the first face of each level of detail.
async function parseMeshChunks(bytes, offset) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const chunks = {};
  while (offset + 16 <= bytes.length) {
    const name = dataViewString(bytes, offset, offset + 8).split('\u0000')[0];
    const version = view.getUint32(offset + 8, true);
    const size = view.getUint32(offset + 12, true);
    offset += 16;
    if (offset + size > bytes.length) throw new Error(`truncated ${name} mesh chunk`);
    chunks[name] = {version, data: bytes.subarray(offset, offset + size)};
    offset += size;
  }
  const core = chunks.COREMESH;
  if (!core) throw new Error('mesh has no COREMESH chunk');
  let positions;
  let normals = null;
  let uvs = null;
  let indices;
  const coreView = new DataView(core.data.buffer, core.data.byteOffset, core.data.byteLength);
  if (core.version === 1) {
    const count = coreView.getUint32(0, true);
    const attrs = readBinaryVertices(coreView, 4, 40, count);
    positions = attrs.positions;
    normals = attrs.normals;
    uvs = attrs.uvs;
    const faceStart = 8 + count * 40;
    const faceCount = coreView.getUint32(4 + count * 40, true);
    indices = new Uint32Array(faceCount * 3);
    for (let i = 0; i < faceCount * 3; i += 1) indices[i] = coreView.getUint32(faceStart + i * 4, true);
  } else if (core.version === 2) {
    const size = coreView.getUint32(0, true);
    const decoded = await decodeDraco(core.data.subarray(4, 4 + size));
    const floats = decoded.attributes.filter(a => a.float);
    const vec3 = floats.filter(a => a.components === 3);
    positions = vec3[0]?.values;
    normals = vec3[1]?.values || null;
    const uv = floats.find(a => a.components === 2)?.values;
    if (uv) {
      uvs = new Float32Array(uv.length);
      for (let i = 0; i < uv.length; i += 2) {
        uvs[i] = uv[i];
        uvs[i + 1] = 1 - uv[i + 1];
      }
    }
    indices = decoded.indices;
  } else {
    throw new Error(`unsupported COREMESH version ${core.version}`);
  }
  if (!positions) throw new Error('mesh has no positions');
  const lods = chunks.LODS;
  if (lods && lods.data.length >= 7) {
    const lodView = new DataView(lods.data.buffer, lods.data.byteOffset, lods.data.byteLength);
    const count = lodView.getUint32(3, true);
    if (count >= 2 && 7 + count * 4 <= lods.data.length) {
      const start = lodView.getUint32(7, true);
      const end = lodView.getUint32(11, true);
      if (start < end && end * 3 <= indices.length) indices = indices.slice(start * 3, end * 3);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  if (normals && normals.length === positions.length) geometry.setAttribute('normal', new THREE.BufferAttribute(normals, 3));
  if (uvs && uvs.length * 3 === positions.length * 2) geometry.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
  geometry.setIndex(new THREE.BufferAttribute(indices, 1));
  if (!geometry.attributes.normal) geometry.computeVertexNormals();
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  return geometry;
}


function parseRobloxMesh(buffer) {
  const bytes = new Uint8Array(buffer);
  const {version, offset} = meshVersionAndOffset(bytes);
  if (version === 'version 1.00' || version === 'version 1.01') return parseMeshV1(bytes, offset, version);
  if (version.startsWith('version 2.')) return parseMeshV2(bytes, offset);
  if (version.startsWith('version 3.')) return parseMeshV3(bytes, offset);
  if (version.startsWith('version 4.') || version.startsWith('version 5.')) return parseMeshV4(bytes, offset);
  if (version.startsWith('version 6.') || version.startsWith('version 7.')) return parseMeshChunks(bytes, offset);
  throw new Error(`unsupported Roblox mesh ${version}`);
}

const meshParseFailures = [];

// Some uploaded meshes carry a stray vertex that is not a number (Roblox does not
// mind). One is enough to make the bounds, and so the framed camera, NaN: move any
// such vertex to the mesh's origin.
function withoutBadVertices(geometry) {
  const position = geometry?.getAttribute?.('position');
  if (!position) return geometry;
  const array = position.array;
  let fixed = false;
  for (let i = 0; i < array.length; i += 3) {
    if (!Number.isFinite(array[i]) || !Number.isFinite(array[i + 1]) || !Number.isFinite(array[i + 2])) {
      array[i] = array[i + 1] = array[i + 2] = 0;
      fixed = true;
    }
  }
  if (fixed) {
    position.needsUpdate = true;
    geometry.computeBoundingBox();
    geometry.computeBoundingSphere();
  }
  return geometry;
}

async function loadMeshGeometry(uri) {
  const content = contentKey(uri);
  const assetId = content ? `content:${content}` : meshAssetId(uri);
  if (!assetId) return null;
  if (sceneMeshGeometryCache.has(assetId)) return sceneMeshGeometryCache.get(assetId);
  const promise = (async () => {
    const url = content ? await contentUrl(uri) : (await sceneMeshManifest)[assetId];
    if (!url) return null;
    return keep('mesh', url, async () => {
      const response = await fetch(url);
      if (!response.ok) return null;
      const geometry = withoutBadVertices(await parseRobloxMesh(await response.arrayBuffer()));
      // Material textures replace `uv` with stud-sized box UVs; the mesh's own UVs,
      // which its TextureID and a character's clothing are drawn with, stay in uv1.
      if (geometry?.attributes.uv && !geometry.attributes.uv1) geometry.setAttribute('uv1', geometry.attributes.uv);
      return geometry;
    });
  })().catch(error => {
    meshParseFailures.push(`${assetId}: ${error.message}`);
    return null;
  });
  sceneMeshGeometryCache.set(assetId, promise);
  return promise;
}

function fitMeshGeometryToPart(baseGeometry, size) {
  const geometry = baseGeometry.clone();
  geometry.computeBoundingBox();
  const box = geometry.boundingBox;
  if (!box) return geometry;
  const rawSize = box.getSize(new THREE.Vector3());
  const [sx, sy, sz] = dimensions(size);
  geometry.scale(
    sx / Math.max(1e-9, rawSize.x),
    sy / Math.max(1e-9, rawSize.y),
    sz / Math.max(1e-9, rawSize.z),
  );
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  return geometry;
}

// Studio-measured (a front view against a 1-stud block): a SpecialMesh of MeshType Head
// is 0.935 of the part's smaller horizontal side across (X and Z) and 0.935 of its
// height tall, times the mesh's Scale. An R6 head (2x1x1, Scale 1.25) is 1.17 studs.
const HEAD_MESH = 'rbxasset://avatar/heads/head.mesh';
function headMeshSize(node, special) {
  const [x, y, z] = dimensions(node.props?.Size);
  const scale = special.props?.Scale || {};
  const across = Math.min(x, z) * 0.935;
  return {X: across * Number(scale.X ?? 1), Y: y * 0.935 * Number(scale.Y ?? 1), Z: across * Number(scale.Z ?? 1)};
}

function transformSpecialFileMesh(baseGeometry, special) {
  const geometry = baseGeometry.clone();
  const scale = special.props?.Scale || {};
  geometry.scale(
    Number(scale.X ?? 1),
    Number(scale.Y ?? 1),
    Number(scale.Z ?? 1),
  );
  const offset = special.props?.Offset || {};
  geometry.translate(
    Number(offset.X ?? 0),
    Number(offset.Y ?? 0),
    Number(offset.Z ?? 0),
  );
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  return geometry;
}

function shapeGeometry(node) {
  let [x, y, z] = dimensions(node.props?.Size);
  const special = specialMeshChild(node);
  const meshType = special?.props?.MeshType?.name;
  if (special && meshType && meshType !== 'FileMesh') {
    const scale = special.props?.Scale || {};
    x *= Number(scale.X ?? 1);
    y *= Number(scale.Y ?? 1);
    z *= Number(scale.Z ?? 1);
    let geometry;
    if (meshType === 'Head') {
      // Until the install's head mesh loads (addPart), or without an install.
      const size = headMeshSize(node, special);
      geometry = new THREE.SphereGeometry(0.5, 24, 16);
      geometry.scale(size.X, size.Y, size.Z);
    } else if (meshType === 'Sphere') {
      geometry = new THREE.SphereGeometry(0.5, 24, 16);
      geometry.scale(x, y, z);
    } else if (meshType === 'Cylinder') {
      geometry = new THREE.CylinderGeometry(0.5, 0.5, 1, 24);
      geometry.scale(x, y, z);
    } else if (meshType === 'Wedge') {
      geometry = wedgeGeometry(x, y, z);
    } else {
      geometry = new THREE.BoxGeometry(x, y, z);
    }
    const offset = special.props?.Offset;
    if (offset) geometry.translate(Number(offset.X ?? 0), Number(offset.Y ?? 0), Number(offset.Z ?? 0));
    geometry.computeBoundingSphere();
    return geometry;
  }

  const shape = node.props?.Shape?.name || node.props?.shape;
  if (node.className === 'CornerWedgePart' || shape === 'CornerWedge') return cornerWedgeGeometry(x, y, z);
  if (node.className === 'WedgePart' || shape === 'Wedge') return wedgeGeometry(x, y, z);
  if (shape === 'Ball' || shape === '2') {
    const geometry = new THREE.SphereGeometry(0.5, 24, 16);
    geometry.scale(x, y, z);
    return geometry;
  }
  if (shape === 'Cylinder' || shape === '3') {
    // Roblox PartType.Cylinder uses the Part X axis as its long axis. THREE's
    // CylinderGeometry uses Y, so scale in the source axes then rotate Y -> X.
    const geometry = new THREE.CylinderGeometry(0.5, 0.5, 1, 24);
    geometry.scale(y, x, z);
    geometry.rotateZ(-Math.PI / 2);
    return geometry;
  }
  return new THREE.BoxGeometry(x, y, z);
}

const NEON_BRIGHTNESS = 3;
function neonBrightness(transparency) {
  const t = Math.max(0, Math.min(1, Number(transparency) || 0));
  return NEON_BRIGHTNESS * (1 - t * t);
}
const MATERIAL_TABLE = {
  Plastic: {roughness: TUNE.pRough, metalness: 0.0},
  SmoothPlastic: {roughness: TUNE.spRough, metalness: 0.0},
  // Neon is unlit and drawn about 3x brighter than its colour, clipped per channel
  // (Studio: orange turns yellow-orange, blue turns cyan); what passes white glows.
  Neon: {roughness: 0.9, metalness: 0.0, emissiveIntensity: NEON_BRIGHTNESS, unlit: true},
  Glass: {roughness: 0.12, metalness: 0.0, opacityScale: 0.72},
  // No environment map to reflect, so high metalness renders near-black; Studio's
  // metals read as their own colour with a sheen (screenshot comparison).
  Metal: {roughness: 0.38, metalness: 0.3},
  CorrodedMetal: {roughness: 0.9, metalness: 0.25},
  DiamondPlate: {roughness: 0.65, metalness: 0.3},
  Foil: {roughness: 0.25, metalness: 0.35},
  Wood: {roughness: 0.86, metalness: 0.0},
  WoodPlanks: {roughness: 0.88, metalness: 0.0},
  Concrete: {roughness: 0.96, metalness: 0.0},
  Brick: {roughness: 0.94, metalness: 0.0},
  Slate: {roughness: 0.82, metalness: 0.04},
  Granite: {roughness: 0.62, metalness: 0.08},
  Marble: {roughness: 0.32, metalness: 0.14},
  Pebble: {roughness: 0.96, metalness: 0.0},
  Cobblestone: {roughness: 0.98, metalness: 0.0},
  Ice: {roughness: 0.16, metalness: 0.0, opacityScale: 0.82},
  Fabric: {roughness: 1.0, metalness: 0.0},
  Grass: {roughness: 1.0, metalness: 0.0},
  LeafyGrass: {roughness: 1.0, metalness: 0.0},
  Ground: {roughness: 1.0, metalness: 0.0},
  Sand: {roughness: 1.0, metalness: 0.0},
  Snow: {roughness: 0.92, metalness: 0.0},
  Mud: {roughness: 1.0, metalness: 0.0},
  Rock: {roughness: 0.96, metalness: 0.02},
  Basalt: {roughness: 0.9, metalness: 0.04},
  CrackedLava: {roughness: 0.94, metalness: 0.0, emissiveIntensity: 0.35},
  Limestone: {roughness: 0.92, metalness: 0.0},
  Pavement: {roughness: 0.9, metalness: 0.0},
  Asphalt: {roughness: 0.96, metalness: 0.0},
  Salt: {roughness: 0.82, metalness: 0.0},
  Sandstone: {roughness: 0.94, metalness: 0.0},
  Glacier: {roughness: 0.2, metalness: 0.0, opacityScale: 0.9},
  ForceField: {roughness: 0.35, metalness: 0.0, opacityScale: 0.55, emissiveIntensity: 0.35},
  Cardboard: {roughness: 0.96, metalness: 0.0},
  Carpet: {roughness: 1.0, metalness: 0.0},
  CeramicTiles: {roughness: 0.32, metalness: 0.02},
  ClayRoofTiles: {roughness: 0.9, metalness: 0.0},
  Leather: {roughness: 0.72, metalness: 0.0},
  Plaster: {roughness: 0.96, metalness: 0.0},
  RoofShingles: {roughness: 0.94, metalness: 0.0},
  Rubber: {roughness: 0.92, metalness: 0.0},
};

// Roblox's own material textures. Roblox publishes the asset ids of every built-in
// material's colour, normal, roughness and metalness maps (roblox_materials.json,
// from its creator docs); `rhr fetch` / the render's own fetch step downloads them
// with the Studio login into the local cache, and /__rhr_extras__.json lists what is
// there. The colour map's alpha marks where the part's Color applies (Brick: the
// bricks take the colour, the mortar keeps its own), so the shader tints by it.
// MaterialService.Use2022Materials picks the current or the pre-2022 set.
//
// Without them (no Studio login, or --flat-materials off but nothing cached) the
// CC0 look-alikes below stand in: a greyscale detail tile the part's Color tints,
// plus a normal map for relief.
// Roblox tiles its built-in material textures once per 10 studs (the same default
// MaterialVariant.StudsPerTile has).
const ROBLOX_TILE_STUDS = 10;
let use2022Materials = true;
const robloxMapCache = new Map();
const robloxMaterialsUsed = new Set();
const lookAlikeMaterialsUsed = new Set();

function computeUse2022Materials(index) {
  const service = nodesOfClass(index, 'MaterialService')[0];
  if (service) {
    const props = service.props || {};
    return Boolean(props.Use2022MaterialsXml ?? props.Use2022Materials ?? false);
  }
  // A place that never saved the setting keeps the pre-2022 set; a model file lands
  // in whatever place uses it, which today uses the current set.
  return !(nodesOfClass(index, 'Lighting').length || nodesOfClass(index, 'Workspace').length);
}

function loadRobloxMap(id, color) {
  const key = `${id}|${color ? 'c' : 'd'}`;
  if (robloxMapCache.has(key)) return robloxMapCache.get(key);
  const promise = extrasManifest.then(extras => {
    const url = id ? extras.materials?.[id] : null;
    if (!url) return null;
    return keep(color ? 'material-colour' : 'material-data', url, () => new Promise(resolve => new THREE.TextureLoader().load(url, texture => {
      texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
      texture.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
      texture.colorSpace = color ? THREE.SRGBColorSpace : THREE.NoColorSpace;
      resolve(texture);
    }, undefined, () => resolve(null))));
  });
  robloxMapCache.set(key, promise);
  return promise;
}

// The map ids for a material (a part's, or a terrain face's: 'top' / 'side' / 'bottom').
async function robloxMaterialEntry(name, terrainFace = null) {
  const table = await robloxMaterialTable;
  if (!table) return null;
  if (terrainFace) {
    const terrain = use2022Materials ? table.terrain : {...table.terrain, ...table.terrainLegacy};
    const faces = terrain[name];
    if (!faces) return null;
    return faces[terrainFace] || faces.all || faces.side || faces.top || null;
  }
  const parts = use2022Materials ? table.parts : {...table.parts, ...table.partsLegacy};
  return parts[name] || null;
}

async function loadRobloxMaterial(name, terrainFace = null) {
  const entry = await robloxMaterialEntry(name, terrainFace);
  if (!entry?.color) return null;
  const [map, normalMap, roughnessMap, metalnessMap] = await Promise.all([
    loadRobloxMap(entry.color, true),
    loadRobloxMap(entry.normal, false),
    loadRobloxMap(entry.roughness, false),
    loadRobloxMap(entry.metalness, false),
  ]);
  if (!map) return null;
  return {map, normalMap, roughnessMap, metalnessMap, roblox: true};
}

// Colour = texture x part colour where the texture's alpha is 1, texture alone where
// it is 0; the alpha never makes the surface see-through.
function useTintMask(material) {
  material.onBeforeCompile = shader => {
    shader.fragmentShader = shader.fragmentShader.replace('#include <map_fragment>', `
#ifdef USE_MAP
  vec4 rhrTexel = texture2D( map, vMapUv );
  diffuseColor.rgb = rhrTexel.rgb * mix( vec3( 1.0 ), diffuseColor.rgb, rhrTexel.a );
#endif`);
  };
  material.customProgramCacheKey = () => 'rhr-tint-mask';
}

// Metals reflect the sky. Only surfaces that are mostly metal get the environment
// map: it would also add sky light to every rough surface, whose lighting is set by
// the scene's lights (see configureSceneLights).
let environmentTexture = null;
let environmentSpecularScale = 1;
const environmentMaterials = new Set();
function wantsEnvironment(material) {
  environmentMaterials.add(material);
  if (environmentTexture) material.envMap = environmentTexture;
}

const LOOKALIKE_TILE_STUDS = {
  Brick: 8, Cobblestone: 8, Pavement: 8, CeramicTiles: 8, ClayRoofTiles: 8, RoofShingles: 8,
  WoodPlanks: 8, Wood: 8, DiamondPlate: 4, Fabric: 4, Carpet: 4, Foil: 6,
};
const DEFAULT_TILE_STUDS = 10;
const materialTextureCache = new Map();

function loadMaterialTextures(name) {
  if (materialTextureCache.has(name)) return materialTextureCache.get(name);
  const promise = materialCredits.then(async credits => {
    const entry = credits[name];
    if (!entry) return null;
    const loader = new THREE.TextureLoader();
    const load = url => keep('lookalike', url, () => new Promise(resolve => loader.load(url, resolve, undefined, () => resolve(null))));
    const [map, normalMap] = await Promise.all([
      load(`./materials/${name}.jpg`),
      entry.normalMap ? load(`./materials/${name}_n.jpg`) : Promise.resolve(null),
    ]);
    for (const texture of [map, normalMap]) {
      if (!texture) continue;
      texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
      texture.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
    }
    if (map) map.colorSpace = THREE.SRGBColorSpace;
    return map ? {map, normalMap} : null;
  });
  materialTextureCache.set(name, promise);
  return promise;
}

// Roblox's textures where cached, else the look-alike; with the tile size to use.
async function materialTextures(name, terrainFace = null) {
  const roblox = await loadRobloxMaterial(name, terrainFace);
  if (roblox) {
    robloxMaterialsUsed.add(name);
    return {...roblox, tile: ROBLOX_TILE_STUDS};
  }
  const lookAlike = await loadMaterialTextures(name);
  if (lookAlike) lookAlikeMaterialsUsed.add(name);
  return lookAlike ? {...lookAlike, tile: LOOKALIKE_TILE_STUDS[name] || DEFAULT_TILE_STUDS} : null;
}

// Apply a set of material maps to a MeshStandardMaterial.
function applyMaps(material, textures) {
  material.map = textures.map;
  if (textures.roblox) useTintMask(material);
  if (textures.normalMap) {
    material.normalMap = textures.normalMap;
    material.normalScale = new THREE.Vector2(1, 1);
  }
  if (textures.roughnessMap) {
    material.roughnessMap = textures.roughnessMap;
    material.roughness = 1;
  }
  if (textures.metalnessMap) {
    material.metalnessMap = textures.metalnessMap;
    // With Lighting.EnvironmentSpecularScale 0 Roblox's metals reflect no sky and
    // read as their colour, lit like any surface (Studio); at 1 they are full metals.
    material.metalness = environmentSpecularScale;
    wantsEnvironment(material);
  } else if (textures.roblox) {
    material.metalness = 0;
  }
  material.needsUpdate = true;
}

// UVs in studs by box projection in the part's own space: each vertex takes the two
// axes across its face, measured from the part's corner, so a texture tiles at the
// same world size on every face of every part, whatever its size, and does not
// stretch on long parts. U runs the other way on the far faces, so a pattern reads
// the right way round from outside every face. Vertical faces keep the texture
// upright.
function studUVs(geometry, tileStuds) {
  const position = geometry.attributes.position;
  let normal = geometry.attributes.normal;
  if (!normal) {
    geometry.computeVertexNormals();
    normal = geometry.attributes.normal;
  }
  geometry.computeBoundingBox();
  const min = geometry.boundingBox.min;
  const uv = new Float32Array(position.count * 2);
  for (let i = 0; i < position.count; i += 1) {
    const nx = normal.getX(i), ny = normal.getY(i), nz = normal.getZ(i);
    const ax = Math.abs(nx), ay = Math.abs(ny), az = Math.abs(nz);
    const x = position.getX(i) - min.x, y = position.getY(i) - min.y, z = position.getZ(i) - min.z;
    let u;
    let v;
    if (ay >= ax && ay >= az) {
      u = x; v = z;
    } else if (ax >= az) {
      u = nx > 0 ? -z : z; v = y;
    } else {
      u = nz > 0 ? x : -x; v = y;
    }
    uv[i * 2] = u / tileStuds;
    uv[i * 2 + 1] = v / tileStuds;
  }
  geometry.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  return geometry;
}

// A part's MaterialVariant (by name, from MaterialService) with its own ColorMap in
// the local image cache is drawn with that image, tinted by the part's Color and
// tiled at the variant's StudsPerTile, as in Roblox, with its normal, roughness and
// metalness maps when it has them. Without the image, the base material stands in.
let materialVariantsByName = null;
let sceneIndex = null;

// The variant a surface uses: the part's own MaterialVariant, else MaterialService's
// override for its base material ("GrassName" = "MossGrass"), which Terrain uses too.
function materialVariant(index, node, materialName) {
  const service = nodesOfClass(index, 'MaterialService')[0];
  const override = service?.props?.[`${materialName}Name`];
  const name = node?.props?.MaterialVariant || (override && override !== materialName ? override : null);
  if (!name) return null;
  if (!materialVariantsByName) {
    materialVariantsByName = new Map();
    for (const variant of nodesOfClass(index, 'MaterialVariant')) {
      const base = variant.props?.BaseMaterial?.name;
      materialVariantsByName.set(`${variant.name}|${base}`, variant);
    }
  }
  return materialVariantsByName.get(`${name}|${materialName}`) || null;
}

async function loadVariantTextures(variant) {
  const props = variant?.props || {};
  const map = props.ColorMap ? await loadSceneTexture(props.ColorMap) : null;
  if (!map) return null;
  map.wrapS = map.wrapT = THREE.RepeatWrapping;
  map.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
  const [normalMap, roughnessMap, metalnessMap] = await Promise.all([
    props.NormalMap ? loadSceneDataTexture(props.NormalMap) : null,
    props.RoughnessMap ? loadSceneDataTexture(props.RoughnessMap) : null,
    props.MetalnessMap ? loadSceneDataTexture(props.MetalnessMap) : null,
  ]);
  return {map, normalMap, roughnessMap, metalnessMap};
}

// A MeshPart's SurfaceAppearance replaces its material's look. With the mesh and the
// ColorMap both cached, the image is drawn with the mesh's own UVs: AlphaMode
// Transparency cuts out the transparent parts (leaves), Overlay shows the part's
// Color through them, as in Roblox. Its normal, roughness and metalness maps are
// used too when cached.
function surfaceAppearanceOf(node) {
  if (node?.className !== 'MeshPart') return null;
  const surface = Object.values(node.children || {}).find(child => child.className === 'SurfaceAppearance');
  return surface?.props?.ColorMap || surface?.props?.NormalMap || surface?.props?.RoughnessMap ? surface : null;
}

function applySurfaceAppearance(mesh, node, geometryReady) {
  const surface = surfaceAppearanceOf(node);
  if (!surface || flatMaterials) return;
  const props = surface.props || {};
  const job = Promise.all([
    props.ColorMap ? loadSceneTexture(props.ColorMap) : null,
    props.NormalMap ? loadSceneDataTexture(props.NormalMap) : null,
    props.RoughnessMap ? loadSceneDataTexture(props.RoughnessMap) : null,
    props.MetalnessMap ? loadSceneDataTexture(props.MetalnessMap) : null,
    geometryReady,
  ]).then(([texture, normalMap, roughnessMap, metalnessMap]) => {
    if (!mesh.userData.rhrMeshAsset) return;
    const material = mesh.material;
    if (texture?.image) {
      const overlay = (props.AlphaMode?.name || 'Overlay') === 'Overlay';
      let map = texture;
      if (overlay) {
        // Part colour underneath, the image on top.
        const image = texture.image;
        const canvas = document.createElement('canvas');
        canvas.width = image.width || 256;
        canvas.height = image.height || 256;
        const context = canvas.getContext('2d');
        context.fillStyle = '#' + material.color.getHexString(THREE.SRGBColorSpace);
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        map = new THREE.CanvasTexture(canvas);
        map.colorSpace = THREE.SRGBColorSpace;
      } else {
        material.alphaTest = 0.5;
        material.side = THREE.DoubleSide;
      }
      map.wrapS = map.wrapT = THREE.RepeatWrapping;
      material.map = map;
      material.color.copy(colorValue(props.Color));
    }
    if (normalMap) material.normalMap = normalMap;
    if (roughnessMap) {
      material.roughnessMap = roughnessMap;
      material.roughness = 1;
    }
    if (metalnessMap) {
      material.metalnessMap = metalnessMap;
      material.metalness = 1;
      wantsEnvironment(material);
    }
    material.needsUpdate = true;
    mesh.userData.rhrSurfaceAppearance = true;
  });
  materialTextureJobs.push(job);
}

// An image drawn over the part's own colour with the mesh's own UVs (uv1): where the
// image is transparent the colour shows, as for a mesh's texture in Roblox. `tint`
// (a SpecialMesh's VertexColor) multiplies the image. A premultiplied image (a
// character's clothing, painted in a render target) adds its colour instead of mixing.
function useOverlayMap(material, texture, premultiplied = false, tint = null) {
  texture.channel = 1;
  material.map = texture;
  const t = tint ? `vec3( ${tint.r.toFixed(5)}, ${tint.g.toFixed(5)}, ${tint.b.toFixed(5)} )` : null;
  const image = t ? `rhrOverlay.rgb * ${t}` : 'rhrOverlay.rgb';
  material.onBeforeCompile = shader => {
    shader.fragmentShader = shader.fragmentShader.replace('#include <map_fragment>', `
#ifdef USE_MAP
  vec4 rhrOverlay = texture2D( map, vMapUv );
  diffuseColor.rgb = ${premultiplied ? `diffuseColor.rgb * ( 1.0 - rhrOverlay.a ) + ${image}` : `mix( diffuseColor.rgb, ${image}, rhrOverlay.a )`};
#endif`);
  };
  const key = `rhr-overlay${premultiplied ? '-premultiplied' : ''}${t ? `-${t}` : ''}`;
  material.customProgramCacheKey = () => key;
  material.needsUpdate = true;
}

// A MeshPart's TextureID, or the TextureId of a FileMesh or Head SpecialMesh.
function meshTextureUri(node) {
  if (node?.className === 'MeshPart') return surfaceAppearanceOf(node) ? null : node.props?.TextureID || null;
  const special = specialMeshChild(node);
  const type = special?.props?.MeshType?.name;
  return special && (type === 'FileMesh' || type === 'Head') ? special.props?.TextureId || null : null;
}

// Drawn with the mesh's own UVs once the mesh has loaded (a box stand-in has none to
// draw it with). The part's colour shows through the image's transparent parts
// (Studio: an R6 package head textured with the face image is the head's colour with
// the face on it); a SpecialMesh's VertexColor tints the image.
function applyMeshTexture(mesh, node, geometryReady) {
  const uri = meshTextureUri(node);
  if (!uri || flatMaterials) return false;
  const special = node.className === 'MeshPart' ? null : specialMeshChild(node);
  const job = Promise.all([loadSceneTexture(uri), geometryReady]).then(([texture]) => {
    if (!texture || !mesh.userData.rhrMeshAsset || !mesh.geometry.attributes.uv1) return;
    const map = texture.clone();
    map.wrapS = map.wrapT = THREE.RepeatWrapping;
    map.needsUpdate = true;
    const vertexColor = special?.props?.VertexColor;
    const tint = vertexColor && (vertexColor.X !== 1 || vertexColor.Y !== 1 || vertexColor.Z !== 1)
      ? new THREE.Color().setRGB(Number(vertexColor.X ?? 1), Number(vertexColor.Y ?? 1), Number(vertexColor.Z ?? 1), THREE.SRGBColorSpace)
      : null;
    useOverlayMap(mesh.material, map, false, tint);
    mesh.userData.rhrMeshTexture = true;
  });
  materialTextureJobs.push(job);
  return true;
}

function applyMaterialTexture(mesh, materialName, geometryReady = Promise.resolve(), node = null, index = null) {
  if (flatMaterials || !materialName) return;
  if (surfaceAppearanceOf(node)) return;  // the SurfaceAppearance replaces the material's look
  const variant = node && index ? materialVariant(index, node, materialName) : null;
  if (!variant && ['Plastic', 'SmoothPlastic', 'Neon', 'Glass', 'ForceField'].includes(materialName)) {
    if (materialName === 'Plastic' || materialName === 'SmoothPlastic') applyPlasticDetail(mesh, node, geometryReady, materialName === 'Plastic');
    return;
  }
  const variantTile = Number(variant?.props?.StudsPerTile) || 10;
  const textures = (async () => {
    const own = variant ? await loadVariantTextures(variant) : null;
    if (own) return {...own, tile: variantTile, variant: variant.name};
    return materialTextures(materialName);
  })();
  // After the part's own mesh load, so the UVs are computed on the final geometry.
  const job = Promise.all([textures, geometryReady]).then(([textures]) => {
    if (!textures) return;
    if (textures.variant) mesh.userData.rhrMaterialVariant = textures.variant;
    studUVs(mesh.geometry, textures.tile);
    applyMaps(mesh.material, textures);
    if (!textures.roblox && !textures.variant) mesh.material.normalScale = new THREE.Vector2(0.8, 0.8);
    mesh.userData.rhrMaterialTexture = materialName;
  });
  materialTextureJobs.push(job);
}

// Plastic's faint surface relief, and legacy surfaces (a Baseplate's studs), from the
// local Studio install when there is one. UVs are in studs; each texture's repeat
// sets its size: the relief every 4 studs, a surface tile every 2 (it holds 2x2 studs).
const studioTextureCache = new Map();
function loadStudioTexture(name, repeat) {
  if (!studioTextureCache.has(name)) {
    studioTextureCache.set(name, extrasManifest.then(extras => {
      const url = extras.studio?.[name];
      if (!url) return null;
      return keep(`studio-${repeat}`, url, () => new Promise(resolve => new THREE.TextureLoader().load(url, texture => {
        texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
        texture.colorSpace = THREE.NoColorSpace;
        texture.repeat.set(1 / repeat, 1 / repeat);
        texture.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
        resolve(texture);
      }, undefined, () => resolve(null))));
    }));
  }
  return studioTextureCache.get(name);
}

// Part faces in BoxGeometry's group order, and the surface texture per SurfaceType.
const BOX_FACE_SURFACES = ['RightSurface', 'LeftSurface', 'TopSurface', 'BottomSurface', 'BackSurface', 'FrontSurface'];
const SURFACE_TEXTURES = {
  Studs: 'surface_studs', Inlet: 'surface_inlet', Universal: 'surface_universal',
  Weld: 'surface_weld', Glue: 'surface_weld',
};

// Studio draws a part's surfaces (studs, inlets...) on Plastic only: SmoothPlastic,
// Wood, Metal, Neon, Brick, Glass and Concrete with TopSurface Studs show none.
function applyPlasticDetail(mesh, node, geometryReady, withSurfaces = true) {
  const isBox = withSurfaces && node?.className === 'Part' && ['Block', undefined].includes(node.props?.Shape?.name ?? node.props?.shape?.name);
  const surfaces = isBox ? BOX_FACE_SURFACES.map(face => SURFACE_TEXTURES[node.props?.[face]?.name] || null) : [];
  const job = Promise.all([
    loadStudioTexture('plastic_normaldetail', 4),
    Promise.all(surfaces.map(name => (name ? loadStudioTexture(name, 2) : null))),
    geometryReady,
  ]).then(([detail, tiles]) => {
    if (!detail && !tiles.some(Boolean)) return;
    studUVs(mesh.geometry, 1);
    const base = mesh.material;
    if (detail) {
      base.normalMap = detail;
      base.normalScale = new THREE.Vector2(0.25, 0.25);
      base.needsUpdate = true;
    }
    // Per-face materials need the box's six face groups. A Block part whose SpecialMesh
    // makes it a sphere or a file mesh (an R6 head) has none, and would not draw at all.
    if (!tiles.some(Boolean) || mesh.geometry.groups.length !== 6) return;
    // The surface tile is grey around mid-value: the part's colour times twice the
    // tile, so the face keeps its colour on average.
    mesh.material = tiles.map(tile => {
      if (!tile) return base;
      const material = base.clone();
      material.map = tile;
      material.onBeforeCompile = shader => {
        shader.fragmentShader = shader.fragmentShader.replace('#include <map_fragment>', `
#ifdef USE_MAP
  diffuseColor.rgb *= texture2D( map, vMapUv ).rgb * 2.0;
#endif`);
      };
      material.customProgramCacheKey = () => 'rhr-surface';
      return material;
    });
  });
  materialTextureJobs.push(job);
}

// Union (CSG) render meshes, decoded by rhr.unions into the cache (see rhr.fetch).
const sceneUnionCache = new Map();

// The cache key of a union's mesh: its asset id, or for a mesh saved in the file
// (MeshData2) "inline-" + the hash rhr.scene named it by.
async function unionKey(node) {
  if (node.props?.AssetId) return contentAssetId(node.props.AssetId);
  const encoded = node.props?.MeshData2;
  if (!encoded) return null;
  const digest = await crypto.subtle.digest('SHA-1', base64Bytes(encoded));
  const hex = [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('');
  return `inline-${hex.slice(0, 20)}`;
}

function loadUnionGeometry(assetId) {
  if (!assetId) return Promise.resolve(null);
  if (sceneUnionCache.has(assetId)) return sceneUnionCache.get(assetId);
  const promise = (async () => {
    const extras = await extrasManifest;
    const url = extras.unions?.[assetId];
    if (!url) return null;
    const response = await fetch(url);
    if (!response.ok) return null;
    const data = await response.json();
    const floats = text => new Float32Array(base64Bytes(text).buffer);
    const positions = floats(data.positions);
    if (!positions.length) return null;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    const normals = floats(data.normals);
    const uvs = floats(data.uvs);
    const colors = base64Bytes(data.colors);
    const count = positions.length / 3;
    if (normals.length === count * 3) geometry.setAttribute('normal', new THREE.BufferAttribute(normals, 3));
    if (uvs.length === count * 2) geometry.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
    if (colors.length === count * 4) {
      const linear = new Float32Array(count * 3);
      const c = new THREE.Color();
      for (let i = 0; i < count; i += 1) {
        c.setRGB(colors[i * 4] / 255, colors[i * 4 + 1] / 255, colors[i * 4 + 2] / 255, THREE.SRGBColorSpace);
        linear[i * 3] = c.r; linear[i * 3 + 1] = c.g; linear[i * 3 + 2] = c.b;
      }
      geometry.setAttribute('color', new THREE.BufferAttribute(linear, 3));
    }
    geometry.setIndex(new THREE.BufferAttribute(new Uint32Array(base64Bytes(data.indices).buffer), 1));
    if (!geometry.attributes.normal) geometry.computeVertexNormals();
    return geometry;
  })().catch(() => null);
  sceneUnionCache.set(assetId, promise);
  return promise;
}

function addPart(node, parent) {
  const cf = node.props?.CFrame;
  if (!cf) return;
  const transparency = Number(node.props?.Transparency ?? 0);
  const materialName = node.props?.Material?.name || 'Plastic';
  const materialSpec = MATERIAL_TABLE[materialName] || MATERIAL_TABLE.Plastic;
  const reflectance = Math.max(0, Math.min(1, Number(node.props?.Reflectance ?? 0)));
  const color = colorValue(node.props?.Color);
  const opacity = Math.max(0, Math.min(1, (1 - transparency) * Number(materialSpec.opacityScale ?? 1)));
  const material = new THREE.MeshStandardMaterial({
    color: materialSpec.unlit ? new THREE.Color(0x000000) : color,
    roughness: materialSpec.roughness,
    metalness: Math.max(materialSpec.metalness, reflectance),
    emissive: materialSpec.emissiveIntensity ? color.clone() : new THREE.Color(0x000000),
    emissiveIntensity: Number(materialSpec.emissiveIntensity ?? 0),
    transparent: opacity < 1,
    opacity,
  });
  // A fully transparent part is not drawn at all. Drawn at opacity 0 it still hides
  // what comes after it, and effects nearly always sit in such a part. It still
  // counts for framing.
  if (opacity <= 0.001) material.visible = false;
  if (reflectance > 0.2 || ['Glass', 'Ice', 'Glacier', 'Foil', 'Metal', 'DiamondPlate'].includes(materialName)) {
    wantsEnvironment(material);
  }
  const mesh = new THREE.Mesh(shapeGeometry(node), material);
  const special = specialMeshChild(node);
  let geometryReady = Promise.resolve();
  if (node.className === 'MeshPart' && node.props?.MeshId) {
    const job = loadMeshGeometry(node.props.MeshId).then(baseGeometry => {
      if (!baseGeometry) return;
      const fitted = fitMeshGeometryToPart(baseGeometry, node.props?.Size);
      mesh.geometry.dispose();
      mesh.geometry = fitted;
      mesh.userData.rhrMeshAsset = meshAssetId(node.props.MeshId);
    });
    meshGeometryJobs.push(job);
    geometryReady = job;
  } else if (node.className === 'UnionOperation' && (node.props?.AssetId || node.props?.MeshData2)) {
    const job = unionKey(node).then(async key => {
      const baseGeometry = await loadUnionGeometry(key);
      if (!baseGeometry) return;
      const fitted = fitMeshGeometryToPart(baseGeometry, node.props?.Size);
      mesh.geometry.dispose();
      mesh.geometry = fitted;
      mesh.userData.rhrUnionAsset = key;
      // Without UsePartColor a union keeps the colour of each part it was made from.
      if (fitted.attributes.color && node.props?.UsePartColor !== true) {
        material.vertexColors = true;
        material.color.set(0xffffff);
        if (material.emissiveIntensity) material.emissive.set(0xffffff);
        material.needsUpdate = true;
      }
    });
    meshGeometryJobs.push(job);
    geometryReady = job;
  } else if (special?.props?.MeshType?.name === 'FileMesh' && special.props?.MeshId) {
    const job = loadMeshGeometry(special.props.MeshId).then(baseGeometry => {
      if (!baseGeometry) return;
      const transformed = transformSpecialFileMesh(baseGeometry, special);
      mesh.geometry.dispose();
      mesh.geometry = transformed;
      mesh.userData.rhrMeshAsset = meshAssetId(special.props.MeshId);
    });
    meshGeometryJobs.push(job);
    geometryReady = job;
  } else if (special?.props?.MeshType?.name === 'Head') {
    const job = loadMeshGeometry(HEAD_MESH).then(baseGeometry => {
      if (!baseGeometry) return;
      const fitted = fitMeshGeometryToPart(baseGeometry, headMeshSize(node, special));
      const offset = special.props?.Offset;
      if (offset) fitted.translate(Number(offset.X ?? 0), Number(offset.Y ?? 0), Number(offset.Z ?? 0));
      mesh.geometry.dispose();
      mesh.geometry = fitted;
      mesh.userData.rhrMeshAsset = 'head';
    });
    meshGeometryJobs.push(job);
    geometryReady = job;
  }
  // A mesh's own image (TextureID) replaces the material's look, as a SurfaceAppearance does.
  if (!applyMeshTexture(mesh, node, geometryReady)) {
    applyMaterialTexture(mesh, materialName, geometryReady, node, sceneIndex);
  }
  applySurfaceAppearance(mesh, node, geometryReady);
  mesh.castShadow = node.props?.CastShadow !== false;
  mesh.receiveShadow = true;
  mesh.userData.rhrNode = node;
  meshByNode.set(node, mesh);
  mesh.matrixAutoUpdate = false;
  mesh.matrix.copy(cframeMatrix(cf));
  mesh.matrixWorldNeedsUpdate = true;
  parent.add(mesh);
}

// A MeshPart or FileMesh whose mesh is not in the local cache has only its bounding
// box. It is drawn as that box with an outline, so it reads as a stand-in, and casts
// no shadow (a box's shadow is not the object's). Its colour comes from its
// SurfaceAppearance's ColorMap when that image is cached: a MeshPart with a
// SurfaceAppearance is usually white, the image carries its real colour (green
// leaves, a yellow beam), and a white box there would be the wrong colour entirely.
// Average colour of an image. With `under` (SurfaceAppearance AlphaMode Overlay) the
// transparent parts show that colour, as the part's Color shows through in Roblox;
// without it (AlphaMode Transparency: cut-out leaves) only opaque pixels count.
async function averageImageColor(texture, under = null) {
  const image = texture?.image;
  if (!image) return null;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 16;
  const context = canvas.getContext('2d');
  context.drawImage(image, 0, 0, 16, 16);
  const data = context.getImageData(0, 0, 16, 16).data;
  let r = 0, g = 0, b = 0, n = 0;
  const base = under ? under.clone().convertLinearToSRGB() : null;
  for (let i = 0; i < data.length; i += 4) {
    const alpha = data[i + 3] / 255;
    if (base) {
      r += data[i] * alpha + base.r * 255 * (1 - alpha);
      g += data[i + 1] * alpha + base.g * 255 * (1 - alpha);
      b += data[i + 2] * alpha + base.b * 255 * (1 - alpha);
      n += 1;
    } else if (alpha >= 0.5) {  // cut-outs: only the opaque part counts
      r += data[i]; g += data[i + 1]; b += data[i + 2]; n += 1;
    }
  }
  if (!n) return null;
  return new THREE.Color().setRGB(r / n / 255, g / n / 255, b / n / 255, THREE.SRGBColorSpace);
}

async function stylePlaceholderMeshes() {
  const jobs = [];
  scene.traverse(object => {
    const node = object.userData?.rhrNode;
    if (!object.isMesh || !node || object.userData.rhrMeshAsset || object.userData.rhrUnionAsset) return;
    const special = specialMeshChild(node);
    const wantsMesh = (node.className === 'MeshPart' && node.props?.MeshId)
      || node.className === 'UnionOperation'
      || (special?.props?.MeshType?.name === 'FileMesh' && special.props?.MeshId);
    if (!wantsMesh) return;
    object.castShadow = false;
    object.userData.rhrPlaceholder = true;
    const surface = Object.values(node.children || {}).find(child => child.className === 'SurfaceAppearance');
    jobs.push((async () => {
      const texture = surface?.props?.ColorMap ? await loadSceneTexture(surface.props.ColorMap) : null;
      const overlay = (surface?.props?.AlphaMode?.name || 'Overlay') === 'Overlay';
      const average = await averageImageColor(texture, overlay ? object.material.color : null);
      if (average) {
        object.material.color.copy(average.multiply(colorValue(surface.props?.Color)));
        object.material.needsUpdate = true;
      }
      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(object.geometry),
        new THREE.LineBasicMaterial({color: object.material.color.clone().multiplyScalar(0.45)}),
      );
      edges.userData.rhrPlaceholderEdges = true;
      object.add(edges);
    })());
  });
  await Promise.all(jobs);
}

// Voxel terrain (rhr.terrain decodes Terrain.SmoothGrid), drawn smooth the way Roblox
// meshes it: surface nets over the voxel grid. Grid corners are voxel centres; every
// cell that the surface passes through gets one vertex, placed at the average of the
// points where the surface crosses the cell's edges, and each voxel face between a
// solid and an empty voxel becomes a quad joining the four cells around it. Where
// along an edge the surface crosses comes from the solid voxel's occupancy: a full
// voxel reaches all the way to its empty neighbour's centre, a nearly empty one
// barely leaves its own. Normals are averaged over the whole surface, so material
// borders do not crease.
//
// Materials: every vertex takes one material, the first in Roblox's terrain material
// order (Grass, Slate, Concrete, Brick, Sand, ...) among the solid voxels around it,
// so where two materials meet the earlier one reaches half a voxel (2 studs) into the
// other: measured in Studio on nine pairs, both ways round. Across a face whose
// corners differ the materials are blended by height, as Roblox does: each
// material's weight (1 at its own corners, 0 at the others) plus the height its
// colour map carries in its alpha; the highest wins, with a soft band
// (TUNE.tBlendH, TUNE.tBlendD). Each face uses the texture for its direction
// (Roblox gives Grass, Asphalt and others separate top, side and bottom textures),
// projected along the face's main axis in world space. Water is its own surface,
// only where it meets air.
let terrainSummary = null;
let terrainGrassSource = null;  // set by addTerrain when Terrain.Decoration is on

function base64Bytes(text) {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

// Terrain textures repeat every 8 studs (checked against Studio).
const TERRAIN_TILE_STUDS = 8;

function terrainSurface(chunks, n, voxelStuds, isInside, isOutside) {
  const key = (x, y, z) => `${x},${y},${z}`;
  const sample = (gx, gy, gz) => {
    const cx = Math.floor(gx / n), cy = Math.floor(gy / n), cz = Math.floor(gz / n);
    const chunk = chunks.get(key(cx, cy, cz));
    if (!chunk) return [0, 0];
    const i = (gx - cx * n) + n * (gz - cz * n) + n * n * (gy - cy * n);
    return [chunk.materials[i], chunk.occupancy[i]];
  };
  const vertexIndex = new Map();   // "x,y,z" of the cell -> vertex number
  const positions = [];
  const vertexMaterials = [];
  const vertexOf = (x, y, z) => {
    const id = key(x, y, z);
    let index = vertexIndex.get(id);
    if (index !== undefined) return index;
    // Average the crossings on the cell's 12 edges.
    let sx = 0, sy = 0, sz = 0, count = 0;
    const corner = [];
    for (let c = 0; c < 8; c += 1) {
      const ox = c & 1, oy = (c >> 1) & 1, oz = (c >> 2) & 1;
      const [material, occupancy] = sample(x + ox, y + oy, z + oz);
      corner.push({ox, oy, oz, material, inside: isInside(material), occupancy});
    }
    for (let a = 0; a < 8; a += 1) {
      for (const bit of [1, 2, 4]) {
        const b = a | bit;
        if (b === a) continue;
        const ca = corner[a], cb = corner[b];
        if (ca.inside === cb.inside) continue;
        const t = ca.inside ? (ca.occupancy + 1) / 256 : 1 - (cb.occupancy + 1) / 256;
        sx += ca.ox + (cb.ox - ca.ox) * t;
        sy += ca.oy + (cb.oy - ca.oy) * t;
        sz += ca.oz + (cb.oz - ca.oz) * t;
        count += 1;
      }
    }
    if (!count) { sx = sy = sz = 0.5; count = 1; }
    let material = 0;
    for (const c of corner) if (c.inside && (!material || c.material < material)) material = c.material;
    vertexMaterials.push(material);
    index = positions.length / 3;
    positions.push(
      (x + sx / count + 0.5) * voxelStuds,
      (y + sy / count + 0.5) * voxelStuds,
      (z + sz / count + 0.5) * voxelStuds,
    );
    vertexIndex.set(id, index);
    return index;
  };

  const quads = [];  // [v0, v1, v2, v3, material]
  const axes = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
  for (const chunk of chunks.values()) {
    const [cx, cy, cz] = chunk.position;
    // Voxel pairs (p, p + axis) whose first voxel lies in this chunk; the pair may
    // reach into the next chunk. Pairs starting just before the chunk are done
    // here only when there is no chunk there to do them.
    const start = [
      chunks.has(key(cx - 1, cy, cz)) ? 0 : -1,
      chunks.has(key(cx, cy - 1, cz)) ? 0 : -1,
      chunks.has(key(cx, cy, cz - 1)) ? 0 : -1,
    ];
    for (let ly = start[1]; ly < n; ly += 1) for (let lz = start[2]; lz < n; lz += 1) for (let lx = start[0]; lx < n; lx += 1) {
      const gx = cx * n + lx, gy = cy * n + ly, gz = cz * n + lz;
      const [m0] = sample(gx, gy, gz);
      const in0 = isInside(m0);
      for (let axis = 0; axis < 3; axis += 1) {
        // A pair starting outside this chunk on another axis belongs to that neighbour.
        if ((lx < 0 && axis !== 0) || (ly < 0 && axis !== 1) || (lz < 0 && axis !== 2)) continue;
        const [dx, dy, dz] = axes[axis];
        const [m1] = sample(gx + dx, gy + dy, gz + dz);
        const in1 = isInside(m1);
        if (in0 === in1) continue;
        if (in0 && !isOutside(m1)) continue;
        if (in1 && !isOutside(m0)) continue;
        // The four cells around this edge, in order round the axis.
        const u = axes[(axis + 1) % 3], v = axes[(axis + 2) % 3];
        const cell = (a, b) => vertexOf(gx - u[0] * a - v[0] * b, gy - u[1] * a - v[1] * b, gz - u[2] * a - v[2] * b);
        const ring = [cell(0, 0), cell(1, 0), cell(1, 1), cell(0, 1)];
        // Wind so the face looks out of the solid side.
        if (!in0) ring.reverse();
        quads.push([...ring, in0 ? m0 : m1]);
      }
    }
  }

  // Smooth normals over the whole surface.
  const normals = new Float32Array(positions.length);
  const p = i => new THREE.Vector3(positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2]);
  for (const quad of quads) {
    const [a, b, c, d] = quad;
    const normal = new THREE.Vector3().crossVectors(p(c).sub(p(a)), p(d).sub(p(b)));
    for (const index of [a, b, c, d]) {
      normals[index * 3] += normal.x; normals[index * 3 + 1] += normal.y; normals[index * 3 + 2] += normal.z;
    }
  }
  for (let i = 0; i < normals.length; i += 3) {
    const length = Math.hypot(normals[i], normals[i + 1], normals[i + 2]) || 1;
    normals[i] /= length; normals[i + 1] /= length; normals[i + 2] /= length;
  }
  return {positions, normals, quads, vertexMaterials};
}

// One geometry per layer (a material and a texture direction: top, side or bottom),
// with world-space box-projected UVs. Each corner weighs the layers of its material
// by its normal (TERRAIN_KIND_BAND: steep turns from top to side over a band, not at
// a line), and `canonicalKind` folds directions that share a texture. A face whose
// corners all have one layer goes into that layer's geometry (`material`, `kind`); a
// face with more goes into a blend geometry for its layers (`blend`, the
// TERRAIN_BLEND_SLOTS heaviest) with each corner's weights in `rhrW`.
const TERRAIN_BLEND_SLOTS = 4;
const TERRAIN_KIND_BAND = [0.4, 0.65];

function terrainKindWeights(ny) {
  const [low, high] = TERRAIN_KIND_BAND;
  const top = THREE.MathUtils.smoothstep(ny, low, high);
  const bottom = THREE.MathUtils.smoothstep(-ny, low, high);
  return [['top', top], ['side', 1 - top - bottom], ['bottom', bottom]].filter(([, w]) => w > 1e-3);
}

function terrainGeometries(surface, kindWeights, canonicalKind = (_, kind) => kind) {
  const {positions, normals, quads, vertexMaterials} = surface;
  const groups = new Map();
  for (const quad of quads) {
    const [a, b, c, d, own] = quad;
    const mean = axis => (normals[a * 3 + axis] + normals[b * 3 + axis] + normals[c * 3 + axis] + normals[d * 3 + axis]) / 4;
    const [qx, qy, qz] = [mean(0), mean(1), mean(2)];
    // One projection for the whole face: chosen per corner, a face on a curve
    // would stretch the texture across two projections.
    const ax = Math.abs(qx), ay = Math.abs(qy), az = Math.abs(qz);
    const projection = ay >= ax && ay >= az ? 'y' : ax >= az ? 'x' : 'z';
    // Each corner's weight per layer ("material|kind").
    const cornerWeights = [a, b, c, d].map(index => {
      const material = vertexMaterials?.[index] || own;
      const weights = new Map();
      for (const [kind, w] of kindWeights(normals[index * 3 + 1])) {
        const key = `${material}|${canonicalKind(material, kind)}`;
        weights.set(key, (weights.get(key) || 0) + w);
      }
      return weights;
    });
    const totals = new Map();
    for (const weights of cornerWeights) for (const [key, w] of weights) totals.set(key, (totals.get(key) || 0) + w);
    const byName = (x, y) => (x < y ? -1 : x > y ? 1 : 0);
    const layers = [...totals.keys()]
      .sort((x, y) => totals.get(y) - totals.get(x) || byName(x, y))
      .slice(0, TERRAIN_BLEND_SLOTS)
      .sort(byName);
    const blend = layers.length > 1;
    const groupKey = layers.join(',');
    let group = groups.get(groupKey);
    if (!group) {
      const parsed = layers.map(key => {
        const [material, kind] = key.split('|');
        return {material: Number(material), kind};
      });
      groups.set(groupKey, group = {
        material: parsed[0].material, kind: parsed[0].kind, blend: blend ? parsed : null,
        positions: [], normals: [], uvs: [], weights: [],
      });
    }
    const cornerOf = new Map([[a, 0], [b, 1], [c, 2], [d, 3]]);
    for (const index of [a, b, c, a, c, d]) {
      const x = positions[index * 3], y = positions[index * 3 + 1], z = positions[index * 3 + 2];
      group.positions.push(x, y, z);
      group.normals.push(normals[index * 3], normals[index * 3 + 1], normals[index * 3 + 2]);
      if (projection === 'y') group.uvs.push(x / TERRAIN_TILE_STUDS, z / TERRAIN_TILE_STUDS);
      else if (projection === 'x') group.uvs.push(z / TERRAIN_TILE_STUDS, y / TERRAIN_TILE_STUDS);
      else group.uvs.push(x / TERRAIN_TILE_STUDS, y / TERRAIN_TILE_STUDS);
      if (blend) {
        const weights = cornerWeights[cornerOf.get(index)];
        const row = layers.map(key => weights.get(key) || 0);
        const sum = row.reduce((x, y) => x + y, 0);
        // A corner whose layers all lost their slots counts as the first slot's.
        for (let s = 0; s < TERRAIN_BLEND_SLOTS; s += 1) group.weights.push(sum > 0 ? (row[s] || 0) / sum : (s === 0 ? 1 : 0));
      }
    }
  }
  return [...groups.values()].map(group => {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(group.positions, 3));
    geometry.setAttribute('normal', new THREE.Float32BufferAttribute(group.normals, 3));
    geometry.setAttribute('uv', new THREE.Float32BufferAttribute(group.uvs, 2));
    if (group.blend) geometry.setAttribute('rhrW', new THREE.Float32BufferAttribute(group.weights, TERRAIN_BLEND_SLOTS));
    return {geometry, material: group.material, blend: group.blend, kind: group.kind, triangles: group.positions.length / 9};
  });
}

// Texture directions that share a texture count as one layer: a material with a
// single texture (Rock, Mud...) blends only with other materials. Keyed by the
// maps Roblox's table gives each direction; a MaterialVariant, the look-alikes and
// flat colours are the same on every face.
async function terrainKindCanon(index, names) {
  const canon = new Map();
  for (let m = 0; m < names.length; m += 1) {
    const name = names[m];
    const same = flatMaterials || materialVariant(index, null, name);
    const entries = same ? null : await Promise.all(['top', 'side', 'bottom'].map(kind => robloxMaterialEntry(name, kind)));
    const id = entry => (entry ? `${entry.color}|${entry.normal}` : '');
    for (const [k, kind] of ['top', 'side', 'bottom'].entries()) {
      let first = kind;
      if (same || !entries[k]) first = 'top';
      else first = ['top', 'side', 'bottom'][entries.findIndex(entry => id(entry) === id(entries[k]))];
      canon.set(`${m}|${kind}`, first);
    }
  }
  return (material, kind) => canon.get(`${material}|${kind}`) || kind;
}

// How one terrain material looks on one face direction: its colour (the texture's
// multiplier), its maps if any, and how many times its texture repeats per terrain
// tile. A MaterialVariant override comes first, then Roblox's own terrain textures,
// then the CC0 look-alike; with none (or --flat-materials) the plain colour.
const terrainLookCache = new Map();

function terrainLook(index, terrain, name, kind) {
  const key = `${name}|${kind}`;
  if (!terrainLookCache.has(key)) terrainLookCache.set(key, loadTerrainLook(index, terrain, name, kind));
  return terrainLookCache.get(key);
}

async function loadTerrainLook(index, terrain, name, kind) {
  const raw = terrain.rawColors?.[name];
  const natural = terrain.colors?.[name];
  const color = new THREE.Color().setRGB(...(natural || [128, 128, 128]).map(c => c / 255), THREE.SRGBColorSpace);
  const plain = {color, maps: null, uvScale: 1, source: null};
  if (flatMaterials) return plain;
  // A MaterialVariant override: its image in real colours, tinted by the place's
  // MaterialColor (white leaves it as is).
  const variant = materialVariant(index, null, name);
  const own = variant ? await loadVariantTextures(variant) : null;
  const tint = raw || [255, 255, 255];
  if (own) {
    const tile = Number(variant.props?.StudsPerTile) || 10;
    return {
      color: new THREE.Color().setRGB(tint[0] / 255, tint[1] / 255, tint[2] / 255, THREE.SRGBColorSpace),
      maps: own, uvScale: TERRAIN_TILE_STUDS / tile, source: 'variant', variant: variant.name,
    };
  }
  const roblox = await loadRobloxMaterial(name, kind);
  if (roblox) {
    // Roblox's terrain textures are pale: it multiplies them by the material's
    // base colour (the install's materials2022.json), scaled by the place's
    // MaterialColor over the default one. Without the install, the default
    // colour stands in for the base colour.
    robloxMaterialsUsed.add(name);
    const fallback = terrain.defaultColors?.[name] || tint;
    const base = terrain.baseColors?.[name] || fallback;
    const channel = k => (base[k] / 255) * Math.min(2, tint[k] / Math.max(1, fallback[k]));
    return {
      color: new THREE.Color().setRGB(channel(0), channel(1), channel(2), THREE.SRGBColorSpace),
      maps: roblox, uvScale: 1, source: 'roblox',
    };
  }
  const lookAlike = await loadMaterialTextures(name);
  if (!lookAlike) return plain;
  lookAlikeMaterialsUsed.add(name);
  return {color, maps: lookAlike, uvScale: 1, source: 'lookalike'};
}

function applyTerrainLook(meshMaterial, mesh, look) {
  meshMaterial.color.copy(look.color);
  if (!look.maps) return;
  if (look.uvScale !== 1) {
    const uv = mesh.geometry.attributes.uv;
    for (let i = 0; i < uv.count; i += 1) uv.setXY(i, uv.getX(i) * look.uvScale, uv.getY(i) * look.uvScale);
  }
  if (look.source === 'lookalike') {
    meshMaterial.map = look.maps.map;
    if (look.maps.normalMap) meshMaterial.normalMap = look.maps.normalMap;
    meshMaterial.needsUpdate = true;
    return;
  }
  applyMaps(meshMaterial, look.maps);
  if (look.variant) mesh.userData.rhrMaterialVariant = look.variant;
  if (look.source === 'roblox') {
    meshMaterial.onBeforeCompile = () => {};  // terrain colour maps are not tint masks
    meshMaterial.customProgramCacheKey = () => 'rhr-terrain';
  }
}

// 1x1 stand-ins for a blend slot without a texture: white at mid height, flat normal.
let terrainBlankTextures = null;
function blankTerrainTextures() {
  if (terrainBlankTextures) return terrainBlankTextures;
  const make = (bytes, colorSpace) => {
    const texture = new THREE.DataTexture(new Uint8Array(bytes), 1, 1);
    texture.colorSpace = colorSpace;
    texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
    texture.needsUpdate = true;
    return texture;
  };
  terrainBlankTextures = {
    color: make([255, 255, 255, 128], THREE.SRGBColorSpace),
    normal: make([128, 128, 255, 255], THREE.NoColorSpace),
  };
  return terrainBlankTextures;
}

// A face where materials meet: every slot's colour and normal map sampled and
// blended by height (see the terrain notes above). Roughness is a flat 0.95 there
// (samplers are scarce: three maps a slot would pass WebGL's 16).
function terrainBlendMaterial(looks, carpetMask = []) {
  const blank = blankTerrainTextures();
  const material = new THREE.MeshStandardMaterial({color: 0xffffff, roughness: 1, metalness: 0});
  material.map = looks[0].maps?.map || blank.color;
  material.normalMap = blank.normal;
  const uniforms = {
    rhrBlendH: {value: TUNE.tBlendH},
    rhrBlendD: {value: TUNE.tBlendD},
    rhrBlendN: {value: TUNE.tBlendN},
    rhrCarpet: {value: grassCarpetColor()},
    rhrCarpetRange: {value: new THREE.Vector2(TUNE.gCarpetNear, TUNE.gCarpetFar)},
  };
  for (let s = 0; s < TERRAIN_BLEND_SLOTS; s += 1) {
    const look = looks[s];
    uniforms[`rhrColor${s}`] = {value: look?.maps?.map || blank.color};
    uniforms[`rhrNormal${s}`] = {value: look?.maps?.normalMap || blank.normal};
    uniforms[`rhrTint${s}`] = {value: look ? look.color.clone() : new THREE.Color(0, 0, 0)};
    uniforms[`rhrScale${s}`] = {value: look?.uvScale || 1};
    uniforms[`rhrRough${s}`] = {value: 0.95};
    uniforms[`rhrUsed${s}`] = {value: look ? 1 : 0};
    uniforms[`rhrCarpetMask${s}`] = {value: carpetMask[s] ? 1 : 0};
  }
  const slots = [...Array(TERRAIN_BLEND_SLOTS).keys()];
  material.onBeforeCompile = shader => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', `#include <common>
attribute vec4 rhrW;
varying vec4 vRhrW;`)
      .replace('#include <begin_vertex>', `#include <begin_vertex>
vRhrW = rhrW;`);
    const declarations = slots.map(s => `uniform sampler2D rhrColor${s};
uniform sampler2D rhrNormal${s};
uniform vec3 rhrTint${s};
uniform float rhrScale${s};
uniform float rhrRough${s};
uniform float rhrUsed${s};
uniform float rhrCarpetMask${s};`).join('\n');
    const sample = slots.map(s => `
  vec4 rhrC${s} = texture2D( rhrColor${s}, vMapUv * rhrScale${s} );
  float rhrA${s} = rhrUsed${s} > 0.5 ? vRhrW[${s}] + rhrBlendH * ( rhrC${s}.a - 0.5 ) + rhrBlendN * rhrNoise( vMapUv * ${TERRAIN_TILE_STUDS.toFixed(1)} + vec2( ${17.3 * s}, ${31.7 * s} ) ) : -10.0;`).join('');
    const top = slots.map(s => `rhrA${s}`).reduce((x, y) => `max( ${x}, ${y} )`);
    const weights = slots.map(s => `
  rhrB[${s}] = max( rhrA${s} - rhrTop + rhrBlendD, 0.0 );`).join('');
    const mixColor = slots.map(s => `rhrB[${s}] * rhrC${s}.rgb * rhrTint${s} * mix( vec3( 1.0 ), rhrCarpet, rhrCarpetMask${s} * rhrCarpetNear )`).join(' + ');
    const mixNormal = slots.map(s => `rhrB[${s}] * ( texture2D( rhrNormal${s}, vMapUv * rhrScale${s} ).xyz * 2.0 - 1.0 )`).join(' + ');
    const mixRough = slots.map(s => `rhrB[${s}] * rhrRough${s}`).join(' + ');
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>
varying vec4 vRhrW;
uniform float rhrBlendH;
uniform float rhrBlendD;
uniform float rhrBlendN;
uniform vec3 rhrCarpet;
uniform vec2 rhrCarpetRange;
${declarations}
// Value noise in studs, two octaves (1 and 1/2 stud), about -0.5..0.5.
float rhrHash( vec2 p ) { return fract( sin( dot( p, vec2( 127.1, 311.7 ) ) ) * 43758.5453 ); }
float rhrValue( vec2 p ) {
  vec2 i = floor( p ), f = fract( p );
  f = f * f * ( 3.0 - 2.0 * f );
  return mix( mix( rhrHash( i ), rhrHash( i + vec2( 1.0, 0.0 ) ), f.x ), mix( rhrHash( i + vec2( 0.0, 1.0 ) ), rhrHash( i + vec2( 1.0, 1.0 ) ), f.x ), f.y );
}
float rhrNoise( vec2 p ) { return 0.67 * rhrValue( p ) + 0.33 * rhrValue( p * 2.0 + 5.2 ) - 0.5; }`)
      .replace('#include <map_fragment>', `
vec4 rhrB;
{${sample}
  float rhrTop = ${top};${weights}
  float rhrCarpetNear = 1.0 - smoothstep( rhrCarpetRange.x, rhrCarpetRange.y, length( vViewPosition ) );
  rhrB /= max( rhrB.x + rhrB.y + rhrB.z + rhrB.w, 1e-5 );
  diffuseColor.rgb *= ${mixColor};
}`)
      .replace('#include <roughnessmap_fragment>', `#include <roughnessmap_fragment>
roughnessFactor = ${mixRough};`)
      .replace('#include <normal_fragment_maps>', THREE.ShaderChunk.normal_fragment_maps.replace(
        'vec3 mapN = texture2D( normalMap, vNormalMapUv ).xyz * 2.0 - 1.0;',
        `vec3 mapN = normalize( ${mixNormal} );`));
  };
  material.customProgramCacheKey = () => 'rhr-terrain-blend';
  return material;
}

async function addTerrain(index) {
  if (!nodesOfClass(index, 'Terrain').length) return;
  let terrain;
  try {
    const response = await fetch('/__rhr_terrain__.json');
    terrain = response.ok ? await response.json() : null;
  } catch (_) {
    terrain = null;
  }
  if (!terrain || !terrain.chunks?.length) return;
  const n = terrain.chunkSize;
  const names = terrain.materials;
  const WATER = names.indexOf('Water');
  const chunks = new Map();
  for (const chunk of terrain.chunks) {
    chunks.set(chunk.position.join(','), {
      position: chunk.position,
      materials: base64Bytes(chunk.materials),
      occupancy: base64Bytes(chunk.occupancy),
    });
  }
  const terrainNode = nodesOfClass(index, 'Terrain')[0];
  const solid = m => m !== 0 && m !== WATER;
  terrainGrid = {chunks, n, voxelStuds: terrain.voxelStuds, solid};
  const ground = terrainSurface(chunks, n, terrain.voxelStuds, solid, m => !solid(m));
  const water = terrainSurface(chunks, n, terrain.voxelStuds, m => m === WATER, m => m === 0);
  water.vertexMaterials = null;
  const canonicalKind = await terrainKindCanon(index, names);
  terrainLookCache.clear();
  const decoration = terrainNode?.props?.Decoration === true && TUNE.gOn > 0;
  const GRASS_ID = names.indexOf('Grass');
  const jobs = [];
  let triangles = 0;
  let blendTriangles = 0;
  const materialsDrawn = new Set();
  for (const part of [...terrainGeometries(ground, terrainKindWeights, canonicalKind), ...terrainGeometries(water, () => [['top', 1]])]) {
    const name = names[part.material];
    const isWater = part.material === WATER;
    for (const layer of part.blend || [part]) materialsDrawn.add(names[layer.material]);
    triangles += part.triangles;
    if (part.blend) {
      blendTriangles += part.triangles;
      const mesh = new THREE.Mesh(part.geometry, new THREE.MeshStandardMaterial({color: 0x808080, roughness: 0.95, metalness: 0}));
      mesh.receiveShadow = true;
      mesh.castShadow = true;
      mesh.userData.rhrNode = terrainNode;
      mesh.userData.rhrTerrain = [...new Set(part.blend.map(layer => names[layer.material]))].join('+');
      scene.add(mesh);
      jobs.push((async () => {
        const looks = await Promise.all(part.blend.map(layer => terrainLook(index, terrain, names[layer.material], layer.kind)));
        mesh.material.dispose();
        const carpet = part.blend.map(layer => decoration && layer.material === GRASS_ID && layer.kind === 'top');
        mesh.material = terrainBlendMaterial(looks, carpet);
      })());
      continue;
    }
    const color = isWater
      ? colorValue(terrainNode?.props?.WaterColor, 0x0c545c)
      : new THREE.Color().setRGB(...(terrain.colors?.[name] || [128, 128, 128]).map(c => c / 255), THREE.SRGBColorSpace);
    const meshMaterial = new THREE.MeshStandardMaterial({
      color,
      roughness: isWater ? 0.15 : 0.95,
      metalness: 0,
      transparent: isWater,
      opacity: isWater ? 0.6 : 1,
      depthWrite: !isWater,
    });
    if (isWater) wantsEnvironment(meshMaterial);
    const mesh = new THREE.Mesh(part.geometry, meshMaterial);
    mesh.receiveShadow = true;
    mesh.castShadow = !isWater;
    mesh.userData.rhrNode = terrainNode;
    mesh.userData.rhrTerrain = name;
    scene.add(mesh);
    const carpet = decoration && part.material === GRASS_ID && part.kind === 'top';
    if (isWater || flatMaterials) {
      if (carpet) withGrassCarpet(meshMaterial);
      continue;
    }
    jobs.push(terrainLook(index, terrain, name, part.kind).then(look => {
      applyTerrainLook(meshMaterial, mesh, look);
      if (carpet) withGrassCarpet(meshMaterial);
    }));
  }
  await Promise.all(jobs);
  terrainSummary = {triangles, blendTriangles, materials: [...materialsDrawn]};
  const GRASS = names.indexOf('Grass');
  if (decoration && GRASS > 0) {
    const raw = terrain.rawColors?.Grass || terrain.defaultColors?.Grass || [111, 126, 62];
    terrainGrassSource = {
      surface: ground, grass: GRASS, node: terrainNode,
      length: Math.max(0.1, Math.min(1, Number(terrainNode.props.GrassLength ?? 0.7))),
      color: new THREE.Color().setRGB(raw[0] / 255, raw[1] / 255, raw[2] / 255, THREE.SRGBColorSpace),
    };
  }
}

// Terrain grass (Terrain.Decoration), measured in Studio at the highest quality with
// GrassLength 0.7: thin blades on the Grass material's top faces only, 1.6 to 3.35
// studs tall at the tip (median 2.5), leaning up to about 45 degrees in any
// direction, spread evenly (not in clumps), casting shadows. Their colour is the
// place's Grass MaterialColor, lit like the ground under them and about 0.6 as bright
// as a flat surface of that colour. Studio draws them all out to about 100 studs from
// the camera, fewer and fewer after that, and none past about 290 (RHR fades them out
// sooner, TUNE.gNear..gFar, which matches a whole field better). Roblox sways them
// (also with no wind); RHR draws them at rest. GrassLength scales their length
// (0.1..1; Roblox also changes their density with it, by an amount not measured).
// Up close Studio's grass reads as a carpet: in a top-down view with decoration on,
// 95% of the pixels change and the whole field comes out about the blades' colour,
// ground between the blades included (on/off pixel ratio R 0.58, G 0.62, B 0.44). So
// with decoration on, the Grass top texture is darkened toward the blade colour too,
// fading out between TUNE.gCarpetNear and gCarpetFar studs from the camera (fitted to
// the change decoration makes in Studio: top-down, at 30 degrees, and over the hills,
// per band of distance). The blades themselves fade between gNear and gFar, fitted
// the same way; on a lone strip Studio still draws a few out to about 260 studs.
function grassCarpetColor() {
  // Linear multipliers for the on/off screen ratio, scaled by TUNE.gCarpet.
  const k = TUNE.gCarpet;
  return new THREE.Color(1 - k * (1 - 0.30), 1 - k * (1 - 0.35), 1 - k * (1 - 0.16));
}

function withGrassCarpet(material) {
  const previous = material.onBeforeCompile;
  const previousKey = material.customProgramCacheKey;
  const carpet = grassCarpetColor();
  material.onBeforeCompile = (shader, renderer) => {
    if (previous) previous.call(material, shader, renderer);
    shader.uniforms.rhrCarpet = {value: carpet};
    shader.uniforms.rhrCarpetRange = {value: new THREE.Vector2(TUNE.gCarpetNear, TUNE.gCarpetFar)};
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>
uniform vec3 rhrCarpet;
uniform vec2 rhrCarpetRange;`)
      .replace('#include <map_fragment>', `#include <map_fragment>
diffuseColor.rgb *= mix( rhrCarpet, vec3( 1.0 ), smoothstep( rhrCarpetRange.x, rhrCarpetRange.y, length( vViewPosition ) ) );`);
  };
  material.customProgramCacheKey = () => `${previousKey ? previousKey.call(material) : ''}|rhr-carpet`;
  material.needsUpdate = true;
}

function grassHash(a, b, c) {
  let h = Math.imul(a | 0, 0x27d4eb2d) ^ Math.imul(b | 0, 0x165667b1) ^ Math.imul(c | 0, 0x9e3779b1);
  h = Math.imul(h ^ (h >>> 15), 0x85ebca6b);
  h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

function addTerrainGrass(camera) {
  const source = terrainGrassSource;
  if (!source || !camera) return;
  const {surface, grass} = source;
  const {positions, normals, quads, vertexMaterials} = surface;
  const scale = source.length / 0.7;
  const eye = camera.position;
  const out = [];
  const shades = [];
  let blades = 0;
  const p = new THREE.Vector3(), mid = new THREE.Vector3(), tip = new THREE.Vector3(), across = new THREE.Vector3();
  const corner = i => [positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2]];
  // Which faces are tops (face normal within ~45 degrees of up), and per edge whether
  // every face on it is one: an edge with a non-top face beside it is where the ground
  // turns down.
  const faceUp = quad => {
    const [a, b, c, d] = quad;
    const e1 = [positions[c * 3] - positions[a * 3], positions[c * 3 + 1] - positions[a * 3 + 1], positions[c * 3 + 2] - positions[a * 3 + 2]];
    const e2 = [positions[d * 3] - positions[b * 3], positions[d * 3 + 1] - positions[b * 3 + 1], positions[d * 3 + 2] - positions[b * 3 + 2]];
    const n = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]];
    return n[1] / (Math.hypot(...n) || 1);
  };
  const edgeKey = (i, j) => (i < j ? `${i}_${j}` : `${j}_${i}`);
  const edgeTop = new Map();  // edge -> true while every face on it is a top
  for (const quad of quads) {
    const top = faceUp(quad) > 0.7;
    for (let e = 0; e < 4; e += 1) {
      const key = edgeKey(quad[e], quad[(e + 1) % 4]);
      edgeTop.set(key, (edgeTop.get(key) ?? true) && top);
    }
  }
  const seen = new Map();
  for (const quad of quads) for (let e = 0; e < 4; e += 1) {
    const key = edgeKey(quad[e], quad[(e + 1) % 4]);
    seen.set(key, (seen.get(key) || 0) + 1);
  }
  for (const quad of quads) {
    const [a, b, c, d] = quad;
    // Grass top weight per corner: the corner is grass, and its normal counts as top.
    const weight = [a, b, c, d].map(i => (vertexMaterials[i] === grass ? THREE.MathUtils.smoothstep(normals[i * 3 + 1], ...TERRAIN_KIND_BAND) : 0));
    if (Math.max(...weight) < 0.5) continue;
    // Edges where the ground turns down: Roblox rounds them and grows no grass on the
    // rounding, so blades keep gMargin away.
    const border = [[a, b], [b, c], [c, d], [d, a]].map(([i, j]) => {
      const key = edgeKey(i, j);
      return !edgeTop.get(key) || (seen.get(key) || 0) < 2;
    });
    const [ax, ay, az] = corner(a), [bx, by, bz] = corner(b), [cx, cy, cz] = corner(c), [dx, dy, dz] = corner(d);
    const side = [Math.hypot(bx - ax, bz - az), Math.hypot(cx - bx, cz - bz), Math.hypot(dx - cx, dz - cz), Math.hypot(ax - dx, az - dz)];
    const mx = (ax + bx + cx + dx) / 4, my = (ay + by + cy + dy) / 4, mz = (az + bz + cz + dz) / 4;
    const distance = Math.hypot(mx - eye.x, my - eye.y, mz - eye.z);
    if (distance > TUNE.gFar + 4) continue;
    // Area from the diagonals.
    const e1 = [cx - ax, cy - ay, cz - az], e2 = [dx - bx, dy - by, dz - bz];
    const area = 0.5 * Math.hypot(e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]);
    const seedX = Math.round(mx * 4), seedY = Math.round(my * 4), seedZ = Math.round(mz * 4);
    const wanted = area * TUNE.gDensity;
    const count = Math.floor(wanted + grassHash(seedX, seedY, seedZ));
    for (let k = 0; k < count; k += 1) {
      const r = n => grassHash(seedX + 7919 * k, seedY + 104729 * n, seedZ + 1299709 * k + n);
      const u = r(1), v = r(2);
      // Bilinear point on the face and the grass weight there.
      const w = weight[0] * (1 - u) * (1 - v) + weight[1] * u * (1 - v) + weight[2] * u * v + weight[3] * (1 - u) * v;
      if (w < 0.5) continue;
      // Distance (studs) to each bordering edge: a-b is v = 0, b-c u = 1, c-d v = 1, d-a u = 0.
      const gaps = [v * side[3], (1 - u) * side[0], (1 - v) * side[1], u * side[2]];
      if ((border[0] && gaps[0] < TUNE.gMargin) || (border[1] && gaps[1] < TUNE.gMargin)
        || (border[2] && gaps[2] < TUNE.gMargin) || (border[3] && gaps[3] < TUNE.gMargin)) continue;
      p.set(
        ax * (1 - u) * (1 - v) + bx * u * (1 - v) + cx * u * v + dx * (1 - u) * v,
        ay * (1 - u) * (1 - v) + by * u * (1 - v) + cy * u * v + dy * (1 - u) * v,
        az * (1 - u) * (1 - v) + bz * u * (1 - v) + cz * u * v + dz * (1 - u) * v,
      );
      // Fewer blades with distance: each has a fixed rank and is kept while the
      // share drawn at its distance is above it.
      const share = 1 - THREE.MathUtils.smoothstep(p.distanceTo(eye), TUNE.gNear, TUNE.gFar);
      if (r(3) >= share) continue;
      // Two segments: the lower half leans a little, the upper half bends further
      // over, the way the blade's flat face points (seen from above, a bent blade
      // shows its face).
      const length = (TUNE.gMin + (TUNE.gMax - TUNE.gMin) * r(4)) * scale;
      const lean = THREE.MathUtils.degToRad(TUNE.gLean) * Math.sqrt(r(5));
      const bend = lean + THREE.MathUtils.degToRad(TUNE.gBend) * r(7);
      const heading = 2 * Math.PI * r(6);
      const hx = Math.cos(heading), hz = Math.sin(heading);
      mid.set(hx * Math.sin(lean), Math.cos(lean), hz * Math.sin(lean)).multiplyScalar(length / 2).add(p);
      tip.set(hx * Math.sin(bend), Math.cos(bend), hz * Math.sin(bend)).multiplyScalar(length / 2).add(mid);
      const half = 0.5 * TUNE.gWidth * (0.7 + 0.6 * r(8));
      across.set(-hz * half, 0, hx * half);
      const bl = [p.x - across.x, p.y, p.z - across.z], br = [p.x + across.x, p.y, p.z + across.z];
      const ml = [mid.x - 0.55 * across.x, mid.y, mid.z - 0.55 * across.z], mr = [mid.x + 0.55 * across.x, mid.y, mid.z + 0.55 * across.z];
      const top = [tip.x, tip.y, tip.z];
      out.push(
        ...bl, ...br, ...mr, ...bl, ...mr, ...ml, ...ml, ...mr, ...top,
        ...br, ...bl, ...mr, ...mr, ...bl, ...ml, ...mr, ...ml, ...top,
      );
      // Blades differ in brightness: in Studio's pixels the darkest tenth is 0.83 and
      // the brightest tenth 1.3 of the median blade (screen values; linear here).
      const shade = ((0.82 + 0.58 * r(9) ** 2.2) / 0.95) ** 2.2;
      for (let k2 = 0; k2 < 18; k2 += 1) shades.push(shade, shade, shade);
      blades += 1;
    }
  }
  if (!blades) return;
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(out, 3));
  // Lit as the ground under them: every blade faces up, on both sides.
  const up = new Float32Array(out.length);
  for (let i = 1; i < up.length; i += 3) up[i] = 1;
  geometry.setAttribute('normal', new THREE.BufferAttribute(up, 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(shades, 3));
  const material = new THREE.MeshStandardMaterial({
    color: source.color.clone().multiply(new THREE.Color(TUNE.gShadeR, TUNE.gShadeG, TUNE.gShadeB)), roughness: 1, metalness: 0,
    vertexColors: true,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  mesh.userData.rhrNode = source.node;
  mesh.userData.rhrTerrain = 'Grass decoration';
  scene.add(mesh);
  if (terrainSummary) terrainSummary.grassBlades = blades;
}

// Characters. A rig is a Model with a Humanoid; what it wears is painted onto its body
// the way Roblox does it, with the layouts that ship in the Studio install
// (content/avatar/compositing): each layout is a flat mesh whose positions are pixels
// of the body's texture and whose UVs point into a clothing template (585x559).
// Pants, then the Shirt, then the ShirtGraphic (the template's torso front) are
// painted in that order into a render target, and the body parts draw it over their
// own colour with their own UVs.
//
// R6: one 1024x512 texture for the body, drawn on the install's R6 body part meshes
// (content/avatar/meshes, boxes with rounded edges), or on a CharacterMesh's mesh
// (a body package) for the parts it replaces. The head is not part of it.
// R15: a texture per body part: the torso's layout is 388x272, an arm's or a leg's
// 264x284 (legs use the arm layouts with the Pants template), drawn with the body
// part MeshPart's UVs. A part with its own TextureID (a body package) wears none.
const AVATAR = 'rbxasset://avatar/';
const R6_BODY = {
  Torso: {mesh: 'torso', bodyPart: 'Torso', color: 'TorsoColor3'},
  'Left Arm': {mesh: 'leftarm', bodyPart: 'LeftArm', color: 'LeftArmColor3'},
  'Right Arm': {mesh: 'rightarm', bodyPart: 'RightArm', color: 'RightArmColor3'},
  'Left Leg': {mesh: 'leftleg', bodyPart: 'LeftLeg', color: 'LeftLegColor3'},
  'Right Leg': {mesh: 'rightleg', bodyPart: 'RightLeg', color: 'RightLegColor3'},
  Head: {color: 'HeadColor3'},
};
const R15_LAYOUTS = {
  torso: {mesh: 'R15CompositTorsoBase', width: 388, height: 272},
  left: {mesh: 'R15CompositLeftArmBase', width: 264, height: 284},
  right: {mesh: 'R15CompositRightArmBase', width: 264, height: 284},
};
// Body part -> [layout, templates painted through it, BodyColors property]
const R15_BODY = {
  UpperTorso: ['torso', ['pants', 'shirt', 'graphic'], 'TorsoColor3'],
  LowerTorso: ['torso', ['pants', 'shirt', 'graphic'], 'TorsoColor3'],
  LeftUpperArm: ['left', ['shirt'], 'LeftArmColor3'],
  LeftLowerArm: ['left', ['shirt'], 'LeftArmColor3'],
  LeftHand: ['left', ['shirt'], 'LeftArmColor3'],
  RightUpperArm: ['right', ['shirt'], 'RightArmColor3'],
  RightLowerArm: ['right', ['shirt'], 'RightArmColor3'],
  RightHand: ['right', ['shirt'], 'RightArmColor3'],
  LeftUpperLeg: ['left', ['pants'], 'LeftLegColor3'],
  LeftLowerLeg: ['left', ['pants'], 'LeftLegColor3'],
  LeftFoot: ['left', ['pants'], 'LeftLegColor3'],
  RightUpperLeg: ['right', ['pants'], 'RightLegColor3'],
  RightLowerLeg: ['right', ['pants'], 'RightLegColor3'],
  RightFoot: ['right', ['pants'], 'RightLegColor3'],
  Head: [null, [], 'HeadColor3'],
};
// Painted at twice the layout's size: the templates' own detail survives filtering.
const CLOTHING_SCALE = 2;
let charactersDressed = 0;
let layeredClothingFitted = 0;
// Character parts whose decals Roblox does not draw (see dressCharacters).
const partsWithoutDecals = new Set();
// The clothing images painted for this render (render targets, freed by resetScene).
const clothingTargets = [];

function childOfClass(node, className) {
  return Object.values(node?.children || {}).find(child => child.className === className) || null;
}

function childNamed(node, name) {
  return Object.values(node?.children || {}).find(child => child.name === name) || null;
}

// What a rig wears, as images in paint order: {pants, shirt, graphic} -> {texture, color}.
async function clothingLayers(model) {
  const layers = {};
  const pants = childOfClass(model, 'Pants');
  const shirt = childOfClass(model, 'Shirt');
  const graphic = childOfClass(model, 'ShirtGraphic');
  const load = async (clothing, property) => {
    const texture = clothing?.props?.[property] ? await loadSceneTexture(clothing.props[property]) : null;
    return texture ? {texture, color: colorValue(clothing.props?.Color3)} : null;
  };
  layers.pants = await load(pants, 'PantsTemplate');
  layers.shirt = await load(shirt, 'ShirtTemplate');
  const image = await load(graphic, 'Graphic');
  if (image?.texture.image) {
    // A T-shirt image covers the template's torso front (231, 74, 128x128): drawn into
    // a template-sized image, it goes through the same layout as the shirt.
    const canvas = document.createElement('canvas');
    canvas.width = 585;
    canvas.height = 559;
    canvas.getContext('2d').drawImage(image.texture.image, 231, 74, 128, 128);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    layers.graphic = {texture, color: image.color};
  }
  return layers;
}

// Paint images through layouts into a new texture (premultiplied alpha, linear).
// items: [{geometry, texture, color}] in paint order; geometry positions are pixels.
function paintLayout(width, height, items) {
  const target = new THREE.WebGLRenderTarget(width * CLOTHING_SCALE, height * CLOTHING_SCALE, {
    type: THREE.HalfFloatType,
    depthBuffer: false,
  });
  clothingTargets.push(target);
  const camera = new THREE.OrthographicCamera(0, width, height, 0, -1000, 1000);
  const canvasScene = new THREE.Scene();
  items.forEach((item, order) => {
    const material = new THREE.MeshBasicMaterial({
      map: item.texture,
      color: item.color || new THREE.Color(0xffffff),
      transparent: true,
      depthTest: false,
      depthWrite: false,
      side: THREE.DoubleSide,
      toneMapped: false,
    });
    const mesh = new THREE.Mesh(item.geometry, material);
    mesh.renderOrder = order;
    canvasScene.add(mesh);
  });
  const previousTarget = renderer.getRenderTarget();
  const clearColor = renderer.getClearColor(new THREE.Color());
  const clearAlpha = renderer.getClearAlpha();
  renderer.setRenderTarget(target);
  renderer.setClearColor(0x000000, 0);
  renderer.clear();
  renderer.render(canvasScene, camera);
  renderer.setRenderTarget(previousTarget);
  renderer.setClearColor(clearColor, clearAlpha);
  canvasScene.traverse(object => object.material?.dispose());
  return target.texture;
}

// The whole image over a layout's full area (a body part's own TextureID, a package's
// base texture).
function fullLayoutQuad(width, height) {
  const geometry = new THREE.PlaneGeometry(width, height);
  geometry.translate(width / 2, height / 2, 0);
  return geometry;
}

// A body part's material, with the clothing texture over its colour.
function dressPart(mesh, texture) {
  const base = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material;
  const material = base.clone();
  material.map = null;
  material.normalMap = null;
  material.roughnessMap = null;
  material.metalnessMap = null;
  material.onBeforeCompile = () => {};
  material.customProgramCacheKey = () => '';
  useOverlayMap(material, texture, true);
  mesh.material = material;
}

function applyBodyColors(model, table) {
  const colors = childOfClass(model, 'BodyColors')?.props;
  if (!colors) return;
  for (const [name, entry] of Object.entries(table)) {
    const property = Array.isArray(entry) ? entry[2] : entry.color;
    const mesh = meshByNode.get(childNamed(model, name));
    if (!mesh || !colors[property]) continue;
    for (const material of [mesh.material].flat()) material.color.copy(colorValue(colors[property]));
  }
}

async function dressR6(model, layers) {
  const charMeshes = Object.values(model.children || {}).filter(child => child.className === 'CharacterMesh');
  const items = [];
  const layout = async name => loadMeshGeometry(`${AVATAR}compositing/${name}.mesh`);
  const idUri = id => (/^\d+$/.test(String(id)) ? `rbxassetid://${id}` : id);
  const textureId = id => (id && String(id) !== '0' ? idUri(id) : null);
  const pantsLayout = layers.pants ? await layout('CompositPantsTemplate') : null;
  const shirtLayout = layers.shirt || layers.graphic ? await layout('CompositShirtTemplate') : null;
  const clothing = [];
  if (pantsLayout) clothing.push({geometry: pantsLayout, ...layers.pants});
  if (shirtLayout && layers.shirt) clothing.push({geometry: shirtLayout, ...layers.shirt});
  if (shirtLayout && layers.graphic) clothing.push({geometry: shirtLayout, ...layers.graphic});
  const atlas = clothing.length ? paintLayout(1024, 512, clothing) : null;
  // A package part's own images (base under, overlay over) replace the clothing on
  // it, as on R15 (Studio: a package's vest shows, the Shirt and T-shirt do not).
  const packageAtlas = new Map();
  const packageTexture = async charMesh => {
    const ids = [textureId(charMesh?.props?.BaseTextureId), textureId(charMesh?.props?.OverlayTextureId)].filter(Boolean);
    if (!ids.length) return null;
    const key = ids.join('|');
    if (!packageAtlas.has(key)) {
      const images = (await Promise.all(ids.map(id => loadSceneTexture(id)))).filter(Boolean);
      packageAtlas.set(key, images.length
        ? paintLayout(1024, 512, images.map(texture => ({geometry: fullLayoutQuad(1024, 512), texture})))
        : null);
    }
    return packageAtlas.get(key);
  };
  let dressed = false;
  for (const [name, entry] of Object.entries(R6_BODY)) {
    if (!entry.mesh) continue;
    const node = childNamed(model, name);
    const mesh = meshByNode.get(node);
    if (!mesh || !['Part', 'MeshPart'].includes(node.className) || specialMeshChild(node)) continue;
    const charMesh = charMeshes.find(c => c.props?.BodyPart?.name === entry.bodyPart);
    const packaged = charMesh?.props?.MeshId && String(charMesh.props.MeshId) !== '0';
    const base = packaged
      ? await loadMeshGeometry(idUri(charMesh.props.MeshId))
      : await loadMeshGeometry(`${AVATAR}meshes/${entry.mesh}.mesh`);
    if (!base) continue;
    // A package's mesh is authored in studs around the part; the plain body part mesh
    // is a unit shape the part's size stretches.
    const geometry = packaged ? base.clone() : fitMeshGeometryToPart(base, node.props?.Size);
    mesh.geometry.dispose();
    mesh.geometry = geometry;
    mesh.userData.rhrMeshAsset = packaged ? meshAssetId(idUri(charMesh.props.MeshId)) : `r6-${entry.mesh}`;
    const own = await packageTexture(charMesh);
    // Nor the T-shirt image Roblox also puts on the torso as its "roblox" decal.
    if (own) partsWithoutDecals.add(node);
    const texture = own || atlas;
    if (texture) dressPart(mesh, texture);
    else if (Array.isArray(mesh.material)) mesh.material = mesh.material[0];
    dressed = true;
  }
  return dressed;
}

async function dressR15(model, layers) {
  const layoutGeometry = {};
  let dressed = false;
  for (const [name, [layoutName, templates]] of Object.entries(R15_BODY)) {
    if (!layoutName) continue;
    const node = childNamed(model, name);
    const mesh = meshByNode.get(node);
    if (!mesh || node.className !== 'MeshPart' || !mesh.userData.rhrMeshAsset || surfaceAppearanceOf(node)) continue;
    // A body part with its own image (a body package's) wears no classic clothing
    // (Studio: clearing a package torso's TextureID brings the Shirt back).
    if (node.props?.TextureID) continue;
    const worn = templates.filter(template => layers[template]);
    if (!worn.length) continue;
    const spec = R15_LAYOUTS[layoutName];
    if (!(layoutName in layoutGeometry)) layoutGeometry[layoutName] = await loadMeshGeometry(`${AVATAR}compositing/${spec.mesh}.mesh`);
    const layout = layoutGeometry[layoutName];
    if (!layout) continue;
    const items = worn.map(template => ({geometry: layout, ...layers[template]}));
    dressPart(mesh, paintLayout(spec.width, spec.height, items));
    dressed = true;
  }
  return dressed;
}

// Layered clothing. An item (an Accessory whose Handle has a WrapLayer) is modelled
// around a reference body, its ReferenceMesh cage; every body part carries a cage of
// its own (its WrapTarget). All of Roblox's cages share one layout: the same points
// with the same UVs (checked: an item's 5410-point reference cage and the 15 body part
// cages of an R15 rig, 1709 distinct UVs, match one to one). Each point of the item's
// reference cage is paired with the body's point of the same UV, and every vertex of
// the item moves by the distance-weighted offsets of its nearest reference points, so
// the item follows how this body differs from the one it was made on.
//
// Layers are fitted in their Order, each onto what is under it, as Roblox does: once
// a layer is fitted, its own outer cage (CageMeshId), moved the same way, is the
// surface the next layer is fitted to.
const CAGE_NEIGHBOURS = 8;

// Anchors ([x, y, z, dx, dy, dz]) in a grid of CAGE_CELL-stud cells, so a point only
// looks at the anchors around it.
const CAGE_CELL = 0.5;
// A cell's number, exact in a double: cells within 2^16 of the origin (32768 studs)
// are distinct; further out two cells can share a number, which only adds anchors to
// look at, never loses one.
function cageCell(x, y, z) {
  const wrap = n => (((n + 65536) % 131072) + 131072) % 131072;
  return (wrap(x) * 131072 + wrap(y)) * 131072 + wrap(z);
}

function anchorGrid(anchors) {
  const cells = new Map();
  for (const anchor of anchors) {
    const key = cageCell(Math.floor(anchor[0] / CAGE_CELL), Math.floor(anchor[1] / CAGE_CELL), Math.floor(anchor[2] / CAGE_CELL));
    if (!cells.has(key)) cells.set(key, []);
    cells.get(key).push(anchor);
  }
  return {cells, all: anchors, found: []};
}

// The anchors in the cells around a point: rings of cells outwards until there are
// enough, plus one more ring so a nearer anchor just across a cell edge is not missed.
function anchorsNear(grid, p) {
  const cx = Math.floor(p.x / CAGE_CELL), cy = Math.floor(p.y / CAGE_CELL), cz = Math.floor(p.z / CAGE_CELL);
  const found = grid.found;
  found.length = 0;
  for (let ring = 0, extra = -1; ring <= 8; ring += 1) {
    for (let x = cx - ring; x <= cx + ring; x += 1) {
      for (let y = cy - ring; y <= cy + ring; y += 1) {
        for (let z = cz - ring; z <= cz + ring; z += 1) {
          if (Math.max(Math.abs(x - cx), Math.abs(y - cy), Math.abs(z - cz)) !== ring) continue;
          const cell = grid.cells.get(cageCell(x, y, z));
          if (cell) for (const anchor of cell) found.push(anchor);
        }
      }
    }
    if (extra < 0 && found.length >= CAGE_NEIGHBOURS) extra = ring + 1;
    if (ring === extra) return found;
  }
  return found.length >= CAGE_NEIGHBOURS ? found : grid.all;
}

// Moves a point by the distance-weighted offsets of its nearest anchors; `nearest` is
// scratch space.
function cageOffset(p, grid, nearest) {
  nearest.fill(null);
  for (const anchor of anchorsNear(grid, p)) {
    const dx = anchor[0] - p.x, dy = anchor[1] - p.y, dz = anchor[2] - p.z;
    const d = dx * dx + dy * dy + dz * dz;
    if (nearest[CAGE_NEIGHBOURS - 1] && d >= nearest[CAGE_NEIGHBOURS - 1][0]) continue;
    let k = CAGE_NEIGHBOURS - 1;
    while (k > 0 && (!nearest[k - 1] || d < nearest[k - 1][0])) {
      nearest[k] = nearest[k - 1];
      k -= 1;
    }
    nearest[k] = [d, anchor];
  }
  let wx = 0, wy = 0, wz = 0, total = 0;
  for (const entry of nearest) {
    if (!entry) continue;
    const weight = 1 / (entry[0] * entry[0] + 1e-8);
    wx += entry[1][3] * weight;
    wy += entry[1][4] * weight;
    wz += entry[1][5] * weight;
    total += weight;
  }
  return p.set(p.x + wx / total, p.y + wy / total, p.z + wz / total);
}

function uvKey(u, v) {
  return `${Math.round(u * 4096)},${Math.round(v * 4096)}`;
}

// A cage's points in world space: part CFrame x cage origin, scaled as the part's
// mesh is scaled to its Size.
function cagePoints(geometry, partNode, origin, scale) {
  const matrix = cframeMatrix(partNode.props.CFrame)
    .multiply(new THREE.Matrix4().makeScale(scale.x, scale.y, scale.z))
    .multiply(origin ? cframeMatrix(origin) : new THREE.Matrix4());
  const position = geometry.attributes.position;
  const uv = geometry.attributes.uv1 || geometry.attributes.uv;
  const points = [];
  const p = new THREE.Vector3();
  for (let i = 0; i < position.count; i += 1) {
    p.fromBufferAttribute(position, i).applyMatrix4(matrix);
    points.push({key: uvKey(uv.getX(i), uv.getY(i)), x: p.x, y: p.y, z: p.z});
  }
  return points;
}

// How a part's mesh was stretched to its Size (fitMeshGeometryToPart).
async function meshScale(node) {
  const base = node.props?.MeshId ? await loadMeshGeometry(node.props.MeshId) : null;
  if (!base) return new THREE.Vector3(1, 1, 1);
  base.computeBoundingBox();
  const raw = base.boundingBox.getSize(new THREE.Vector3());
  const [x, y, z] = dimensions(node.props?.Size);
  return new THREE.Vector3(x / Math.max(raw.x, 1e-6), y / Math.max(raw.y, 1e-6), z / Math.max(raw.z, 1e-6));
}

async function fitLayeredClothing(model) {
  const children = Object.values(model.children || {});
  const items = children
    .filter(child => child.className === 'Accessory')
    .map(accessory => childNamed(accessory, 'Handle'))
    .filter(handle => handle?.className === 'MeshPart' && childOfClass(handle, 'WrapLayer') && meshByNode.get(handle)?.userData.rhrMeshAsset)
    .sort((a, b) => Number(childOfClass(a, 'WrapLayer').props?.Order ?? 0) - Number(childOfClass(b, 'WrapLayer').props?.Order ?? 0));
  if (!items.length) return 0;
  // The body's cage, by UV.
  const body = new Map();
  for (const part of children) {
    const target = childOfClass(part, 'WrapTarget');
    if (part.className !== 'MeshPart' || !target?.props?.CageMeshId || !part.props?.CFrame) continue;
    const cage = await loadMeshGeometry(target.props.CageMeshId);
    if (!cage) continue;
    for (const point of cagePoints(cage, part, target.props.CageOrigin, await meshScale(part))) {
      if (!body.has(point.key)) body.set(point.key, point);
    }
  }
  if (!body.size) return 0;
  let fitted = 0;
  for (const handle of items) {
    const layer = childOfClass(handle, 'WrapLayer');
    const reference = layer.props?.ReferenceMeshId ? await loadMeshGeometry(layer.props.ReferenceMeshId) : null;
    if (!reference) continue;
    const scale = await meshScale(handle);
    // Reference points with their offsets onto the body, one per UV.
    const seen = new Set();
    const anchors = [];
    for (const point of cagePoints(reference, handle, layer.props.ReferenceOrigin, scale)) {
      const onBody = body.get(point.key);
      if (!onBody || seen.has(point.key)) continue;
      seen.add(point.key);
      anchors.push([point.x, point.y, point.z, onBody.x - point.x, onBody.y - point.y, onBody.z - point.z]);
    }
    if (anchors.length < CAGE_NEIGHBOURS) continue;
    const grid = anchorGrid(anchors);
    const mesh = meshByNode.get(handle);
    const toWorld = cframeMatrix(handle.props.CFrame);
    const toLocal = toWorld.clone().invert();
    const geometry = mesh.geometry.clone();
    const position = geometry.attributes.position;
    const p = new THREE.Vector3();
    const nearest = new Array(CAGE_NEIGHBOURS);
    for (let i = 0; i < position.count; i += 1) {
      cageOffset(p.fromBufferAttribute(position, i).applyMatrix4(toWorld), grid, nearest).applyMatrix4(toLocal);
      position.setXYZ(i, p.x, p.y, p.z);
    }
    // This layer's outer cage, fitted the same way, is what the next layer goes over.
    const outer = layer.props?.CageMeshId ? await loadMeshGeometry(layer.props.CageMeshId) : null;
    if (outer) {
      for (const point of cagePoints(outer, handle, layer.props.CageOrigin, scale)) {
        if (!body.has(point.key)) continue;
        cageOffset(p.set(point.x, point.y, point.z), grid, nearest);
        body.set(point.key, {key: point.key, x: p.x, y: p.y, z: p.z});
      }
    }
    position.needsUpdate = true;
    geometry.computeBoundingBox();
    geometry.computeBoundingSphere();
    mesh.geometry.dispose();
    mesh.geometry = geometry;
    fitted += 1;
  }
  return fitted;
}

async function dressCharacters(index) {
  for (const humanoid of nodesOfClass(index, 'Humanoid')) {
    const model = index.parentByNode.get(humanoid);
    if (!model) continue;
    const r15 = humanoid.props?.RigType?.name === 'R15' || Boolean(childNamed(model, 'UpperTorso'));
    if (r15) layeredClothingFitted += await fitLayeredClothing(model);
    if (flatMaterials) continue;
    applyBodyColors(model, r15 ? R15_BODY : R6_BODY);
    // A head with its own image (a dynamic head, its face drawn in) shows no face decal
    // (Studio: an R6 rig with a dynamic head keeps its face.png decal, not drawn).
    const head = childNamed(model, 'Head');
    if (head && meshTextureUri(head)) partsWithoutDecals.add(head);
    const layers = await clothingLayers(model);
    if (await (r15 ? dressR15(model, layers) : dressR6(model, layers))) charactersDressed += 1;
  }
}

function addNode(node, parent) {
  // Model.Scale is not applied: a saved model's parts already carry their scaled
  // CFrames and Sizes (Roblox's ScaleTo rewrites them; Scale only records the factor).
  if (['Part', 'WedgePart', 'CornerWedgePart', 'MeshPart', 'UnionOperation'].includes(node.className)) {
    addPart(node, parent);
  }
  for (const child of Object.values(node.children || {})) addNode(child, parent);
}

async function loadSceneTexture(uri) {
  const content = contentKey(uri);
  const assetId = content ? `content:${content}` : contentAssetId(uri);
  if (!assetId) return null;
  if (sceneTextureCache.has(assetId)) return sceneTextureCache.get(assetId);

  const promise = (async () => {
    const url = content ? await contentUrl(uri) : (await sceneAssetManifest)[assetId];
    if (!url) return null;
    return keep('image', url, async () => {
      const texture = await new Promise(resolve => new THREE.TextureLoader().load(url, resolve, undefined, () => resolve(null)));
      if (texture) texture.colorSpace = THREE.SRGBColorSpace;
      return texture;
    });
  })();
  sceneTextureCache.set(assetId, promise);
  return promise;
}

// A normal, roughness or metalness map: the same cached image, read as data (no sRGB).
const sceneDataTextureCache = new Map();
async function loadSceneDataTexture(uri) {
  const content = contentKey(uri);
  const assetId = content ? `content:${content}` : contentAssetId(uri);
  if (!assetId) return null;
  if (sceneDataTextureCache.has(assetId)) return sceneDataTextureCache.get(assetId);
  const promise = (async () => {
    const url = content ? await contentUrl(uri) : (await sceneAssetManifest)[assetId];
    if (!url) return null;
    return keep('image-data', url, async () => {
      const texture = await new Promise(resolve => new THREE.TextureLoader().load(url, resolve, undefined, () => resolve(null)));
      if (texture) {
        texture.colorSpace = THREE.NoColorSpace;
        texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
      }
      return texture;
    });
  })();
  sceneDataTextureCache.set(assetId, promise);
  return promise;
}

function surfaceImagePlane(parentNode, face) {
  const [sx, sy, sz] = dimensions(parentNode.props?.Size);
  const epsilon = 0.004;
  let geometry;
  let faceWidth;
  let faceHeight;
  const plane = new THREE.Group();
  if (face === 'Back') {
    faceWidth = sx; faceHeight = sy;
    geometry = new THREE.PlaneGeometry(faceWidth, faceHeight);
    plane.position.z = sz / 2 + epsilon;
  } else if (face === 'Right') {
    faceWidth = sz; faceHeight = sy;
    geometry = new THREE.PlaneGeometry(faceWidth, faceHeight);
    plane.position.x = sx / 2 + epsilon;
    plane.rotation.y = Math.PI / 2;
  } else if (face === 'Left') {
    faceWidth = sz; faceHeight = sy;
    geometry = new THREE.PlaneGeometry(faceWidth, faceHeight);
    plane.position.x = -sx / 2 - epsilon;
    plane.rotation.y = -Math.PI / 2;
  } else if (face === 'Top') {
    faceWidth = sx; faceHeight = sz;
    geometry = new THREE.PlaneGeometry(faceWidth, faceHeight);
    plane.position.y = sy / 2 + epsilon;
    // Studio: a Top decal's image top edge is at +Z and its left at +X (measured).
    plane.rotation.set(-Math.PI / 2, 0, Math.PI);
  } else if (face === 'Bottom') {
    faceWidth = sx; faceHeight = sz;
    geometry = new THREE.PlaneGeometry(faceWidth, faceHeight);
    plane.position.y = -sy / 2 - epsilon;
    plane.rotation.x = Math.PI / 2;
  } else {
    faceWidth = sx; faceHeight = sy;
    geometry = new THREE.PlaneGeometry(faceWidth, faceHeight);
    plane.position.z = -sz / 2 - epsilon;
    plane.rotation.y = Math.PI;
  }
  return {geometry, plane, faceWidth, faceHeight};
}

// A decal on a mesh (a face on an R6 head) lies on the mesh's own surface: the image
// is projected along the face's direction over the mesh's bounds, onto the triangles
// that look that way. Same orientation as on a box (surfaceImagePlane).
function projectedDecalGeometry(source, face) {
  source.computeBoundingBox();
  const size = source.boundingBox.getSize(new THREE.Vector3());
  const center = source.boundingBox.getCenter(new THREE.Vector3());
  const {plane, faceWidth, faceHeight} = surfaceImagePlane({props: {Size: {X: size.x, Y: size.y, Z: size.z}}}, face);
  plane.position.add(center);
  plane.updateMatrix();
  const toPlane = plane.matrix.clone().invert();
  const position = source.attributes.position;
  const index = source.index;
  const count = index ? index.count : position.count;
  const corners = [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()];
  const local = [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()];
  const edgeA = new THREE.Vector3();
  const edgeB = new THREE.Vector3();
  const positions = [];
  const uvs = [];
  for (let i = 0; i + 2 < count; i += 3) {
    for (let k = 0; k < 3; k += 1) {
      corners[k].fromBufferAttribute(position, index ? index.getX(i + k) : i + k);
      local[k].copy(corners[k]).applyMatrix4(toPlane);
    }
    const facing = edgeA.subVectors(local[1], local[0]).cross(edgeB.subVectors(local[2], local[0])).normalize().z;
    if (facing < 0.2) continue;
    for (let k = 0; k < 3; k += 1) {
      positions.push(corners[k].x, corners[k].y, corners[k].z);
      uvs.push(local[k].x / faceWidth + 0.5, local[k].y / faceHeight + 0.5);
    }
  }
  if (!positions.length) return null;
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  geometry.computeVertexNormals();
  return geometry;
}

async function addSurfaceImage(node, parentNode) {
  const parentMesh = meshByNode.get(parentNode);
  if (!parentMesh) return;
  const baseTexture = await loadSceneTexture(node.props?.Texture);
  if (!baseTexture) return;
  const face = node.props?.Face?.name || 'Front';
  if (parentMesh.userData.rhrMeshAsset && node.className === 'Decal') {
    const geometry = projectedDecalGeometry(parentMesh.geometry, face);
    if (!geometry) return;
    const texture = baseTexture.clone();
    texture.wrapS = texture.wrapT = THREE.ClampToEdgeWrapping;
    texture.needsUpdate = true;
    const transparency = Math.max(0, Math.min(1, Number(node.props?.Transparency ?? 0)));
    const decal = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
      map: texture,
      color: colorValue(node.props?.Color3, 0xffffff),
      roughness: 1,
      transparent: true,
      opacity: 1 - transparency,
      depthWrite: false,
      polygonOffset: true,
      polygonOffsetFactor: -2,
      polygonOffsetUnits: -2,
    }));
    decal.userData.rhrDecoration = true;
    parentMesh.add(decal);
    return;
  }
  const {geometry, plane, faceWidth, faceHeight} = surfaceImagePlane(parentNode, face);
  let texture = baseTexture;
  if (node.className === 'Texture') {
    texture = baseTexture.clone();
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.RepeatWrapping;
    const studsU = Math.max(1e-6, Number(node.props?.StudsPerTileU ?? 2));
    const studsV = Math.max(1e-6, Number(node.props?.StudsPerTileV ?? 2));
    texture.repeat.set(faceWidth / studsU, faceHeight / studsV);
    texture.offset.set(
      -Number(node.props?.OffsetStudsU ?? 0) / studsU,
      Number(node.props?.OffsetStudsV ?? 0) / studsV,
    );
    texture.needsUpdate = true;
  }
  const transparency = Math.max(0, Math.min(1, Number(node.props?.Transparency ?? 0)));
  const material = new THREE.MeshBasicMaterial({
    map: texture,
    color: colorValue(node.props?.Color3, 0xffffff),
    transparent: true,
    opacity: 1 - transparency,
    side: THREE.DoubleSide,
    depthWrite: false,
    polygonOffset: true,
    polygonOffsetFactor: -1,
    polygonOffsetUnits: -1,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.userData.rhrDecoration = true;
  plane.add(mesh);
  parentMesh.add(plane);
}

async function addSurfaceImages(index) {
  const jobs = [];
  for (const className of ['Decal', 'Texture']) {
    for (const node of nodesOfClass(index, className)) {
      const parent = index.parentByNode.get(node);
      if (parent && !partsWithoutDecals.has(parent)) jobs.push(addSurfaceImage(node, parent));
    }
  }
  await Promise.all(jobs);
}

function addAttachmentAnchors(index) {
  for (const node of nodesOfClass(index, 'Attachment')) {
    const parentNode = index.parentByNode.get(node);
    if (!parentNode) continue;
    const parentAnchor = anchorByNode.get(parentNode) || meshByNode.get(parentNode);
    if (!parentAnchor) continue;
    const anchor = new THREE.Object3D();
    const cf = node.props?.CFrame;
    if (cf) {
      anchor.matrixAutoUpdate = false;
      anchor.matrix.copy(cframeMatrix(cf));
      const position = node.props?.Position;
      if (position) {
        // The emitter preserves both properties. In saved Roblox instances the
        // serialized CFrame can remain identity while Position carries the
        // authored local offset; keep CFrame's rotation and apply Position's
        // explicit translation.
        anchor.matrix.setPosition(
          Number(position.X ?? 0),
          Number(position.Y ?? 0),
          Number(position.Z ?? 0),
        );
      }
      anchor.matrixWorldNeedsUpdate = true;
    } else {
      const position = node.props?.Position;
      anchor.position.set(
        Number(position?.X ?? 0),
        Number(position?.Y ?? 0),
        Number(position?.Z ?? 0),
      );
    }
    parentAnchor.add(anchor);
    anchorByNode.set(node, anchor);
  }
}

function sequenceKeypoints(value) {
  return (value?.keypoints || [])
    .map((point, index) => ({
      time: Number(point.Time ?? point.time ?? 0),
      value: point.Value ?? point.value,
      index,
    }))
    .sort((a, b) => a.time - b.time || a.index - b.index);
}

function sequenceValue(value, time, fallback = 0) {
  const points = sequenceKeypoints(value);
  if (!points.length) return Number(value ?? fallback);
  const t = Math.max(0, Math.min(1, Number(time)));
  if (t <= points[0].time) return Number(points[0].value ?? fallback);
  const last = points.at(-1);
  if (t >= last.time) return Number(last.value ?? fallback);
  for (let index = 1; index < points.length; index += 1) {
    const a = points[index - 1];
    const b = points[index];
    if (t <= b.time) {
      const alpha = b.time === a.time ? 1 : (t - a.time) / (b.time - a.time);
      return Number(a.value ?? fallback) + (Number(b.value ?? fallback) - Number(a.value ?? fallback)) * alpha;
    }
  }
  return Number(last.value ?? fallback);
}

function sequenceColorAt(value, time, fallback = 0xffffff) {
  const points = sequenceKeypoints(value);
  if (!points.length) return colorValue(value, fallback);
  const t = Math.max(0, Math.min(1, Number(time)));
  if (t <= points[0].time) return colorValue(points[0].value, fallback);
  const last = points.at(-1);
  if (t >= last.time) return colorValue(last.value, fallback);
  for (let index = 1; index < points.length; index += 1) {
    const a = points[index - 1];
    const b = points[index];
    if (t <= b.time) {
      const alpha = b.time === a.time ? 1 : (t - a.time) / (b.time - a.time);
      return colorValue(a.value, fallback).lerp(colorValue(b.value, fallback), alpha);
    }
  }
  return colorValue(last.value, fallback);
}

function cubicPoint(p0, p1, p2, p3, t) {
  const omt = 1 - t;
  return p0.clone().multiplyScalar(omt * omt * omt)
    .addScaledVector(p1, 3 * omt * omt * t)
    .addScaledVector(p2, 3 * omt * t * t)
    .addScaledVector(p3, t * t * t);
}

function cubicTangent(p0, p1, p2, p3, t) {
  const omt = 1 - t;
  return p1.clone().sub(p0).multiplyScalar(3 * omt * omt)
    .addScaledVector(p2.clone().sub(p1), 6 * omt * t)
    .addScaledVector(p3.clone().sub(p2), 3 * t * t);
}

function beamRibbonGeometry(points, tangents, widths, camera, faceCamera, normal, textureMode, textureLength, colorSequence, transparencySequence, textureOffset = 0) {
  const positions = [];
  const uvs = [];
  const colors = [];
  const distances = [0];
  for (let index = 1; index < points.length; index += 1) {
    distances.push(distances[index - 1] + points[index].distanceTo(points[index - 1]));
  }
  const totalLength = Math.max(1e-6, distances.at(-1));

  for (let index = 0; index < points.length; index += 1) {
    const point = points[index];
    const tangent = tangents[index].clone().normalize();
    let side;
    if (faceCamera) {
      side = tangent.clone().cross(camera.position.clone().sub(point));
    } else {
      side = normal.clone().sub(tangent.clone().multiplyScalar(normal.dot(tangent)));
    }
    if (side.lengthSq() <= 1e-10) {
      side = tangent.clone().cross(new THREE.Vector3(0, 1, 0));
      if (side.lengthSq() <= 1e-10) side = tangent.clone().cross(new THREE.Vector3(1, 0, 0));
    }
    side.normalize().multiplyScalar(Math.max(0.005, widths[index] / 2));
    const left = point.clone().sub(side);
    const right = point.clone().add(side);
    positions.push(left.x, left.y, left.z, right.x, right.y, right.z);
    // The texture's vertical axis runs along the beam and its horizontal axis across
    // it. Stretch repeats it TextureLength times over the whole beam; Wrap and Static
    // repeat it every TextureLength studs (measured in Studio). The image's top is at
    // Attachment0 (v runs down the image, as the texture is flipped on load), and
    // textureOffset scrolls it toward Attachment1, in whole textures.
    const along = textureMode === 'Stretch'
      ? distances[index] / totalLength * Math.max(1e-6, textureLength)
      : distances[index] / Math.max(1e-6, textureLength);
    const v = textureOffset - along;
    uvs.push(0, v, 1, v);
    const color = sequenceColorAt(colorSequence, index / Math.max(1, points.length - 1));
    const alpha = 1 - Math.max(0, Math.min(1, sequenceValue(transparencySequence, index / Math.max(1, points.length - 1), 0)));
    colors.push(color.r, color.g, color.b, alpha, color.r, color.g, color.b, alpha);
  }

  const indices = [];
  for (let index = 0; index < points.length - 1; index += 1) {
    const left = index * 2;
    const next = left + 2;
    indices.push(left, next, left + 1, left + 1, next, next + 1);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 4));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  return geometry;
}

async function addBeams(index, camera) {
  for (const node of nodesOfClass(index, 'Beam')) {
    if (node.props?.Enabled === false) continue;
    const a0 = findNodeByReference(index, node, 'Attachment0');
    const a1 = findNodeByReference(index, node, 'Attachment1');
    const anchor0 = anchorByNode.get(a0);
    const anchor1 = anchorByNode.get(a1);
    if (!anchor0 || !anchor1) continue;
    scene.updateMatrixWorld(true);
    const p0 = anchor0.getWorldPosition(new THREE.Vector3());
    const p3 = anchor1.getWorldPosition(new THREE.Vector3());
    const x0 = new THREE.Vector3(1, 0, 0).applyQuaternion(anchor0.getWorldQuaternion(new THREE.Quaternion())).normalize();
    const x1 = new THREE.Vector3(1, 0, 0).applyQuaternion(anchor1.getWorldQuaternion(new THREE.Quaternion())).normalize();
    const curveSize0 = Number(node.props?.CurveSize0 ?? 0);
    const curveSize1 = Number(node.props?.CurveSize1 ?? 0);
    const p1 = p0.clone().addScaledVector(x0, curveSize0);
    const p2 = p3.clone().addScaledVector(x1, -curveSize1);
    const segments = Math.max(2, Math.min(64, Math.round(Number(node.props?.Segments ?? 10))));
    const points = [];
    const tangents = [];
    const widths = [];
    for (let index = 0; index <= segments; index += 1) {
      const t = index / segments;
      points.push(cubicPoint(p0, p1, p2, p3, t));
      const tangent = cubicTangent(p0, p1, p2, p3, t);
      tangents.push(tangent.lengthSq() > 1e-10 ? tangent : p3.clone().sub(p0));
      widths.push(Math.max(0.01, Number(node.props?.Width0 ?? 0.2) * (1 - t) + Number(node.props?.Width1 ?? 0.2) * t));
    }
    if (points[0].distanceTo(points.at(-1)) <= 1e-6 && Math.abs(curveSize0) <= 1e-6 && Math.abs(curveSize1) <= 1e-6) continue;
    const attachmentUp = new THREE.Vector3(0, 1, 0).applyQuaternion(anchor0.getWorldQuaternion(new THREE.Quaternion())).normalize();
    const textureMode = node.props?.TextureMode?.name || 'Stretch';
    const textureLength = Math.max(1e-6, Number(node.props?.TextureLength ?? 1));
    const geometry = beamRibbonGeometry(
      points,
      tangents,
      widths,
      camera,
      node.props?.FaceCamera === true,
      attachmentUp,
      textureMode,
      textureLength,
      node.props?.Color,
      node.props?.Transparency,
      // TextureSpeed cycles per second, from Attachment0 toward Attachment1, at the
      // effect time (kept to one cycle so large times stay precise).
      (Number(node.props?.TextureSpeed ?? 1) * (particleState.time ?? 0)) % 1,
    );
    const localTransparency = Math.max(0, Math.min(1, Number(node.props?.LocalTransparencyModifier ?? 0)));
    const materialOpacity = 1 - localTransparency;
    const brightness = Math.max(0, Number(node.props?.Brightness ?? 1));
    const texture = ribbonTexture(node.props?.Texture ? await loadSceneTexture(node.props.Texture) : null);
    const material = effectMaterial(texture, effectLight(brightness, node.props?.LightInfluence), materialOpacity, node.props?.LightEmission);
    const mesh = new THREE.Mesh(geometry, material);
    mesh.userData.rhrDecoration = true;
    mesh.userData.rhrEffect = true;
    centerForSorting(mesh);
    scene.add(mesh);
  }
}

function ancestorPart(index, node) {
  let current = node;
  while (current) {
    if (['Part', 'WedgePart', 'CornerWedgePart', 'MeshPart', 'UnionOperation'].includes(current.className)) return current;
    current = index.parentByNode.get(current) || null;
  }
  return null;
}

function assemblyVelocity(index, attachment) {
  const part = ancestorPart(index, index.parentByNode.get(attachment));
  const value = part?.props?.AssemblyLinearVelocity;
  return new THREE.Vector3(
    Number(value?.X ?? 0),
    Number(value?.Y ?? 0),
    Number(value?.Z ?? 0),
  );
}

function trailRibbonGeometry(positions0, positions1, ages, widthScale, colorSequence, transparencySequence, textureMode, textureLength, camera, faceCamera) {
  const positions = [];
  const uvs = [];
  const colors = [];
  const centers = positions0.map((position, index) => position.clone().add(positions1[index]).multiplyScalar(0.5));
  const distances = [0];
  for (let index = 1; index < centers.length; index += 1) {
    distances.push(distances[index - 1] + centers[index].distanceTo(centers[index - 1]));
  }

  for (let index = 0; index < centers.length; index += 1) {
    const center = centers[index];
    const span = positions1[index].clone().sub(positions0[index]);
    const spanLength = span.length();
    let side = spanLength > 1e-8 ? span.normalize() : new THREE.Vector3(1, 0, 0);
    if (faceCamera && camera) {
      const before = centers[Math.max(0, index - 1)];
      const after = centers[Math.min(centers.length - 1, index + 1)];
      const tangent = after.clone().sub(before);
      if (tangent.lengthSq() > 1e-10) {
        tangent.normalize();
        const towardCamera = camera.position.clone().sub(center);
        const cameraSide = tangent.clone().cross(towardCamera);
        if (cameraSide.lengthSq() > 1e-10) side = cameraSide.normalize();
      }
    }
    const scale = Math.max(0, sequenceValue(widthScale, ages[index], 1));
    side.multiplyScalar(spanLength * scale / 2);
    const edge0 = center.clone().sub(side);
    const edge1 = center.clone().add(side);
    positions.push(edge0.x, edge0.y, edge0.z, edge1.x, edge1.y, edge1.z);
    // As for Beams: the texture's vertical axis runs along the trail, the image's top
    // at the attachments (the newest end, measured in Studio). Wrap tiles stay put
    // relative to the attachments, so a whole tile starts there; Static tiles are
    // stamped where the trail began, here its oldest point.
    const v = textureMode === 'Stretch'
      ? (1 - ages[index]) * textureLength
      : textureMode === 'Wrap'
        ? (distances[index] - distances.at(-1)) / Math.max(1e-6, textureLength)
        : distances[index] / Math.max(1e-6, textureLength);
    uvs.push(0, v, 1, v);
    const color = sequenceColorAt(colorSequence, ages[index]);
    const alpha = 1 - Math.max(0, Math.min(1, sequenceValue(transparencySequence, ages[index], 0)));
    colors.push(color.r, color.g, color.b, alpha, color.r, color.g, color.b, alpha);
  }

  const indices = [];
  for (let index = 0; index < centers.length - 1; index += 1) {
    const left = index * 2;
    const next = left + 2;
    indices.push(left, next, left + 1, left + 1, next, next + 1);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 4));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  return geometry;
}

async function addTrails(index, camera) {
  for (const node of nodesOfClass(index, 'Trail')) {
    if (node.props?.Enabled === false) continue;
    const a0 = findNodeByReference(index, node, 'Attachment0');
    const a1 = findNodeByReference(index, node, 'Attachment1');
    const anchor0 = anchorByNode.get(a0);
    const anchor1 = anchorByNode.get(a1);
    if (!anchor0 || !anchor1) continue;
    scene.updateMatrixWorld(true);
    const current0 = anchor0.getWorldPosition(new THREE.Vector3());
    const current1 = anchor1.getWorldPosition(new THREE.Vector3());
    const velocity0 = assemblyVelocity(index, a0);
    const velocity1 = assemblyVelocity(index, a1);
    const speed = Math.max(velocity0.length(), velocity1.length());
    if (speed <= 1e-6) continue;
    const lifetime = Math.max(0.01, Math.min(20, Number(node.props?.Lifetime ?? 2)));
    const maxLength = Math.max(0, Number(node.props?.MaxLength ?? 0));
    const effectiveLifetime = maxLength > 0 ? Math.min(lifetime, maxLength / speed) : lifetime;
    const minLength = Math.max(0, Number(node.props?.MinLength ?? 0));
    if (speed * effectiveLifetime + 1e-6 < minLength) continue;
    const samples = Math.max(2, Math.min(64, Math.ceil(effectiveLifetime * 30)));
    const positions0 = [];
    const positions1 = [];
    const ages = [];
    for (let index = 0; index <= samples; index += 1) {
      const age = effectiveLifetime * (1 - index / samples);
      positions0.push(current0.clone().addScaledVector(velocity0, -age));
      positions1.push(current1.clone().addScaledVector(velocity1, -age));
      ages.push(age / lifetime);
    }
    const geometry = trailRibbonGeometry(
      positions0,
      positions1,
      ages,
      node.props?.WidthScale,
      node.props?.Color,
      node.props?.Transparency,
      node.props?.TextureMode?.name || 'Stretch',
      Math.max(1e-6, Number(node.props?.TextureLength ?? 1)),
      camera,
      node.props?.FaceCamera === true,
    );
    const texture = ribbonTexture(node.props?.Texture ? await loadSceneTexture(node.props.Texture) : null);
    const localTransparency = Math.max(0, Math.min(1, Number(node.props?.LocalTransparencyModifier ?? 0)));
    const materialOpacity = 1 - localTransparency;
    const brightness = Math.max(0, Number(node.props?.Brightness ?? 1));
    const material = effectMaterial(texture, effectLight(brightness, node.props?.LightInfluence), materialOpacity, node.props?.LightEmission);
    const mesh = new THREE.Mesh(geometry, material);
    mesh.userData.rhrDecoration = true;
    mesh.userData.rhrEffect = true;
    centerForSorting(mesh);
    scene.add(mesh);
  }
}

// How Roblox draws a particle, fitted to a sweep of flat particles in Studio (LightEmission
// -2..1, Brightness 1/5/25, transparency 0/0.5/0.75, over black and white, plus an
// orange at Brightness 1/5/25; 8/255 RMS): each channel of the colour (texture x Color x
// Brightness) is capped softly near 2.5; alpha acts as alpha^1.45; what is behind is kept
// by 1 - a (1 - LE) for LightEmission 0..1 (all of it at 1: added light) and by
// 1 - a (1 + 2.47 |LE|) below 0, which darkens it hard; then Studio's tone curve, on the brightest channel,
// with each channel pulled toward white as it gets bright (bright orange turns yellow,
// then white). Blended in HDR: see compositeParticles.
const PARTICLE_FIT = {q: 1.4543, cap: 2.4633, sPos: 0.1052, sNeg: 0.0517, kNeg: 2.4655,
  g: 2.1935, c: 0.2196, p: 1.8966, m0: 0.8305, n: 2.5407, t: 0.5301};
const PARTICLE_LAYER = 1;
function particleMaterial(map, light, lightEmission) {
  const material = new THREE.MeshBasicMaterial({
    map,
    color: light,
    vertexColors: true,
    transparent: true,
    side: THREE.DoubleSide,
    depthWrite: false,
    blending: THREE.CustomBlending,
    blendSrc: THREE.OneFactor,
    blendDst: THREE.OneMinusSrcAlphaFactor,
    blendSrcAlpha: THREE.OneFactor,
    blendDstAlpha: THREE.OneMinusSrcAlphaFactor,
  });
  const f = PARTICLE_FIT;
  material.onBeforeCompile = shader => {
    shader.uniforms.rhrLightEmission = {value: Number(lightEmission ?? 0)};
    shader.fragmentShader = 'uniform float rhrLightEmission;\n' + shader.fragmentShader.replace(
      '#include <premultiplied_alpha_fragment>',
      `float rhrA = pow(clamp(gl_FragColor.a, 0.0, 1.0), ${f.q.toFixed(4)});
      vec3 rhrCol = ${f.cap.toFixed(4)} * tanh(max(gl_FragColor.rgb, vec3(0.0)) / ${f.cap.toFixed(4)});
      float rhrLE = rhrLightEmission;
      gl_FragColor.rgb = rhrCol * rhrA * (1.0 + ${f.sPos.toFixed(4)} * max(rhrLE, 0.0) + ${f.sNeg.toFixed(4)} * min(rhrLE, 0.0));
      // What stays of the background: at most all of it, never less than nothing.
      float rhrKept = rhrLE >= 0.0 ? min(rhrLE, 1.0) : ${f.kNeg.toFixed(4)} * rhrLE;
      gl_FragColor.a = min(1.0, rhrA * (1.0 - rhrKept));`,
    );
  };
  material.customProgramCacheKey = () => 'rhr-particle';
  return material;
}

// How much light a particle, Beam or Trail gives off, per channel, as a multiple of its
// colour (measured in Studio with flat particles and beams, 212 readings, 1.7/255 RMS
// through Studio's own display curve). LightInfluence L blends Brightness toward the
// scene's light with weight sqrt(L): at L = 1 Brightness no longer counts and the
// effect is exactly as bright as the scene's light. That light does not depend on
// which way the effect faces: the larger of Ambient and OutdoorAmbient, squared, plus
// Lighting.Brightness / 2 while the sun is up (fading in over the 15 minutes after
// sunrise, and out before sunset). At night the moon gives a few percent that falls
// off steeply as the moon sinks. Without Lighting, Studio's daylight: 1.
let effectSceneLight = new THREE.Color(1, 1, 1);

function effectLight(brightness, lightInfluence) {
  const w = Math.sqrt(Math.max(0, Math.min(1, Number(lightInfluence ?? 0))));
  const b = brightness * (1 - w);
  return new THREE.Color(b + w * effectSceneLight.r, b + w * effectSceneLight.g, b + w * effectSceneLight.b);
}

function configureEffectLight(lighting) {
  if (!lighting) {
    effectSceneLight = new THREE.Color(1, 1, 1);
    return;
  }
  const props = lighting.props || {};
  const channel = (value, key) => Math.max(0, Number(value?.[key] ?? 0.5));
  const clock = clockTime(props) ?? 14;
  // Sun height as in configureSceneLights (Lighting:GetSunDirection().Y).
  const tilt = Math.cos(THREE.MathUtils.degToRad(Number(props.GeographicLatitude ?? 41.7333) - 23.5));
  const height = Math.sin(((clock - 6) / 12) * Math.PI) * tilt;
  const sky = height >= 0 ? Math.min(1, height / 0.073) : 0.086 * (-height) ** 3.2;
  const sun = Math.max(0, Number(props.Brightness ?? 1)) / 2 * sky;
  const light = ['R', 'G', 'B'].map(key => Math.max(channel(props.Ambient, key), channel(props.OutdoorAmbient, key)) ** 2 + sun);
  effectSceneLight = new THREE.Color(...light);
}

// A Beam or Trail repeats its texture along its length: its own copy (the image may be
// shared with a decal), repeating vertically and clamped across.
function ribbonTexture(texture) {
  if (!texture) return null;
  const copy = texture.clone();
  copy.wrapS = THREE.ClampToEdgeWrapping;
  copy.wrapT = THREE.RepeatWrapping;
  copy.needsUpdate = true;
  return copy;
}

// Particles, Beams and Trails blend by LightEmission: 0 is ordinary transparency,
// 1 adds the effect's light to what is behind it (it can only brighten), and values in
// between mix the two. Written premultiplied: colour * alpha is added, and what is
// behind is dimmed by alpha * (1 - LightEmission).
function effectMaterial(map, light, opacity, lightEmission) {
  const emission = Math.max(0, Math.min(1, Number(lightEmission ?? 0)));
  const material = new THREE.MeshBasicMaterial({
    map,
    color: light,
    vertexColors: true,
    transparent: true,
    opacity,
    side: THREE.DoubleSide,
    depthWrite: false,
    blending: THREE.CustomBlending,
    blendSrc: THREE.OneFactor,
    blendDst: THREE.OneMinusSrcAlphaFactor,
    blendSrcAlpha: THREE.OneFactor,
    blendDstAlpha: THREE.OneMinusSrcAlphaFactor,
  });
  material.onBeforeCompile = shader => {
    shader.uniforms.rhrLightEmission = {value: emission};
    shader.fragmentShader = 'uniform float rhrLightEmission;\n' + shader.fragmentShader.replace(
      '#include <premultiplied_alpha_fragment>',
      'gl_FragColor.rgb *= gl_FragColor.a;\ngl_FragColor.a *= 1.0 - rhrLightEmission;',
    );
  };
  material.customProgramCacheKey = () => 'rhr-effect';
  return material;
}

// Transparent objects are drawn far to near by their position; effect geometry is
// built in world coordinates, so move its origin to its middle for that sort.
function centerForSorting(mesh) {
  const geometry = mesh.geometry;
  geometry.computeBoundingBox();
  if (!geometry.boundingBox || geometry.boundingBox.isEmpty()) return;
  const center = geometry.boundingBox.getCenter(new THREE.Vector3());
  geometry.translate(-center.x, -center.y, -center.z);
  mesh.position.add(center);
}

// ParticleEmitters, frozen at one moment of the effect playing (see particles/sim.js
// for how an effect is played). The moment is --effect-time seconds after the effect
// starts or, by default, the one with the most particle area on show.
const particleState = {emitters: [], time: null, auto: false, idle: [], orphan: 0, missingTextures: new Set(), drawn: 0};

function worldPose(object) {
  object.updateWorldMatrix(true, false);
  const position = new THREE.Vector3();
  const quaternion = new THREE.Quaternion();
  object.matrixWorld.decompose(position, quaternion, new THREE.Vector3());
  return {position, quaternion};
}

function collectEmitters(index, seed) {
  // Calibration only (RHR_EFFECTS_UNDER): draw just the emitters under one path.
  const under = params.get('effectsUnder');
  for (const node of nodesOfClass(index, 'ParticleEmitter')) {
    if (under && !String(node.path || '').startsWith(under)) continue;
    const props = node.props || {};
    const schedule = playSchedule(props, node.attributes);
    if (schedule.kind === 'idle') {
      particleState.idle.push(node.path || node.name);
      continue;
    }
    const parent = index.parentByNode.get(node);
    let pose = null;
    let size = [0, 0, 0];
    if (parent?.className === 'Attachment' && anchorByNode.get(parent)) {
      pose = worldPose(anchorByNode.get(parent));
    } else if (parent?.props?.CFrame && meshByNode.get(parent)) {
      const matrix = cframeMatrix(parent.props.CFrame);
      pose = {position: new THREE.Vector3(), quaternion: new THREE.Quaternion()};
      matrix.decompose(pose.position, pose.quaternion, new THREE.Vector3());
      size = dimensions(parent.props.Size);
    }
    if (!pose) {
      particleState.orphan += 1;
      continue;
    }
    const axes = [new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 1)]
      .map(axis => axis.applyQuaternion(pose.quaternion).toArray());
    particleState.emitters.push({
      node,
      props,
      schedule,
      options: {origin: pose.position.toArray(), basis: axes, emitterSize: size, seed: hashSeed(node.path || node.name, seed)},
    });
  }
}

function chooseEffectTime(requested) {
  if (Number.isFinite(requested)) return Math.max(0, requested);
  const played = particleState.emitters.filter(emitter => emitter.schedule.played);
  if (!played.length) return 0;
  particleState.auto = true;
  const dt = 1 / 30;
  const horizon = Math.min(30, Math.max(...played.map(emitter => playHorizon(emitter.props, emitter.schedule))));
  const scores = new Float64Array(Math.ceil(horizon / dt) + 2);
  for (const emitter of particleState.emitters) {
    playEmitter(emitter.props, emitter.schedule, {
      ...emitter.options,
      dt,
      from: 0,
      until: horizon,
      visit: (time, particles) => {
        // Size and transparency only: the colour and flipbook frame do not count.
        let score = 0;
        for (const particle of particles) {
          const alpha = particle.age / particle.lifetime;
          const size = sampleNumberSequence(emitter.props.Size, alpha);
          const transparency = sampleNumberSequence(emitter.props.Transparency, alpha);
          score += size * size * Math.max(0, 1 - Math.min(1, transparency));
        }
        scores[Math.round(time / dt)] += score;
      },
    });
  }
  // The middle of the first stretch at (nearly) the fullest: a burst is fullest the
  // moment it is emitted too, while every particle still sits on one spot.
  const peak = Math.max(...scores);
  if (!(peak > 0)) return 0;
  const first = scores.findIndex(score => score >= peak * 0.9);
  let last = first;
  while (last + 1 < scores.length && scores[last + 1] >= peak * 0.9) last += 1;
  return Math.round((first + last) / 2) * dt;
}

function simulateParticles(index) {
  const seed = Number(params.get('seed') || 0);
  collectEmitters(index, seed);
  const requested = params.get('effectTime') === null ? NaN : Number(params.get('effectTime'));
  particleState.time = chooseEffectTime(requested);
  for (const emitter of particleState.emitters) {
    const particles = playEmitter(emitter.props, emitter.schedule, {...emitter.options, dt: 1 / 60, until: particleState.time});
    // A particle aligned to its velocity that has none is not drawn (Studio: VelocityParallel
    // at Speed 0 shows nothing, where Speed 0.001 does).
    const aligned = /^Velocity/.test(emitter.props.Orientation?.name || '');
    emitter.snapshot = particles.map(particle => ({particle, look: particleLook(emitter.props, particle)}))
      .filter(({particle, look}) => look.size > 0 && look.transparency < 1
        && !(aligned && Math.hypot(...particle.velocity) < 1e-9));
  }
}

// A texture that cannot be loaded draws nothing, as in Studio (its particles are
// reported instead).
async function particleTexture(uri) {
  const texture = await loadSceneTexture(uri);
  if (!texture) particleState.missingTextures.add(String(uri));
  return texture;
}

async function addParticles(camera) {
  const cameraPosition = camera.getWorldPosition(new THREE.Vector3());
  const cameraRight = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0).normalize();
  const cameraUp = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1).normalize();
  const worldUp = new THREE.Vector3(0, 1, 0);
  for (const emitter of particleState.emitters) {
    if (!emitter.snapshot?.length) continue;
    const props = emitter.props;
    // An emitter without a texture draws nothing in Roblox.
    if (!String(props.Texture || '').trim()) continue;
    const orientation = props.Orientation?.name || 'FacingCamera';
    const zOffset = Number(props.ZOffset ?? 0);
    const brightness = Math.max(0, Number(props.Brightness ?? 1));
    const [columns, rows] = flipbookLayout(props);
    const quads = [];
    for (const {particle, look} of emitter.snapshot) {
      const position = new THREE.Vector3(...particle.position);
      const toCamera = cameraPosition.clone().sub(position);
      const distance = toCamera.length();
      if (distance < 1e-4) continue;
      toCamera.divideScalar(distance);
      // ZOffset moves the particle toward the camera (or away) without changing its
      // size on screen.
      let sizeScale = 1;
      if (zOffset) {
        const moved = Math.max(0.06, distance - zOffset);
        sizeScale = moved / distance;
        position.copy(cameraPosition).addScaledVector(toCamera, -moved);
      }
      const velocity = new THREE.Vector3(...particle.velocity);
      let right;
      let up;
      if (orientation === 'VelocityParallel' && velocity.lengthSq() > 1e-12) {
        up = velocity.clone().normalize();
        right = new THREE.Vector3().crossVectors(up, toCamera);
        if (right.lengthSq() < 1e-10) right.copy(cameraRight);
        right.normalize();
      } else if (orientation === 'VelocityPerpendicular' && velocity.lengthSq() > 1e-12) {
        const normal = velocity.clone().normalize();
        right = new THREE.Vector3().crossVectors(Math.abs(normal.y) > 0.99 ? new THREE.Vector3(1, 0, 0) : worldUp, normal).normalize();
        up = new THREE.Vector3().crossVectors(normal, right).normalize();
      } else if (orientation === 'FacingCameraWorldUp') {
        up = worldUp.clone();
        right = new THREE.Vector3().crossVectors(up, toCamera);
        if (right.lengthSq() < 1e-10) right.copy(cameraRight);
        right.normalize();
      } else {
        right = cameraRight.clone();
        up = cameraUp.clone();
      }
      if (orientation !== 'VelocityParallel') {
        const angle = -THREE.MathUtils.degToRad(Number(particle.rotation || 0));
        const c = Math.cos(angle);
        const s = Math.sin(angle);
        const r2 = right.clone().multiplyScalar(c).addScaledVector(up, s);
        up = up.clone().multiplyScalar(c).addScaledVector(right, -s);
        right = r2;
      }
      // Squash s stretches one axis by 1 + |s| and shrinks the other as much: taller
      // for s > 0, wider for s < 0 (measured in Studio at -3, -1, 1 and 3).
      const squash = Number(look.squash || 0);
      const tall = squash >= 0 ? 1 + squash : 1 / (1 - squash);
      // Size is half the particle's width: a Size 4 particle is 8 studs across
      // (measured in Studio against a 4-stud cube).
      const halfWidth = look.size * sizeScale / tall;
      const halfHeight = look.size * sizeScale * tall;
      const frame = look.frame || {index: 0};
      const column = frame.index % columns;
      const row = Math.floor(frame.index / columns);
      const color = new THREE.Color().setRGB(look.color[0], look.color[1], look.color[2], THREE.SRGBColorSpace);
      quads.push({
        depth: cameraPosition.distanceToSquared(position),
        position, right: right.multiplyScalar(halfWidth), up: up.multiplyScalar(halfHeight),
        uv: [column / columns, 1 - (row + 1) / rows, (column + 1) / columns, 1 - row / rows],
        color, alpha: 1 - look.transparency,
      });
    }
    if (!quads.length) continue;
    quads.sort((a, b) => b.depth - a.depth);
    const positions = new Float32Array(quads.length * 12);
    const uvs = new Float32Array(quads.length * 8);
    const colors = new Float32Array(quads.length * 16);
    const indices = new Uint32Array(quads.length * 6);
    quads.forEach((quad, i) => {
      const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]];
      corners.forEach(([sx, sy], k) => {
        const p = quad.position.clone().addScaledVector(quad.right, sx).addScaledVector(quad.up, sy);
        positions.set([p.x, p.y, p.z], (i * 4 + k) * 3);
        uvs.set([sx < 0 ? quad.uv[0] : quad.uv[2], sy < 0 ? quad.uv[1] : quad.uv[3]], (i * 4 + k) * 2);
        colors.set([quad.color.r, quad.color.g, quad.color.b, quad.alpha], (i * 4 + k) * 4);
      });
      indices.set([i * 4, i * 4 + 1, i * 4 + 2, i * 4, i * 4 + 2, i * 4 + 3], i * 6);
    });
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 4));
    geometry.setIndex(new THREE.BufferAttribute(indices, 1));
    const texture = await particleTexture(props.Texture);
    if (!texture) continue;
    const material = particleMaterial(texture, effectLight(brightness, props.LightInfluence), props.LightEmission);
    const mesh = new THREE.Mesh(geometry, material);
    mesh.userData.rhrDecoration = true;
    mesh.userData.rhrEffect = true;
    mesh.layers.set(PARTICLE_LAYER);
    // The particles already moved by ZOffset, so the sort sees it too: it changes
    // which effect is drawn over which, as in Roblox.
    centerForSorting(mesh);
    scene.add(mesh);
    particleState.drawn += quads.length;
  }
}

// Highlight: the parts' shape filled with FillColor and edged with OutlineColor, drawn
// over the scene (AlwaysOnTop) or only where the parts are seen (Occluded), before the
// effects. Every fill is drawn first, in order, then every outline (in Studio a later
// Highlight's fill does not cover an earlier one's outline). Through the stencil
// buffer, each of the first four Highlights gets two bits: "inside the shape", so its
// outline (the shape pushed out a few pixels) only shows outside it, and "not filled
// yet", so its fill is laid down once per pixel. Later ones get a plain fill.
const OUTLINE_PX = 3;  // at 1080 px screen height
const highlightState = {drawn: 0, skipped: 0};
function addHighlights(index) {
  const highlights = nodesOfClass(index, 'Highlight').filter(node => node.props?.Enabled !== false);
  highlights.slice(0, 31).forEach((node, i) => {
    const target = findNodeByReference(index, node, 'Adornee') || index.parentByNode.get(node);
    if (!target) return;
    const meshes = [];
    walk(target, child => {
      const mesh = meshByNode.get(child);
      if (mesh?.isMesh && Number(child.props?.Transparency ?? 0) < 1) meshes.push(mesh);
    });
    if (!meshes.length) return;
    const onTop = (node.props?.DepthMode?.name || 'AlwaysOnTop') === 'AlwaysOnTop';
    const fillOpacity = 1 - Math.max(0, Math.min(1, Number(node.props?.FillTransparency ?? 0.5)));
    const outlineOpacity = 1 - Math.max(0, Math.min(1, Number(node.props?.OutlineTransparency ?? 0)));
    // Front faces only, as in Roblox: the holes in a cracked shell stay holes, and get
    // their own outline.
    const common = {depthTest: !onTop, depthWrite: false, transparent: true, side: THREE.FrontSide};
    const passes = [];
    if (i < 4) {
      const shapeBit = 1 << (2 * i);
      const fillBit = 1 << (2 * i + 1);
      passes.push([-1000 + i * 2, new THREE.MeshBasicMaterial({...common, colorWrite: false, stencilWrite: true,
        stencilRef: shapeBit | fillBit, stencilWriteMask: shapeBit | fillBit,
        stencilFunc: THREE.AlwaysStencilFunc, stencilZPass: THREE.ReplaceStencilOp})]);
      if (fillOpacity > 0) {
        passes.push([-999 + i * 2, new THREE.MeshBasicMaterial({...common, stencilWrite: true,
          color: colorValue(node.props?.FillColor, 0xffffff), opacity: fillOpacity,
          stencilRef: fillBit, stencilFuncMask: fillBit, stencilWriteMask: fillBit,
          stencilFunc: THREE.EqualStencilFunc, stencilZPass: THREE.ZeroStencilOp})]);
      }
      if (outlineOpacity > 0) {
        const outline = new THREE.MeshBasicMaterial({...common, side: THREE.BackSide, stencilWrite: true,
          color: colorValue(node.props?.OutlineColor, 0xffffff), opacity: outlineOpacity,
          stencilRef: shapeBit, stencilFuncMask: shapeBit, stencilWriteMask: 0,
          stencilFunc: THREE.NotEqualStencilFunc, stencilZPass: THREE.KeepStencilOp});
        outline.onBeforeCompile = shader => {
          shader.uniforms.rhrOutline = {value: 2 * OUTLINE_PX / 1080};
          shader.vertexShader = 'uniform float rhrOutline;\n' + shader.vertexShader.replace(
            '#include <project_vertex>',
            `#include <project_vertex>
            vec2 rhrDir = (projectionMatrix * vec4(normalize(normalMatrix * normal), 0.0)).xy;
            if (dot(rhrDir, rhrDir) > 1e-12) gl_Position.xy += normalize(rhrDir) * rhrOutline * gl_Position.w;`,
          );
        };
        outline.customProgramCacheKey = () => 'rhr-highlight-outline';
        passes.push([-500 + i, outline]);
      }
    } else if (fillOpacity > 0) {
      passes.push([-999 + i * 2, new THREE.MeshBasicMaterial({...common, side: THREE.FrontSide,
        color: colorValue(node.props?.FillColor, 0xffffff), opacity: fillOpacity})]);
    }
    for (const mesh of meshes) {
      mesh.updateWorldMatrix(true, false);
      for (const [order, material] of passes) {
        const copy = new THREE.Mesh(mesh.geometry, material);
        copy.matrixAutoUpdate = false;
        copy.matrix.copy(mesh.matrixWorld);
        copy.renderOrder = order;
        copy.castShadow = false;
        copy.userData.rhrEffect = true;
        scene.add(copy);
      }
    }
    highlightState.drawn += 1;
  });
  highlightState.skipped = Math.max(0, highlights.length - 31);
}

function faceDirection(face) {
  if (face === 'Back') return new THREE.Vector3(0, 0, 1);
  if (face === 'Right') return new THREE.Vector3(1, 0, 0);
  if (face === 'Left') return new THREE.Vector3(-1, 0, 0);
  if (face === 'Top') return new THREE.Vector3(0, 1, 0);
  if (face === 'Bottom') return new THREE.Vector3(0, -1, 0);
  return new THREE.Vector3(0, 0, -1);
}

function configureLocalLightShadow(light) {
  light.castShadow = shadowsRequested;
  if (!light.castShadow) return;
  light.shadow.mapSize.set(512, 512);
  light.shadow.bias = -0.0005;
  light.shadow.normalBias = 0.02;
}

function addLocalLight(node, parentNode) {
  const parentMesh = anchorByNode.get(parentNode) || meshByNode.get(parentNode);
  if (!parentMesh) return;
  const props = node.props || {};
  const color = colorValue(props.Color, 0xffffff);
  const brightness = Math.max(0, Number(props.Brightness ?? 1));
  const range = Math.max(0.01, Number(props.Range ?? 8));
  const shadows = props.Shadows === true;
  let light;

  if (node.className === 'PointLight') {
    light = new THREE.PointLight(color, brightness * 18, range, 2);
    light.position.set(0, 0, 0);
  } else {
    const angle = Math.max(1, Math.min(179, Number(props.Angle ?? (node.className === 'SurfaceLight' ? 90 : 45))));
    light = new THREE.SpotLight(color, brightness * 22, range, THREE.MathUtils.degToRad(angle / 2), 0.22, 2);
    const direction = faceDirection(props.Face?.name || 'Front');
    light.position.copy(direction).multiplyScalar(0.03);
    light.target.position.copy(direction).multiplyScalar(Math.max(1, range * 0.5));
    parentMesh.add(light.target);
  }

  if (shadows) configureLocalLightShadow(light);
  light.userData.rhrDecoration = true;
  light.userData.rhrLocalLight = {range, brightness, path: node.path || node.name};
  parentMesh.add(light);
}

// WebGL evaluates every light for every pixel, and in software (SwiftShader) a place
// with a hundred SpotLights takes tens of seconds a frame. Keep the lights that
// matter from this camera: nearest first, weighted by range and brightness. The
// rest are removed and counted in a note.
const MAX_LOCAL_LIGHTS = 16;
let localLightsDropped = 0;

function pruneLocalLights(camera) {
  const lights = [];
  scene.updateMatrixWorld(true);
  scene.traverse(object => { if (object.userData?.rhrLocalLight) lights.push(object); });
  if (lights.length <= MAX_LOCAL_LIGHTS) return;
  const position = new THREE.Vector3();
  const score = light => {
    const {range, brightness} = light.userData.rhrLocalLight;
    const distance = light.getWorldPosition(position).distanceTo(camera.position);
    return Math.max(0, distance - range) / Math.max(0.1, Math.sqrt(brightness));
  };
  lights.sort((a, b) => score(a) - score(b));
  for (const light of lights.slice(MAX_LOCAL_LIGHTS)) {
    if (light.target) light.target.removeFromParent();
    light.removeFromParent();
    localLightsDropped += 1;
  }
}

function addLocalLights(index) {
  for (const className of ['PointLight', 'SpotLight', 'SurfaceLight']) {
    for (const node of nodesOfClass(index, className)) {
      const parent = index.parentByNode.get(node);
      if (parent) addLocalLight(node, parent);
    }
  }
}

function findCamera(index) {
  const cameras = nodesOfClass(index, 'Camera');
  const current = cameras.find(node =>
    node.name === 'CurrentCamera' && index.rootByNode.get(node)?.className === 'Workspace'
  );
  return current || cameras[0] || null;
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

function focusDirection(view) {
  if (view === 'front') return new THREE.Vector3(0, 0, 1);
  if (view === 'back') return new THREE.Vector3(0, 0, -1);
  if (view === 'left') return new THREE.Vector3(-1, 0, 0);
  if (view === 'right') return new THREE.Vector3(1, 0, 0);
  if (view === 'top') return new THREE.Vector3(0, 1, 0);
  return new THREE.Vector3(1, 0.75, 1).normalize();
}

// A standard view frames the build, not the floor: nearly every place has a
// 2048-stud Baseplate, and framing it leaves the build a speck in the middle. A part
// is ground when it is a thin slab whose footprint dwarfs everything else put
// together. It is still drawn; `--focus <its path>` frames it on purpose.
function withoutGround(boxes) {
  const footprint = b => Math.max(1e-6, (b.max.x - b.min.x) * (b.max.z - b.min.z));
  const isSlab = b => {
    const s = b.getSize(new THREE.Vector3());
    return s.y <= 0.05 * Math.min(s.x, s.z);
  };
  const slabs = boxes.filter(entry => isSlab(entry.box));
  if (!slabs.length || slabs.length === boxes.length) return boxes;
  const rest = new THREE.Box3();
  for (const entry of boxes) if (!slabs.includes(entry)) rest.union(entry.box);
  const ground = new Set(slabs.filter(entry => footprint(entry.box) >= 20 * footprint(rest)));
  if (!ground.size) return boxes;
  framingIgnored.push(...[...ground].map(entry => entry.node.path || entry.node.name));
  return boxes.filter(entry => !ground.has(entry));
}

const framingIgnored = [];

// Where the particles are, for framing: the 5th to 95th percentile on each axis, so a
// few sparks flung far away do not push the camera back.
function particleBoundsWithin(allowed) {
  const points = [];
  for (const emitter of particleState.emitters) {
    if (allowed && !allowed.has(emitter.node)) continue;
    if (!String(emitter.props.Texture || '').trim()) continue;
    for (const {particle, look} of emitter.snapshot || []) points.push([...particle.position, look.size]);
  }
  if (!points.length) return null;
  const pick = (axis, q) => {
    const values = points.map(point => point[axis]).sort((a, b) => a - b);
    return values[Math.min(values.length - 1, Math.max(0, Math.round(q * (values.length - 1))))];
  };
  const size = pick(3, 0.5);
  const lo = points.length >= 20 ? 0.05 : 0;
  const hi = points.length >= 20 ? 0.95 : 1;
  return new THREE.Box3(
    new THREE.Vector3(pick(0, lo) - size, pick(1, lo) - size, pick(2, lo) - size),
    new THREE.Vector3(pick(0, hi) + size, pick(1, hi) + size, pick(2, hi) + size),
  );
}

function frameScene(camera, index, focusPath, view = 'iso') {
  let allowed = null;
  if (focusPath) {
    const target = findNodeByPath(index, focusPath);
    if (!target) throw new Error(`focus path not found: ${focusPath}`);
    allowed = new Set();
    walk(target, node => allowed.add(node));
  }
  scene.updateMatrixWorld(true);
  const boxes = [];
  scene.traverse(object => {
    if (!object.isMesh || !object.userData?.rhrNode) return;
    if (allowed && !allowed.has(object.userData.rhrNode)) return;
    const objectBox = new THREE.Box3().expandByObject(object);
    if (!objectBox.isEmpty()) boxes.push({ box: objectBox, node: object.userData.rhrNode });
  });
  // Effects are framed with the parts they come from (an effect's parts are often
  // invisible, and its particles fly well past them).
  const effectBounds = particleBoundsWithin(allowed);
  if (!boxes.length && !effectBounds) throw new Error(`no renderable 3D geometry${focusPath ? ` under ${focusPath}` : ''}`);
  // Frame what can be seen: fully transparent parts (effect holders, often huge) only
  // count when there is nothing else.
  const seen = boxes.filter(entry => Number(entry.node.props?.Transparency ?? 0) < 1);
  const candidates = seen.length || effectBounds ? seen : boxes;
  const framed = focusPath ? candidates : withoutGround(candidates);
  const box = new THREE.Box3();
  for (const entry of framed) box.union(entry.box);
  if (effectBounds) box.union(effectBounds);

  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const verticalFov = THREE.MathUtils.degToRad(camera.fov);
  const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * camera.aspect);
  const distanceY = size.y / Math.max(1e-6, 2 * Math.tan(verticalFov / 2));
  const distanceX = size.x / Math.max(1e-6, 2 * Math.tan(horizontalFov / 2));
  const depthPad = Math.max(size.x, size.y, size.z) * 0.6;
  const distance = Math.max(distanceX, distanceY, 0.5) * 1.25 + depthPad;
  const direction = focusDirection(view);
  if (view === 'top') camera.up.set(0, 0, -1);
  else camera.up.set(0, 1, 0);
  camera.position.copy(center).addScaledVector(direction, distance);
  camera.lookAt(center);
  camera.updateMatrixWorld(true);
  return center;
}

function findNodeByPath(index, path) {
  return index.byPath.get(path) || null;
}

function findFirstClass(index, className) {
  return nodesOfClass(index, className)[0] || null;
}

// A Sky or Atmosphere only counts inside Lighting, as in Roblox: one saved in a model
// (which lands in Workspace when inserted) changes nothing.
function findLightingClass(index, className) {
  const nodes = nodesOfClass(index, className);
  return nodes.find(node => index.rootByNode.get(node)?.className === 'Lighting') || null;
}

function sceneGeometryBounds() {
  const box = new THREE.Box3();
  let count = 0;
  scene.traverse(object => {
    if (!object.isMesh || !object.userData?.rhrNode) return;
    box.expandByObject(object);
    count += 1;
  });
  return count && !box.isEmpty() ? box : null;
}

// A cube map from six images. Roblox stretches each sky face over its square, whatever
// the image's own size (sky uploads are often 1023x682 and the like); WebGL needs six
// equal squares, so every face is drawn onto one first.
// Quarter turns per cube face (+X, -X, +Y, -Y, +Z, -Z), clockwise on the canvas.
const SKY_FACE_TURNS = [0, 0, -1, 0, 0, 0];

async function loadSquareCube(urls) {
  const images = await Promise.all(urls.map(url => new Promise(resolve => {
    const image = new Image();
    image.crossOrigin = 'anonymous';  // from this render's data server; drawn to a canvas below
    image.onload = () => resolve(image);
    image.onerror = () => resolve(null);
    image.src = dataUrl(url);
  })));
  if (images.some(image => !image)) return null;
  const largest = Math.max(...images.map(image => Math.max(image.naturalWidth, image.naturalHeight)));
  const size = Math.min(1024, 2 ** Math.ceil(Math.log2(Math.max(16, largest))));
  const faces = images.map((image, face) => {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = size;
    const context = canvas.getContext('2d');
    // Roblox's SkyboxUp is turned a quarter against THREE's +Y face (matched against
    // Studio looking straight up: only this turn lines its clouds up).
    const turn = SKY_FACE_TURNS[face] || 0;
    if (turn) {
      context.translate(size / 2, size / 2);
      context.rotate(turn * Math.PI / 2);
      context.translate(-size / 2, -size / 2);
    }
    context.drawImage(image, 0, 0, size, size);
    return canvas;
  });
  const cube = new THREE.CubeTexture(faces);
  cube.colorSpace = THREE.SRGBColorSpace;
  cube.needsUpdate = true;
  return cube;
}

async function configureSky(index) {
  const sky = findLightingClass(index, 'Sky');
  if (!sky) return false;
  const props = sky.props || {};
  const manifest = await sceneAssetManifest;
  const faceIds = {
    right: contentAssetId(props.SkyboxRt),
    left: contentAssetId(props.SkyboxLf),
    up: contentAssetId(props.SkyboxUp),
    down: contentAssetId(props.SkyboxDn),
    back: contentAssetId(props.SkyboxBk),
    front: contentAssetId(props.SkyboxFt),
  };
  const urls = [
    // Checked in Studio: looking toward +X shows SkyboxLf, toward -X SkyboxRt
    // (THREE's cube faces go +X, -X, +Y, -Y, +Z, -Z in this order).
    manifest[faceIds.right],
    manifest[faceIds.left],
    manifest[faceIds.up],
    manifest[faceIds.down],
    manifest[faceIds.back],
    manifest[faceIds.front],
  ];
  if (urls.some(url => !url)) return false;

  const cube = await loadSquareCube(urls);
  if (!cube) return false;
  scene.background = cube;

  const orientation = props.SkyboxOrientation;
  if (orientation && scene.backgroundRotation) {
    scene.backgroundRotation.set(
      THREE.MathUtils.degToRad(Number(orientation.X ?? 0)),
      THREE.MathUtils.degToRad(Number(orientation.Y ?? 0)),
      THREE.MathUtils.degToRad(Number(orientation.Z ?? 0)),
    );
  }
  return true;
}

// Atmosphere, measured in Studio (a Roblox template's lighting; black and white
// panels 25 to 800 studs from the camera, Density 0.2 / 0.375 / 0.6, Haze 0 / 2 / 5),
// in linear light:
//
// - Geometry keeps exp(-(depth / L)^p) of its own light and takes the rest from the
//   fog colour. L and p depend steeply on Density: about 7900 studs and 1.8 at 0.2
//   (almost nothing fades), 512 and 1.6 at 0.375 (half gone at about 400 studs), 77
//   and 1.25 at 0.6 (gone by 200). Between and beyond, log L and p are interpolated
//   linearly. Haze hardly changes it.
// - Haze veils the sky: below the horizon it is the fog colour once Haze reaches 1,
//   above it a band about 1.5 x Haze degrees high blends in, and from Haze 5 the whole
//   sky is fog-coloured.
// - The fog colour lies between Color and Decay, nearer Decay.
const FOG_KNOTS = [[0.2, Math.log(7900), 1.8], [0.375, Math.log(512), 1.6], [0.6, Math.log(77), 1.25]];

function fogCurve(density) {
  if (density <= 0.05) return null;
  let a = FOG_KNOTS[0];
  let b = FOG_KNOTS[1];
  if (density > FOG_KNOTS[1][0]) { a = FOG_KNOTS[1]; b = FOG_KNOTS[2]; }
  const t = (density - a[0]) / (b[0] - a[0]);
  const logL = a[1] + (b[1] - a[1]) * t;
  const power = Math.max(1.0, Math.min(2.0, a[2] + (b[2] - a[2]) * t));
  return {length: Math.exp(Math.min(logL, 12)) * TUNE.fogL, power};
}

let atmosphereState = null;
let fogPowerCompiled = null;  // the exponent in the shared fog shader code, once set

function configureAtmosphere(index) {
  const atmosphere = findLightingClass(index, 'Atmosphere');
  if (!atmosphere) return;
  const props = atmosphere.props || {};
  const color = colorValue(props.Color, 0xc7d4e4);
  const decay = colorValue(props.Decay, 0x6b7480);
  const density = Math.max(0, Number(props.Density ?? 0.395));
  const haze = Math.max(0, Number(props.Haze ?? 0));
  const curve = fogCurve(density);
  const fogColor = color.clone().lerp(decay, TUNE.fogDecayMix);
  if (curve) {
    // FogExp2's density carries 1 / L; the exponent is compiled into the fog chunk,
    // before any material is compiled.
    const power = curve.power.toFixed(3);
    if (fogPowerCompiled !== null && fogPowerCompiled !== power) {
      // Shaders compiled for another exponent would be reused: this page cannot draw
      // this scene. The worker loads a fresh page and draws it there.
      throw new Error('RHR_NEEDS_FRESH_PAGE: fog exponent changed');
    }
    fogPowerCompiled = power;
    THREE.ShaderChunk.fog_fragment = THREE.ShaderChunk.fog_fragment.replace(
      'float fogFactor = 1.0 - exp( - fogDensity * fogDensity * vFogDepth * vFogDepth );',
      `float fogFactor = 1.0 - exp( - pow( fogDensity * vFogDepth, ${power} ) );`,
    );
    scene.fog = new THREE.FogExp2(fogColor, 1 / curve.length);
  }
  atmosphereState = {fogColor, haze, curve};
  // No sky image: the default gradient sky keeps the atmosphere colour at the horizon.
  atmosphereHorizon = fogColor.clone();
}

// A sky cube drawn on a dome around the camera, so the Atmosphere can veil it the
// way Roblox does (see configureAtmosphere).
// Clouds (Terrain.Clouds), drawn in the sky dome as one layer above the camera that
// curves down to meet the horizon, as Roblox's does (its layer ends about 0.4 degrees
// above the horizon). The cloud shapes come from the flat cloud tile Roblox ships
// for devices without 3D textures (content/sky/cloudsfb.dds, two octaves). Fitted to
// Studio at the highest quality, looking 25 degrees up: Cover opens the layer
// steeply (none at 0.35, about 5% of the sky at 0.5, 70% at 0.65, all of it from
// 0.8), Density makes the clouds more opaque, and they come out grey (sRGB about
// 0.73 scattered, 0.64 overcast) times Color, darker as the sun sets. Roblox's clouds
// change shape over time even with no wind; RHR draws one fixed layout.
let cloudState = null;
let sunState = null;

// The sun: Sky.SunTextureId (Roblox's own sun from the install when unset), added
// onto the sky where the sun is, under the clouds; none when CelestialBodiesShown is
// off. Fitted to Studio's default sun seen straight up (its disc sits exactly on
// Lighting:GetSunDirection()): the texture, slightly blurred, drawn 1.16 x
// SunAngularSize across at 0.7 brightness gives the same white disc and soft rim.
async function prepareSun(index) {
  sunState = null;
  const sky = findLightingClass(index, 'Sky');
  const props = sky?.props || {};
  if (props.CelestialBodiesShown === false) return;
  const texture = await loadSceneTexture(props.SunTextureId || 'rbxasset://sky/sun.jpg');
  if (!texture) return;
  const size = Math.max(0, Math.min(60, Number(props.SunAngularSize ?? 21)));
  sunState = {texture, size};
}

async function prepareClouds(index) {
  cloudState = null;
  const node = nodesOfClass(index, 'Clouds')[0];
  if (!node || node.props?.Enabled === false) return;
  const texture = await loadStudioTexture('sky_clouds', 1);
  if (!texture) return;
  const props = node.props || {};
  const cover = TUNE.cCover >= 0 ? TUNE.cCover : Number(props.Cover ?? 0.5);
  const density = TUNE.cDensity >= 0 ? TUNE.cDensity : Number(props.Density ?? 0.7);
  cloudState = {node, texture, cover, density, color: colorValue(props.Color, 0xffffff)};
}

function cloudUniforms() {
  const c = cloudState;
  return {
    cloudOn: {value: c ? 1 : 0},
    clouds: {value: c ? c.texture : null},
    cloudCover: {value: c ? c.cover : 0},
    cloudDensity: {value: c ? c.density : 0},
    cloudColor: {value: c ? c.color.clone() : new THREE.Color(1, 1, 1)},
    cloudShape: {value: new THREE.Vector4(TUNE.cHeight / TUNE.cTile, TUNE.cCurve, TUNE.cEdge, TUNE.cSoft)},
    cloudFit: {value: new THREE.Vector4(TUNE.cCov0, TUNE.cCov1, TUNE.cOpacity, TUNE.cCore)},
    cloudShade: {value: new THREE.Vector2(TUNE.cBright, TUNE.cDark)},
    cloudSun: {value: new THREE.Vector3(0, 1, 0)},
    sunOn: {value: sunState ? 1 : 0},
    sunTex: {value: sunState ? sunState.texture : null},
    sunTan: {value: sunState ? Math.tan(THREE.MathUtils.degToRad(sunState.size * TUNE.sunScale) / 2) : 1},
    sunGain: {value: TUNE.sunGain},
    sunBlur: {value: TUNE.sunBlur},
    cloudLook: {value: new THREE.Vector3(TUNE.cOct, TUNE.cLod, TUNE.cHaze)},
    cloudShade2: {value: new THREE.Vector2(TUNE.cDensPow, 0)},
  };
}

function makeSkyDome(cube) {
  const haze = atmosphereState ? atmosphereState.haze : 0;
  const material = new THREE.ShaderMaterial({
    uniforms: {
      ...cloudUniforms(),
      sky: {value: cube},
      fogColor: {value: atmosphereState ? atmosphereState.fogColor.clone() : new THREE.Color(1, 1, 1)},
      haze: {value: haze},
      intensity: {value: TUNE.skyBg},
      rotation: {value: new THREE.Matrix3()},
    },
    vertexShader: `
varying vec3 vDir;
void main() {
  vDir = position;
  vec4 p = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  gl_Position = p.xyww;
}`,
    fragmentShader: `
uniform samplerCube sky; uniform vec3 fogColor; uniform float haze; uniform float intensity;
uniform mat3 rotation;
uniform float cloudOn; uniform sampler2D clouds; uniform float cloudCover; uniform float cloudDensity;
uniform vec3 cloudColor; uniform vec4 cloudShape; uniform vec4 cloudFit; uniform vec2 cloudShade; uniform vec3 cloudSun; uniform vec3 cloudLook; uniform vec2 cloudShade2;
uniform float sunOn; uniform sampler2D sunTex; uniform float sunTan; uniform float sunGain; uniform float sunBlur;
varying vec3 vDir;
vec3 rhrToLinear( vec3 c ) { return pow( c, vec3( 2.2 ) ); }
float overcastK( float cover ) { return 3.0 * smoothstep( 0.7, 0.85, cover ); }
void main() {
  vec3 d = normalize(vDir);
  vec3 s = rotation * d;
  vec3 c = textureCube(sky, vec3(-s.x, s.y, s.z)).rgb * intensity;
  if ( sunOn > 0.5 ) {
    vec3 sd = normalize( cloudSun );
    float facing = dot( d, sd );
    if ( facing > 0.0 && sd.y > -0.2 ) {
      vec3 right = normalize( cross( abs( sd.y ) < 0.99 ? vec3( 0.0, 1.0, 0.0 ) : vec3( 1.0, 0.0, 0.0 ), sd ) );
      vec3 up = cross( sd, right );
      vec2 q = vec2( dot( d, right ), dot( d, up ) ) / facing / sunTan;
      if ( abs( q.x ) < 1.0 && abs( q.y ) < 1.0 ) c += texture2D( sunTex, q * 0.5 + 0.5, sunBlur ).rgb * sunGain * smoothstep( 1.0, 0.8, length( q ) );
    }
  }
  if ( cloudOn > 0.5 && d.y > cloudShape.z ) {
    // Distance to a layer that curves down to the horizon, in tiles per unit height.
    float reach = 1.0 / sqrt( d.y * d.y + cloudShape.y );
    vec2 p = d.xz * cloudShape.x * reach;
    float n = ( 1.0 - cloudLook.x ) * texture2D( clouds, p, cloudLook.y ).r + cloudLook.x * texture2D( clouds, p * 2.7 + vec2( 0.31, 0.17 ), cloudLook.y ).r;
    // Toward the horizon the pattern gets finer than a pixel: settle to its mean.
    n = mix( n, 0.24, smoothstep( 6.0, 30.0, reach ) );
    float core = smoothstep( 0.0, 0.25, n - ( cloudFit.x - cloudFit.y * ( cloudCover - 0.5 ) * 2.0 ) );
    // Cover sets the threshold: the tile's value where cloud starts.
    float threshold = cloudFit.x - cloudFit.y * ( cloudCover - 0.5 ) * 2.0;
    float body = smoothstep( threshold - cloudShape.w, threshold + cloudShape.w, n + ( cloudCover >= 0.999 ? 1.0 : 0.0 ) );
    // Opacity builds up with thickness: thin edges see-through, thick middles solid.
    float alpha = body * ( 1.0 - exp( - cloudFit.z * pow( cloudDensity, cloudShade2.x ) * ( 0.15 + 1.6 * core + overcastK( cloudCover ) ) ) );
    alpha *= smoothstep( cloudShape.z, cloudShape.z + 0.004, d.y );
    // Low broken clouds are seen through more air: fainter toward the horizon (an
    // overcast layer stays solid down to it).
    alpha *= mix( mix( cloudLook.z, 1.0, smoothstep( 0.0, 0.4, d.y ) ), 1.0, smoothstep( 0.7, 0.8, cloudCover ) );
    float overcast = smoothstep( 0.6, 1.0, cloudCover );
    // Thin edges bright, thick middles grey; one flat grey when overcast.
    float grey = mix( mix( cloudShade.x, cloudFit.w, core ), cloudShade.y, overcast );
    float daylight = mix( 0.12, 1.0, smoothstep( -0.1, 0.25, cloudSun.y ) );
    c = mix( c, rhrToLinear( vec3( grey ) ) * cloudColor * daylight, clamp( alpha, 0.0, 1.0 ) );
  }
  float elevation = degrees(asin(clamp(d.y, -1.0, 1.0)));
  float veil;
  if (elevation < 0.0) veil = clamp(haze, 0.0, 1.0);
  else veil = max(clamp((haze - 2.0) / 3.0, 0.0, 1.0), haze > 0.0 ? exp(-elevation / (1.5 * haze)) : 0.0);
  gl_FragColor = vec4(mix(c, fogColor, veil), 1.0);
  #include <colorspace_fragment>
}`,
    side: THREE.BackSide,
    depthWrite: false,
    depthTest: false,
    fog: false,
  });
  const dome = new THREE.Mesh(new THREE.SphereGeometry(1, 48, 24), material);
  dome.frustumCulled = false;
  dome.renderOrder = -1000;
  dome.userData.rhrSkyDome = true;
  dome.onBeforeRender = (_renderer, _scene, camera) => {
    if (sunDirection) material.uniforms.cloudSun.value.copy(sunDirection);
    dome.position.copy(camera.position);
    dome.scale.setScalar(camera.far * 0.5);
    dome.updateMatrixWorld(true);
  };
  return dome;
}

// Sky visibility: how much of the sky each place can see. Roblox's modern lighting
// keeps a voxel grid of the world and lights surfaces with the sky only as far as
// the sky is visible from them: the wall behind a pillar, the floor under an
// overhang and the inside of a room are much darker than open ground, while the
// sun still lights whatever it reaches. This builds the same kind of grid: parts
// and terrain are rasterized into 4-stud cells (a fraction of each cell filled),
// then from every open cell next to geometry, 16 directions over the upper
// hemisphere are marched through the grid and the light that gets through is
// averaged. Surfaces sample the grid just in front of themselves, and their sky
// and ambient light is scaled by it (sun light is not: it has its own shadows).
let terrainGrid = null;  // set by addTerrain: {chunks, n, voxelStuds, solid}
let skyVisibility = null;

const SKY_DIRECTIONS = (() => {
  // Cosine-weighted directions over the upper hemisphere (golden-angle spiral).
  const out = [];
  const count = 16;
  for (let i = 0; i < count; i += 1) {
    const u = (i + 0.5) / count;
    const r = Math.sqrt(u);
    const phi = i * 2.399963;
    out.push([r * Math.cos(phi), Math.sqrt(1 - u), r * Math.sin(phi)]);
  }
  return out;
})();

function buildSkyVisibility(camera) {
  const boxes = [];
  const worldBox = new THREE.Box3();
  scene.traverse(object => {
    const node = object.userData?.rhrNode;
    if (!object.isMesh || !node || object.userData.rhrTerrain) return;
    if (object.userData.rhrPlaceholder) return;
    const material = Array.isArray(object.material) ? object.material[0] : object.material;
    if (material.transparent && material.opacity < 0.5) return;
    object.geometry.computeBoundingBox();
    const local = object.geometry.boundingBox;
    const box = local.clone().applyMatrix4(object.matrixWorld);
    worldBox.union(box);
    const shape = node.className === 'Part' ? (node.props?.Shape?.name || 'Block') : node.className;
    const weight = shape === 'Block' ? 1 : (shape === 'WedgePart' || shape === 'CornerWedgePart' || shape === 'Wedge') ? 0.5
      : (shape === 'Cylinder' || shape === 'Ball') ? 0.7 : 0.6;
    boxes.push({matrix: object.matrixWorld.clone(), local, box, weight});
  });
  if (terrainGrid) {
    for (const chunk of terrainGrid.chunks.values()) {
      const [cx, cy, cz] = chunk.position;
      const size = terrainGrid.n * terrainGrid.voxelStuds;
      worldBox.union(new THREE.Box3(new THREE.Vector3(cx * size, cy * size, cz * size),
        new THREE.Vector3((cx + 1) * size, (cy + 1) * size, (cz + 1) * size)));
    }
  }
  if (!boxes.length && !terrainGrid) return;
  // The grid covers the geometry near the camera, at most 1200 x 400 x 1200 studs.
  const focus = camera.position;
  const min = worldBox.min.clone().max(new THREE.Vector3(focus.x - 600, focus.y - 200, focus.z - 600));
  const max = worldBox.max.clone().min(new THREE.Vector3(focus.x + 600, focus.y + 200, focus.z + 600));
  if (min.x >= max.x || min.y >= max.y || min.z >= max.z) return;
  let V = 4;
  const cells = () => Math.ceil((max.x - min.x) / V + 2) * Math.ceil((max.y - min.y) / V + 2) * Math.ceil((max.z - min.z) / V + 2);
  while (cells() > 3_000_000) V *= 2;
  // Align to the terrain's 4-stud grid.
  min.set(Math.floor(min.x / V) * V - V, Math.floor(min.y / V) * V - V, Math.floor(min.z / V) * V - V);
  const nx = Math.ceil((max.x - min.x) / V) + 2;
  const ny = Math.ceil((max.y - min.y) / V) + 2;
  const nz = Math.ceil((max.z - min.z) / V) + 2;
  const occ = new Float32Array(nx * ny * nz);
  const at = (x, y, z) => x + nx * (y + ny * z);
  const inverse = new THREE.Matrix4();
  const p = new THREE.Vector3();
  const samples = [0.25, 0.75];
  for (const item of boxes) {
    const x0 = Math.max(0, Math.floor((item.box.min.x - min.x) / V));
    const x1 = Math.min(nx - 1, Math.floor((item.box.max.x - min.x) / V));
    const y0 = Math.max(0, Math.floor((item.box.min.y - min.y) / V));
    const y1 = Math.min(ny - 1, Math.floor((item.box.max.y - min.y) / V));
    const z0 = Math.max(0, Math.floor((item.box.min.z - min.z) / V));
    const z1 = Math.min(nz - 1, Math.floor((item.box.max.z - min.z) / V));
    if (x0 > x1 || y0 > y1 || z0 > z1) continue;
    const e = item.matrix.elements;
    const axisAligned = [0, 1, 2, 4, 5, 6, 8, 9, 10].every(k => Math.abs(e[k]) < 1e-4 || Math.abs(Math.abs(e[k]) - 1) < 1e-4);
    inverse.copy(item.matrix).invert();
    // Thin rotated parts are thickened to half a cell so the samples cannot miss them.
    const thick = item.local.clone();
    for (const axis of ['x', 'y', 'z']) {
      const half = (thick.max[axis] - thick.min[axis]) / 2;
      const scale = new THREE.Vector3().setFromMatrixColumn(item.matrix, 'xyz'.indexOf(axis)).length() || 1;
      const need = V / 4 / scale;
      if (half < need) {
        const mid = (thick.max[axis] + thick.min[axis]) / 2;
        thick.min[axis] = mid - need;
        thick.max[axis] = mid + need;
      }
    }
    for (let z = z0; z <= z1; z += 1) for (let y = y0; y <= y1; y += 1) for (let x = x0; x <= x1; x += 1) {
      let fraction;
      if (axisAligned) {
        const ox = Math.max(0, Math.min(item.box.max.x, min.x + (x + 1) * V) - Math.max(item.box.min.x, min.x + x * V));
        const oy = Math.max(0, Math.min(item.box.max.y, min.y + (y + 1) * V) - Math.max(item.box.min.y, min.y + y * V));
        const oz = Math.max(0, Math.min(item.box.max.z, min.z + (z + 1) * V) - Math.max(item.box.min.z, min.z + z * V));
        // What blocks light through a cell is how much of it a part covers, not its
        // volume: a 1-stud roof over a 4-stud cell blocks the sky completely.
        fraction = Math.max(ox * oy, oy * oz, ox * oz) / (V * V);
        if (ox <= 0 || oy <= 0 || oz <= 0) fraction = 0;
      } else {
        let inside = 0;
        for (const sx of samples) for (const sy of samples) for (const sz of samples) {
          p.set(min.x + (x + sx) * V, min.y + (y + sy) * V, min.z + (z + sz) * V).applyMatrix4(inverse);
          if (thick.containsPoint(p)) inside += 1;
        }
        fraction = inside / 8;
      }
      if (fraction > 0) {
        const i = at(x, y, z);
        occ[i] = Math.min(1, occ[i] + fraction * item.weight);
      }
    }
  }
  if (terrainGrid) {
    const {chunks, n, voxelStuds, solid} = terrainGrid;
    for (const chunk of chunks.values()) {
      const [cx, cy, cz] = chunk.position;
      for (let i = 0; i < n * n * n; i += 1) {
        const material = chunk.materials[i];
        if (!solid(material)) continue;
        const lx = i % n, lz = Math.floor(i / n) % n, ly = Math.floor(i / (n * n));
        const x = Math.floor(((cx * n + lx + 0.5) * voxelStuds - min.x) / V);
        const y = Math.floor(((cy * n + ly + 0.5) * voxelStuds - min.y) / V);
        const z = Math.floor(((cz * n + lz + 0.5) * voxelStuds - min.z) / V);
        if (x < 0 || y < 0 || z < 0 || x >= nx || y >= ny || z >= nz) continue;
        const k = at(x, y, z);
        occ[k] = Math.min(1, occ[k] + (chunk.occupancy[i] / 255) * (voxelStuds / V) ** 3);
      }
    }
  }
  const vis = new Float32Array(nx * ny * nz).fill(1);
  const maxSteps = Math.max(8, Math.round(TUNE.aoReach / V));
  const shell = (x, y, z) => {
    for (const [dx, dy, dz] of [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]]) {
      const X = x + dx, Y = y + dy, Z = z + dz;
      if (X >= 0 && Y >= 0 && Z >= 0 && X < nx && Y < ny && Z < nz && occ[at(X, Y, Z)] > 0.05) return true;
    }
    return false;
  };
  for (let z = 0; z < nz; z += 1) for (let y = 0; y < ny; y += 1) for (let x = 0; x < nx; x += 1) {
    const i = at(x, y, z);
    if (occ[i] >= 0.5 || !shell(x, y, z)) continue;
    let sum = 0;
    for (const [dx, dy, dz] of SKY_DIRECTIONS) {
      let transmit = 1;
      let px = x + 0.5, py = y + 0.5, pz = z + 0.5;
      for (let s = 0; s < maxSteps && transmit > 0.02; s += 1) {
        px += dx; py += dy; pz += dz;
        const X = Math.floor(px), Y = Math.floor(py), Z = Math.floor(pz);
        if (X < 0 || Y < 0 || Z < 0 || X >= nx || Y >= ny || Z >= nz) break;
        transmit *= 1 - occ[at(X, Y, Z)];
      }
      sum += transmit;
    }
    vis[i] = sum / SKY_DIRECTIONS.length;
  }
  // Filled cells take their open neighbours' value, so filtering at a surface does
  // not mix in the "open sky" of a cell that is really inside a wall.
  const final = new Uint8Array(nx * ny * nz);
  for (let z = 0; z < nz; z += 1) for (let y = 0; y < ny; y += 1) for (let x = 0; x < nx; x += 1) {
    const i = at(x, y, z);
    let value = vis[i];
    if (occ[i] >= 0.5) {
      let sum = 0, count = 0;
      for (const [dx, dy, dz] of [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]]) {
        const X = x + dx, Y = y + dy, Z = z + dz;
        if (X < 0 || Y < 0 || Z < 0 || X >= nx || Y >= ny || Z >= nz) continue;
        const j = at(X, Y, Z);
        if (occ[j] < 0.5) { sum += vis[j]; count += 1; }
      }
      value = count ? sum / count : 1;
    }
    final[i] = Math.round(Math.max(0, Math.min(1, value)) * 255);
  }
  const texture = new THREE.Data3DTexture(final, nx, ny, nz);
  texture.format = THREE.RedFormat;
  texture.type = THREE.UnsignedByteType;
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.unpackAlignment = 1;
  texture.needsUpdate = true;
  skyVisibility = {
    texture: {value: texture},
    min: {value: min.clone()},
    size: {value: new THREE.Vector3(nx * V, ny * V, nz * V)},
    offset: {value: V * 0.6},
    strength: {value: TUNE.aoK},
  };
  // Every lit material reads the grid (see withSkyVisibility).
  scene.traverse(object => {
    if (!object.isMesh) return;
    for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
      if (material.isMeshStandardMaterial) withSkyVisibility(material);
    }
  });
}

function withSkyVisibility(material) {
  if (material.userData.rhrSkyVisibility) return;
  material.userData.rhrSkyVisibility = true;
  const previous = material.onBeforeCompile;
  const previousKey = material.customProgramCacheKey;
  material.onBeforeCompile = (shader, renderer) => {
    if (previous) previous.call(material, shader, renderer);
    shader.uniforms.rhrSkyVis = skyVisibility.texture;
    shader.uniforms.rhrSkyMin = skyVisibility.min;
    shader.uniforms.rhrSkySize = skyVisibility.size;
    shader.uniforms.rhrSkyOffset = skyVisibility.offset;
    shader.uniforms.rhrSkyStrength = skyVisibility.strength;
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <lights_pars_begin>', `#include <lights_pars_begin>
uniform highp sampler3D rhrSkyVis;
uniform vec3 rhrSkyMin;
uniform vec3 rhrSkySize;
uniform float rhrSkyOffset;
uniform float rhrSkyStrength;`)
      .replace('#include <lights_fragment_end>', `{
  vec3 rhrN = transformNormalByInverseViewMatrix( geometryNormal, viewMatrix );
  vec3 rhrP = ( ( vec4( geometryPosition, 1.0 ) - viewMatrix[ 3 ] ) * viewMatrix ).xyz + rhrN * rhrSkyOffset;
  vec3 rhrUV = ( rhrP - rhrSkyMin ) / rhrSkySize;
  float rhrVis = 1.0;
  if ( all( greaterThan( rhrUV, vec3( 0.0 ) ) ) && all( lessThan( rhrUV, vec3( 1.0 ) ) ) ) rhrVis = texture( rhrSkyVis, rhrUV ).r;
  rhrVis = mix( 1.0, rhrVis, rhrSkyStrength );
  #if defined( RE_IndirectDiffuse )
    irradiance *= rhrVis;
    iblIrradiance *= rhrVis;
  #endif
  #if defined( RE_IndirectSpecular )
    radiance *= rhrVis;
  #endif
}
#include <lights_fragment_end>`);
  };
  material.customProgramCacheKey = () => `${previousKey ? previousKey.call(material) : ''}|rhr-sky-visibility`;
  material.needsUpdate = true;
}

// Modern lighting (Lighting.EnvironmentDiffuseScale above 0, as in every current
// Roblox template): the sun, plus light from the sky itself, which is what gives
// Roblox's shadows and shaded faces their sky-blue colour. The sky light comes from
// the sky as it is drawn, Atmosphere veil included, prefiltered into an environment
// map; it also gives surfaces their sky reflections (EnvironmentSpecularScale).
// Ambient / OutdoorAmbient add a little flat light. Strengths are fitted to Studio
// screenshots of a calibration rig under a template's lighting (tests/studio notes
// in docs/known-approximations.md).
function modernLighting(index) {
  const lighting = findFirstClass(index, 'Lighting');
  const envDiffuse = Number(lighting?.props?.EnvironmentDiffuseScale ?? 0);
  return Boolean(lighting) && envDiffuse > 0;
}

function configureModernEnvironment(index, sky) {
  const props = findFirstClass(index, 'Lighting')?.props || {};
  const envDiffuse = Math.max(0, Math.min(1, Number(props.EnvironmentDiffuseScale ?? 1)));
  const skyScene = new THREE.Scene();
  if (sky) skyScene.add(makeSkyDome(sky));
  else skyScene.background = scene.background;
  const generator = new THREE.PMREMGenerator(renderer);
  const cubeCamera = generator.fromScene(skyScene, 0, 0.1, 100);
  generator.dispose();
  scene.environment = cubeCamera.texture;
  scene.environmentIntensity = TUNE.skyK * envDiffuse;
  environmentTexture = cubeCamera.texture;
}

let atmosphereHorizon = null;

// Lighting.ClockTime, or its saved form TimeOfDay ("hh:mm:ss"); null when absent.
function clockTime(props) {
  const direct = Number(props.ClockTime);
  if (props.ClockTime !== undefined && Number.isFinite(direct)) return direct;
  const match = /^(-?\d+):(\d+):(\d+)/.exec(String(props.TimeOfDay ?? ''));
  if (!match) return null;
  return Number(match[1]) + Number(match[2]) / 60 + Number(match[3]) / 3600;
}

let sunLight = null;
let sunDirection = null;

// The shadow map covers what the camera looks at, not the scene's whole bounds: a
// 512-stud Baseplate made one 1024px map blur every shadow into a smudge.
// Shadows reach this far from the camera; the two cascades split the distance.
const SHADOW_DISTANCE = 500;

function fitSunShadow() {
  // The SunLight fits its cascades to the view camera on every render.
}

// Roblox draws its default sky when a place has no Sky object: the sky512 cube in
// the Studio install (rhr.studio converts it into the cache). Faces go in the same
// order as a Sky object's (see configureSky).
async function studioDefaultSky() {
  const studio = (await extrasManifest).studio || {};
  const urls = ['sky_rt', 'sky_lf', 'sky_up', 'sky_dn', 'sky_bk', 'sky_ft'].map(name => studio[name]);
  if (urls.some(url => !url)) return null;
  return loadSquareCube(urls);
}

// The sky, prefiltered for reflections (metals, glass). A gradient cube stands in
// when the sky is not a cube image.
function configureEnvironment(index) {
  if (!environmentMaterials.size) return;
  let cube = scene.background?.isCubeTexture ? scene.background : null;
  if (!cube) {
    const faces = [];
    for (let face = 0; face < 6; face += 1) {
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = 16;
      const context = canvas.getContext('2d');
      if (face === 2) context.fillStyle = '#5eb4dc';
      else if (face === 3) context.fillStyle = '#7a7d80';
      else {
        const gradient = context.createLinearGradient(0, 0, 0, 16);
        gradient.addColorStop(0, '#6fbde0');
        gradient.addColorStop(0.5, '#c4e2ea');
        gradient.addColorStop(0.5001, '#8a8d90');
        gradient.addColorStop(1, '#7a7d80');
        context.fillStyle = gradient;
      }
      context.fillRect(0, 0, 16, 16);
      faces.push(canvas);
    }
    cube = new THREE.CubeTexture(faces);
    cube.colorSpace = THREE.SRGBColorSpace;
    cube.needsUpdate = true;
  }
  const generator = new THREE.PMREMGenerator(renderer);
  environmentTexture = generator.fromCubemap(cube).texture;
  generator.dispose();
  const lighting = findFirstClass(index, 'Lighting');
  const specular = Number(lighting?.props?.EnvironmentSpecularScale ?? 1);
  // Roblox metals stay readable with EnvironmentSpecularScale 0; keep some sky in them.
  const intensity = Math.max(0.35, Math.min(1, Number.isFinite(specular) ? specular : 1));
  for (const material of environmentMaterials) {
    material.envMap = environmentTexture;
    material.envMapIntensity = intensity;
    material.needsUpdate = true;
  }
}

// Without a Studio install: a vertical gradient sampled from Studio's default sky
// (zenith blue to pale horizon).
function defaultSkyTexture(horizon = null) {
  const canvas = document.createElement('canvas');
  canvas.width = 2;
  canvas.height = 256;
  const context = canvas.getContext('2d');
  const gradient = context.createLinearGradient(0, 0, 0, canvas.height);
  const mix = (hex, amount) => {
    if (!horizon) return hex;
    return '#' + new THREE.Color(hex).lerp(horizon, amount).getHexString(THREE.SRGBColorSpace);
  };
  gradient.addColorStop(0, '#5eb4dc');
  gradient.addColorStop(0.7, mix('#a6d6e6', 0.45));
  gradient.addColorStop(1, mix('#c4e2ea', 0.8));
  context.fillStyle = gradient;
  context.fillRect(0, 0, canvas.width, canvas.height);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function configureSceneLights(index) {
  const lighting = findFirstClass(index, 'Lighting');
  const props = lighting?.props || {};
  configureEffectLight(lighting);
  const hasLighting = Boolean(lighting);
  const ambient = hasLighting ? colorValue(props.Ambient, 0x808080) : new THREE.Color(0xddeeff);
  const outdoor = hasLighting ? colorValue(props.OutdoorAmbient, 0x808080) : new THREE.Color(0x334455);
  const brightness = Math.max(0, Number(hasLighting ? (props.Brightness ?? 1) : 1));
  const bounds = sceneGeometryBounds();
  const center = bounds ? bounds.getCenter(new THREE.Vector3()) : new THREE.Vector3();
  const span = bounds ? Math.max(...bounds.getSize(new THREE.Vector3()).toArray(), 1) : 12;

  // Balance calibrated by eye against Studio screenshots of the same scene and camera
  // (default Lighting): faces away from the sun stay clearly lit by the sky and
  // ambient, as in Roblox, rather than falling to near-black. Ambient/OutdoorAmbient
  // light everything regardless of Brightness; the sky light scales with Brightness
  // like the sun, so Brightness 0 leaves only the ambient.
  const modern = modernLighting(index);
  // A sun with two shadow cascades over the view (three.js SunLight add-on): sharp
  // shadows near the camera and shadows out to SHADOW_DISTANCE studs.
  const key = new SunLight(0xfff6e8, 1.25 * brightness);
  if (modern) {
    // The sky light is the environment map (configureModernEnvironment).
    scene.add(new THREE.AmbientLight(ambient.clone().add(outdoor).multiplyScalar(0.5), TUNE.ambK));
    key.color.setRGB(TUNE.sunR, TUNE.sunG, TUNE.sunB);
    key.intensity = TUNE.sunK * brightness;
  } else {
    scene.add(new THREE.AmbientLight(ambient.clone().add(outdoor).multiplyScalar(0.5), hasLighting ? 2.0 : 1.6));
    // EnvironmentDiffuseScale is Roblox's sky light (modern templates set it to 1); it
    // lifts every surface, most visibly the faces turned away from the sun. Scale set
    // by eye against the Roblox template place.
    const envDiffuse = hasLighting ? Math.max(0, Math.min(1, Number(props.EnvironmentDiffuseScale ?? 0))) : 0;
    scene.add(new THREE.HemisphereLight(0xbcd7ff, outdoor, ((hasLighting ? 0.6 : 0.7) + 0.9 * envDiffuse) * brightness));
  }
  let direction;
  const clock = clockTime(props);
  if (hasLighting && clock !== null) {
    // Roblox's sun (Lighting:GetSunDirection, sampled in Studio at 6/9/12/14/18h):
    // rises at +X, sets at -X, tilted toward +Z by sin(latitude - 23.5 degrees).
    const tilt = THREE.MathUtils.degToRad(Number(props.GeographicLatitude ?? 41.7333) - 23.5);
    const arc = ((clock - 6) / 12) * Math.PI;
    direction = new THREE.Vector3(
      Math.cos(arc) * Math.cos(tilt),
      Math.sin(arc) * Math.cos(tilt),
      Math.sin(tilt),
    );
    // Below the horizon the moon lights the scene from the opposite side; at the
    // horizon itself (6:00, 18:00) the sun still grazes from its own side.
    if (direction.y < 0) direction.negate();
    direction.y = Math.max(direction.y, 0.05);
    direction.normalize();
  } else {
    direction = new THREE.Vector3(6, 10, 8).normalize();
  }
  // A SunLight shines from its position toward the origin.
  key.position.copy(direction);

  if (shadowsRequested && props.GlobalShadows !== false) {
    key.castShadow = true;
    const softness = Math.max(0, Math.min(1, Number(props.ShadowSoftness ?? 0.5)));
    renderer.shadowMap.type = THREE.PCFShadowMap;
    // Filter radius in shadow-map texels: a soft edge about half a stud wide near the
    // camera, as Roblox's modern shadows have.
    key.shadow.radius = 2 + softness * 4;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.camera.near = 0.1;
    key.shadow.camera.far = SHADOW_DISTANCE;
    key.shadow.bias = -0.0005;
    key.shadow.normalBias = 0.03;
  }
  scene.add(key);
  sunLight = key;
  sunDirection = direction.clone();

}

function configureViewportLights(node) {
  const ambient = colorValue(node.props?.Ambient, 0xc8c8c8);
  const lightColor = colorValue(node.props?.LightColor, 0x8c8c8c);
  scene.add(new THREE.HemisphereLight(ambient, 0x000000, 1.0));
  const light = new THREE.DirectionalLight(lightColor, 1.5);
  const direction = node.props?.LightDirection;
  light.position.set(Number(direction?.X ?? -1), Number(direction?.Y ?? -1), Number(direction?.Z ?? -1));
  scene.add(light);
}

// Resolve a reference property (Attachment0, Adornee, PrimaryPart) of `node`: by the
// target's id when the IR has one, else by an unambiguous full name, else null.
// Never by "first instance anywhere with that name".
function findNodeByReference(index, node, property) {
  const id = node?.refs?.[property];
  if (id !== undefined && id !== null) return index.byId.get(id) || null;
  const key = String(node?.props?.[property] || '');
  if (!key || index.ambiguousReferences.has(key)) return null;
  return index.byReference.get(key) || null;
}

function findBillboards(index) {
  return nodesOfClass(index, 'BillboardGui').map(node => ({
    node,
    parent: index.parentByNode.get(node) || null,
  }));
}

// In-world UI is drawn by the same 2D engine as ScreenGuis: the page asks the local
// server to render the GUI subtree at its canvas size and places the PNG. A failed
// render fails the page (data-rhr-error) instead of leaving the GUI out.
async function renderGuiImage(node, canvasWidth, canvasHeight) {
  const response = await fetch('/__rhr_gui__.png', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      path: node.path,
      width: Math.max(1, Math.round(canvasWidth)),
      height: Math.max(1, Math.round(canvasHeight)),
    }),
  });
  if (!response.ok) throw new Error(`in-world GUI ${node.path}: ${await response.text()}`);
  const image = document.createElement('img');
  image.src = URL.createObjectURL(await response.blob());
  await image.decode();
  image.style.position = 'absolute';
  image.style.inset = '0';
  image.style.width = '100%';
  image.style.height = '100%';
  return image;
}

function hasGuiContent(node) {
  return Object.values(node.children || {}).some(child => GUI_OBJECT_CLASSES.has(child.className));
}

const GUI_OBJECT_CLASSES = new Set([
  'Frame', 'CanvasGroup', 'ScrollingFrame', 'TextLabel', 'TextButton', 'TextBox',
  'ImageLabel', 'ImageButton', 'ViewportFrame', 'VideoFrame',
]);

function parentWorldPosition(parent, billboard, camera) {
  const cf = parent?.props?.CFrame;
  if (!cf) return null;
  const position = new THREE.Vector3(Number(cf.X), Number(cf.Y), Number(cf.Z));
  const right = new THREE.Vector3(Number(cf.R00), Number(cf.R10), Number(cf.R20));
  const up = new THREE.Vector3(Number(cf.R01), Number(cf.R11), Number(cf.R21));
  const back = new THREE.Vector3(Number(cf.R02), Number(cf.R12), Number(cf.R22));
  const local = billboard.props?.StudsOffset;
  const world = billboard.props?.StudsOffsetWorldSpace;
  if (local) position.addScaledVector(right, Number(local.X || 0)).addScaledVector(up, Number(local.Y || 0)).addScaledVector(back, Number(local.Z || 0));
  if (world) position.add(new THREE.Vector3(Number(world.X || 0), Number(world.Y || 0), Number(world.Z || 0)));
  const size = parent.props?.Size || {};
  const half = new THREE.Vector3(Number(size.X || 0) / 2, Number(size.Y || 0) / 2, Number(size.Z || 0) / 2);
  const extents = billboard.props?.ExtentsOffset;
  if (extents && camera) {
    const cameraRight = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0).normalize();
    const cameraUp = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1).normalize();
    const cameraBack = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 2).normalize();
    position.addScaledVector(cameraRight, Number(extents.X || 0) * half.x);
    position.addScaledVector(cameraUp, Number(extents.Y || 0) * half.y);
    position.addScaledVector(cameraBack, Number(extents.Z || 0) * half.z);
  }
  const extentsWorld = billboard.props?.ExtentsOffsetWorldSpace;
  if (extentsWorld) {
    position.add(new THREE.Vector3(
      Number(extentsWorld.X || 0) * half.x,
      Number(extentsWorld.Y || 0) * half.y,
      Number(extentsWorld.Z || 0) * half.z,
    ));
  }
  return position;
}

function overlayZIndex(alwaysOnTop, depth, zOffset = 0) {
  const layer = Math.round(Number(zOffset || 0) * 10);
  if (alwaysOnTop) return String(200000 + layer);
  return String(Math.max(1, 100000 - Math.round(Math.max(0, depth) * 100) + layer));
}

function isOccluded(anchor, point, camera) {
  if (!anchor || !point || !camera) return false;
  const direction = point.clone().sub(camera.position);
  const distance = direction.length();
  if (distance <= 1e-6) return false;
  direction.normalize();
  const raycaster = new THREE.Raycaster(camera.position, direction, 0, distance);
  return raycaster.intersectObjects(scene.children, true).some(hit => {
    if (hit.object.userData?.rhrDecoration) return false;
    const node = hit.object.userData?.rhrNode;
    const cf = node?.props?.CFrame;
    const sameAnchor = node === anchor || (cf && new THREE.Vector3(Number(cf.X), Number(cf.Y), Number(cf.Z)).distanceTo(point) < 1e-4);
    return !sameAnchor && hit.distance < distance - 0.01;
  });
}

async function addBillboards(index, camera) {
  const overlay = document.querySelector('#rhr-overlay');
  if (!overlay) return;
  for (const {node, parent} of findBillboards(index)) {
    if (node.props?.Enabled === false) continue;
    const anchor = node.props?.Adornee ? findNodeByReference(index, node, 'Adornee') : parent;
    const world = parentWorldPosition(anchor, node, camera);
    if (!world) continue;
    const cameraPoint = camera.worldToLocal(world.clone());
    const depth = -cameraPoint.z;
    const maxDistance = Number(node.props?.MaxDistance ?? 0);
    if (depth <= 0 || (maxDistance > 0 && depth > maxDistance)) continue;
    if (node.props?.AlwaysOnTop !== true && isOccluded(anchor, world, camera)) continue;
    const projected = world.clone().project(camera);
    const size = node.props?.Size;
    const widthStuds = Number(size?.XS ?? 0);
    const heightStuds = Number(size?.YS ?? 0);
    const widthOffset = Number(size?.XO ?? 0);
    const heightOffset = Number(size?.YO ?? 0);
    const scale = height / (2 * Math.tan((camera.fov * Math.PI) / 360) * depth);
    // Whole pixels: the GUI image is rendered at exactly this size and placed on a
    // pixel boundary, so it is never resampled (a resampled image blurs text).
    const widthPx = Math.max(1, Math.round(widthStuds * scale + widthOffset));
    const heightPx = Math.max(1, Math.round(heightStuds * scale + heightOffset));
    const root = document.createElement('div');
    const sizeOffset = node.props?.SizeOffset || {};
    const sizeOffsetX = Number(sizeOffset.X || 0);
    const sizeOffsetY = Number(sizeOffset.Y || 0);
    root.style.position = 'absolute';
    root.style.left = `${Math.round((projected.x * 0.5 + 0.5) * width - widthPx / 2 + sizeOffsetX * widthPx)}px`;
    root.style.top = `${Math.round((-projected.y * 0.5 + 0.5) * height - heightPx / 2 - sizeOffsetY * heightPx)}px`;
    root.style.width = `${widthPx}px`;
    root.style.height = `${heightPx}px`;
    root.style.zIndex = overlayZIndex(Boolean(node.props?.AlwaysOnTop), depth);
    root.style.pointerEvents = 'none';
    if (hasGuiContent(node)) root.appendChild(await renderGuiImage(node, widthPx, heightPx));
    overlay.appendChild(root);
  }
}

function findSurfaceGuis(index) {
  return nodesOfClass(index, 'SurfaceGui').map(node => ({
    node,
    parent: index.parentByNode.get(node) || null,
  }));
}

function localToWorld(part, local) {
  const cf = part?.props?.CFrame;
  if (!cf) return null;
  const position = new THREE.Vector3(Number(cf.X), Number(cf.Y), Number(cf.Z));
  const right = new THREE.Vector3(Number(cf.R00), Number(cf.R10), Number(cf.R20));
  const up = new THREE.Vector3(Number(cf.R01), Number(cf.R11), Number(cf.R21));
  const back = new THREE.Vector3(Number(cf.R02), Number(cf.R12), Number(cf.R22));
  return position.addScaledVector(right, local.x).addScaledVector(up, local.y).addScaledVector(back, local.z);
}

function surfaceCorners(part, surface) {
  const dimensions = part?.props?.Size;
  if (!dimensions) return null;
  const sx = Number(dimensions.X || 1) / 2;
  const sy = Number(dimensions.Y || 1) / 2;
  const sz = Number(dimensions.Z || 1) / 2;
  const face = surface.props?.Face?.name || 'Front';
  // Corner order is the GUI's top-left, top-right, bottom-right, bottom-left, as
  // measured in Studio with an asymmetric SurfaceGui on each face of a part.
  if (face === 'Right') return [[sx, sy, sz], [sx, sy, -sz], [sx, -sy, -sz], [sx, -sy, sz]];
  if (face === 'Left') return [[-sx, sy, -sz], [-sx, sy, sz], [-sx, -sy, sz], [-sx, -sy, -sz]];
  if (face === 'Top') return [[-sx, sy, sz], [-sx, sy, -sz], [sx, sy, -sz], [sx, sy, sz]];
  if (face === 'Bottom') return [[sx, -sy, sz], [sx, -sy, -sz], [-sx, -sy, -sz], [-sx, -sy, sz]];
  if (face === 'Back') return [[-sx, sy, sz], [sx, sy, sz], [sx, -sy, sz], [-sx, -sy, sz]];
  return [[sx, sy, -sz], [-sx, sy, -sz], [-sx, -sy, -sz], [sx, -sy, -sz]];
}

function surfaceHomography(points, width, height) {
  const [p0, p1, p2, p3] = points;
  const dx1 = p1.x - p2.x;
  const dx2 = p3.x - p2.x;
  const dx3 = p0.x - p1.x + p2.x - p3.x;
  const dy1 = p1.y - p2.y;
  const dy2 = p3.y - p2.y;
  const dy3 = p0.y - p1.y + p2.y - p3.y;
  const denominator = dx1 * dy2 - dx2 * dy1;
  let a;
  let b;
  let c;
  let d;
  let e;
  let f;
  let g;
  let h;
  if (Math.abs(denominator) < 1e-8) {
    a = p1.x - p0.x; b = p3.x - p0.x; c = 0;
    d = p1.y - p0.y; e = p3.y - p0.y; f = 0;
    g = p0.x; h = p0.y;
  } else {
    g = (dx3 * dy2 - dx2 * dy3) / denominator;
    h = (dx1 * dy3 - dx3 * dy1) / denominator;
    a = p1.x - p0.x + g * p1.x;
    b = p3.x - p0.x + h * p3.x;
    c = p0.x;
    d = p1.y - p0.y + g * p1.y;
    e = p3.y - p0.y + h * p3.y;
    f = p0.y;
  }
  return `matrix3d(${a / width},${d / width},0,${g / width},${b / height},${e / height},0,${h / height},0,0,1,0,${c},${f},0,1)`;
}

async function addSurfaceGuis(index, camera) {
  const overlay = document.querySelector('#rhr-overlay');
  if (!overlay) return;
  for (const {node, parent} of findSurfaceGuis(index)) {
    if (node.props?.Enabled === false) continue;
    const anchor = node.props?.Adornee ? findNodeByReference(index, node, 'Adornee') : parent;
    const localCorners = surfaceCorners(anchor, node);
    if (!localCorners) continue;
    const worldPoints = localCorners.map(corner => localToWorld(anchor, new THREE.Vector3(...corner)));
    // A SurfaceGui is one-sided: from behind its face Studio shows the bare part.
    const faceCenter = worldPoints.reduce((sum, point) => sum.add(point), new THREE.Vector3()).multiplyScalar(1 / worldPoints.length);
    // Outward normal: (bottom-left - top-left) x (top-right - top-left).
    const faceNormal = new THREE.Vector3().subVectors(worldPoints[3], worldPoints[0])
      .cross(new THREE.Vector3().subVectors(worldPoints[1], worldPoints[0]));
    if (faceNormal.dot(new THREE.Vector3().subVectors(camera.position, faceCenter)) <= 0) continue;
    const points = worldPoints.map(world => world?.clone().project(camera));
    if (points.some(point => !point || point.z < -1 || point.z > 1)) continue;
    const depths = worldPoints.map(world => -camera.worldToLocal(world.clone()).z);
    const depth = depths.reduce((sum, value) => sum + value, 0) / depths.length;
    const maxDistance = Number(node.props?.MaxDistance ?? 0);
    if (depth <= 0 || (maxDistance > 0 && depth > maxDistance)) continue;
    const center = localToWorld(anchor, new THREE.Vector3(0, 0, 0));
    if (node.props?.AlwaysOnTop !== true && isOccluded(anchor, center, camera)) continue;
    const screen = points.map(point => ({x: (point.x * 0.5 + 0.5) * width, y: (-point.y * 0.5 + 0.5) * height}));
    const left = Math.min(...screen.map(point => point.x));
    const top = Math.min(...screen.map(point => point.y));
    const right = Math.max(...screen.map(point => point.x));
    const bottom = Math.max(...screen.map(point => point.y));
    if (right <= left || bottom <= top) continue;
    const faceWidth = new THREE.Vector3(...localCorners[0]).distanceTo(new THREE.Vector3(...localCorners[1]));
    const faceHeight = new THREE.Vector3(...localCorners[1]).distanceTo(new THREE.Vector3(...localCorners[2]));
    const sizingMode = node.props?.SizingMode?.name;
    const canvasSize = node.props?.CanvasSize || {};
    const pixelsPerStud = Number(node.props?.PixelsPerStud || 50);
    const virtualWidth = sizingMode === 'FixedSize' ? Number(canvasSize.X || 1) : faceWidth * pixelsPerStud;
    const virtualHeight = sizingMode === 'FixedSize' ? Number(canvasSize.Y || 1) : faceHeight * pixelsPerStud;
    const root = document.createElement('div');
    root.style.position = 'absolute';
    root.style.left = `${left}px`;
    root.style.top = `${top}px`;
    root.style.width = `${right - left}px`;
    root.style.height = `${bottom - top}px`;
    root.style.clipPath = `polygon(${screen.map(point => `${(point.x - left) / (right - left) * 100}% ${(point.y - top) / (bottom - top) * 100}%`).join(',')})`;
    root.style.zIndex = overlayZIndex(Boolean(node.props?.AlwaysOnTop), depth, node.props?.ZOffset);
    if (hasGuiContent(node)) {
      const canvasElement = document.createElement('div');
      canvasElement.style.position = 'absolute';
      canvasElement.style.inset = '0';
      canvasElement.style.transformOrigin = '0 0';
      canvasElement.style.transform = surfaceHomography(
        screen.map(point => ({x: point.x - left, y: point.y - top})),
        right - left,
        bottom - top,
      );
      canvasElement.appendChild(await renderGuiImage(node, virtualWidth, virtualHeight));
      root.appendChild(canvasElement);
    }
    overlay.appendChild(root);
  }
}

async function reportNotes() {
  const notes = [];
  if (cloudState) notes.push(`clouds drawn as one still layer (Cover ${cloudState.cover.toFixed(2)}, Density ${cloudState.density.toFixed(2)}; Roblox's change shape over time)`);
  if (terrainSummary) {
    notes.push(`terrain drawn smooth (${terrainSummary.materials.join(', ')}); materials blended where they meet (approximate)`);
    if (terrainSummary.grassBlades) notes.push(`terrain grass drawn at rest (${terrainSummary.grassBlades} blades; Roblox animates it)`);
  }
  if (meshParseFailures.length) {
    notes.push(`${meshParseFailures.length} cached mesh file(s) could not be read and are drawn as boxes (${meshParseFailures.slice(0, 3).join('; ')})`);
  }
  if (localLightsDropped) {
    notes.push(`drew the ${MAX_LOCAL_LIGHTS} most relevant local lights; ${localLightsDropped} farther ones were left out`);
  }
  if (particleState.emitters.length || particleState.idle.length) {
    const played = particleState.emitters.filter(emitter => emitter.schedule.played).length;
    const when = particleState.auto ? `${particleState.time.toFixed(2)} s into the effect (the fullest moment; --effect-time T picks another)` : `${particleState.time.toFixed(2)} s into the effect`;
    notes.push(`particles: ${particleState.drawn} drawn from ${particleState.emitters.length} emitter(s)${played ? `, ${played} played from their EmitCount/EmitDelay/EmitDuration attributes, at ${when}` : ''}`);
  }
  if (particleState.idle.length) {
    notes.push(`${particleState.idle.length} ParticleEmitter(s) are disabled and have no EmitCount/EmitDuration attributes: a script plays them, so they are not drawn (${particleState.idle.slice(0, 3).join(', ')}${particleState.idle.length > 3 ? ', ...' : ''})`);
  }
  if (particleState.orphan) {
    notes.push(`${particleState.orphan} ParticleEmitter(s) are not inside a part or attachment and are not drawn`);
  }
  if (particleState.missingTextures.size) {
    notes.push(`${particleState.missingTextures.size} particle texture(s) could not be loaded, so those particles are not drawn (as in Studio): ${[...particleState.missingTextures].slice(0, 3).join(', ')}`);
  }
  if (framingIgnored.length) {
    notes.push(`framing left out ground ${framingIgnored.join(', ')} (still drawn; --focus <path> frames it)`);
  }
  if (!notes.length) return;
  try {
    await fetch('/__rhr_notes__.json', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(notes),
    });
  } catch (_) {
    // Notes are advisory; a failed post must not fail the render.
  }
}

async function reportCamera(camera) {
  if (params.get('reportCamera') !== '1') return;
  try {
    await fetch('/__rhr_camera__.json', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        position: camera.position.toArray(),
        quaternion: camera.quaternion.toArray(),
        fov: camera.fov,
      }),
    });
  } catch (_) {
    // Camera reporting is optional metadata for callers such as `rhr preview`.
  }
}

function configureCamera(camera, node) {
  const cf = node?.props?.CFrame;
  if (cf) {
    const matrix = cframeMatrix(cf);
    matrix.decompose(camera.position, camera.quaternion, camera.scale);
  } else {
    camera.position.set(0, 5, 12);
    camera.lookAt(0, 0, 0);
  }
  const requestedFov = Number(params.get('fov'));
  camera.fov = Number.isFinite(requestedFov) && requestedFov > 1 && requestedFov < 179
    ? requestedFov
    : Number(node?.props?.FieldOfView ?? 70);
  camera.aspect = width / height;
  camera.near = 0.05;
  camera.far = 10000;
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld(true);
}

// Post-processing: Neon glow, Lighting's BloomEffect and ColorCorrectionEffect.
//
// Neon glows in Roblox whatever the place's effects: its parts are drawn again into
// a separate buffer at a fraction of the screen's resolution (half or quarter,
// depending on the graphics level), blurred, and added over the picture. Here that
// buffer is a quarter-resolution copy of the scene with Neon's brightness past white
// and everything else black (so geometry in front hides the glow), blurred with a
// separable Gaussian and added. Checked against Studio at its highest quality level,
// where Neon glows (at low quality levels Studio draws no glow and no post effects). BloomEffect adds the blurred parts of the picture
// brighter than its Threshold; ColorCorrectionEffect then adjusts brightness,
// contrast, saturation and tint. The scene is drawn into a half-float buffer so
// Neon can be brighter than white, as in Roblox's HDR renderer. Glow size and
// strength are set by eye.
const NEON_GLOW_STRENGTH = 0.9;
const NEON_GLOW_RADIUS_PX = 20;  // at 1080 px screen height; scales with the height
let postEffects = null;

function readPostEffects(index) {
  const lighting = nodesOfClass(index, 'Lighting')[0];
  const lightingIndex = lighting ? index : null;
  const children = lighting ? Object.values(lighting.children || {}) : [];
  const enabled = node => node.props?.Enabled !== false;
  const bloom = children.find(c => c.className === 'BloomEffect' && enabled(c)) || null;
  const rays = children.find(c => c.className === 'SunRaysEffect' && enabled(c)) || null;
  const corrections = children.filter(c => c.className === 'ColorCorrectionEffect' && enabled(c));
  const neon = [];
  scene.traverse(object => {
    if (object.isMesh && object.userData?.rhrNode?.props?.Material?.name === 'Neon') neon.push(object);
  });
  const exposure = Number(lighting?.props?.ExposureCompensation ?? 0);
  return {
    lighting: lightingIndex,
    neon,
    sunRays: rays && sunDirection ? {
      intensity: Math.max(0, Number(rays.props?.Intensity ?? 0.25)),
      spread: TUNE.rSpread >= 0 ? TUNE.rSpread : Math.max(0, Math.min(1, Number(rays.props?.Spread ?? 1))),
    } : null,
    bloom: bloom ? {
      intensity: Math.max(0, Number(bloom.props?.Intensity ?? 1)),
      size: Math.max(0, Number(bloom.props?.Size ?? 24)),
      threshold: Math.max(0, Number(bloom.props?.Threshold ?? 2)),
    } : null,
    corrections: corrections.map(c => ({
      brightness: Number(c.props?.Brightness ?? 0),
      contrast: Number(c.props?.Contrast ?? 0),
      saturation: Number(c.props?.Saturation ?? 0),
      tint: colorValue(c.props?.TintColor, 0xffffff),
    })),
    exposure: Number.isFinite(exposure) ? Math.max(-3, Math.min(3, exposure)) : 0,
    modern: modernLighting(index),
  };
}

const fullscreenCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
const fullscreenQuad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2));
const fullscreenScene = new THREE.Scene();
fullscreenScene.add(fullscreenQuad);

function drawFullscreen(material, target) {
  fullscreenQuad.material = material;
  renderer.setRenderTarget(target);
  renderer.render(fullscreenScene, fullscreenCamera);
}

const FULLSCREEN_VERTEX = `
varying vec2 vUv;
void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;

function blurMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: {source: {value: null}, direction: {value: new THREE.Vector2()}, sigma: {value: 4}},
    vertexShader: FULLSCREEN_VERTEX,
    fragmentShader: `
uniform sampler2D source; uniform vec2 direction; uniform float sigma;
varying vec2 vUv;
void main() {
  vec4 sum = vec4(0.0); float total = 0.0;
  for (int i = -24; i <= 24; i++) {
    float x = float(i);
    if (abs(x) > 3.0 * sigma + 1.0) continue;
    float w = exp(-0.5 * x * x / (sigma * sigma));
    sum += texture2D(source, vUv + direction * x) * w;
    total += w;
  }
  gl_FragColor = sum / total;
}`,
    depthTest: false,
    depthWrite: false,
  });
}

function makeTarget(w, h) {
  return new THREE.WebGLRenderTarget(Math.max(1, w), Math.max(1, h), {
    type: THREE.HalfFloatType,
    colorSpace: THREE.LinearSRGBColorSpace,
    depthBuffer: true,
    stencilBuffer: true,  // Highlights mark their shape in it
  });
}

// Blur `source` into `out` (same size) with a Gaussian of `sigma` texels.
function gaussian(source, scratch, out, sigma) {
  const material = blurMaterial();
  material.uniforms.sigma.value = Math.max(0.5, Math.min(16, sigma));
  material.uniforms.source.value = source.texture;
  material.uniforms.direction.value.set(1 / source.width, 0);
  drawFullscreen(material, scratch);
  material.uniforms.source.value = scratch.texture;
  material.uniforms.direction.value.set(0, 1 / source.height);
  drawFullscreen(material, out);
  material.dispose();
}

// Draw Neon parts only, in their colour; everything else black so it hides glow behind it.
function renderNeonBuffer(camera, target) {
  const black = new THREE.MeshBasicMaterial({color: 0x000000});
  const swapped = [];
  const background = scene.background;
  const fog = scene.fog;
  scene.background = null;
  scene.fog = null;
  scene.traverse(object => {
    if (!object.isMesh && !object.isLineSegments) return;
    const node = object.userData?.rhrNode;
    const neon = node?.props?.Material?.name === 'Neon' && Number(node.props?.Transparency ?? 0) < 0.98;
    swapped.push([object, object.material, object.visible]);
    if (neon) {
      const transparency = Math.max(0, Math.min(1, Number(node.props?.Transparency ?? 0)));
      // The glow is the Neon's own colour, faded out for dim Neon (Studio: white glows
      // white, cyan light cyan; grey and dark colours hardly glow).
      const glow = colorValue(node.props?.Color).multiplyScalar(neonBrightness(transparency));
      const peak = Math.max(glow.r, glow.g, glow.b);
      glow.multiplyScalar(THREE.MathUtils.smoothstep(peak, 0.8, 1.6) * (1 - transparency));
      object.material = new THREE.MeshBasicMaterial({color: glow});
    } else if (object.isLineSegments || object.userData?.rhrEffect || (object.material?.transparent && object.material.opacity < 0.5)) {
      object.visible = false;
    } else {
      object.material = black;
    }
  });
  const clearColor = renderer.getClearColor(new THREE.Color());
  const clearAlpha = renderer.getClearAlpha();
  renderer.setRenderTarget(target);
  renderer.setClearColor(0x000000, 1);
  renderer.clear();
  renderer.render(scene, camera);
  renderer.setClearColor(clearColor, clearAlpha);
  for (const [object, material, visible] of swapped) {
    if (object.material !== material && object.material !== black) object.material.dispose();
    object.material = material;
    object.visible = visible;
  }
  black.dispose();
  scene.background = background;
  scene.fog = fog;
}

// SunRaysEffect, fitted to Studio at its highest quality (a bar half across the sun,
// Intensity 0.1 / 0.25, Spread 0.1 / 0.3 / 1): a glow around the sun, as wide as
// Spread makes it, blurred toward the sun on screen through what is sky, so anything
// in front of the sun casts a long shadow through it (GPU Gems 3's light
// scattering). Drawn at quarter resolution and added before tone mapping; it still
// shows with the sun just off screen.
function renderSunRays(camera, rays, size, out) {
  const view = sunDirection.clone().transformDirection(camera.matrixWorldInverse);
  if (view.z > -0.05) return false;  // the sun is behind the camera
  const tanY = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2);
  const tanX = tanY * camera.aspect;
  const sunUv = new THREE.Vector2(0.5 + 0.5 * (view.x / -view.z) / tanX, 0.5 + 0.5 * (view.y / -view.z) / tanY);
  // What is sky: white, geometry black.
  const mask = makeTarget(...size);
  const hidden = [];
  scene.traverse(object => { if (object.userData?.rhrSkyDome && object.visible) { object.visible = false; hidden.push(object); } });
  const background = scene.background, fog = scene.fog;
  scene.background = new THREE.Color(1, 1, 1);
  scene.fog = null;
  const black = new THREE.MeshBasicMaterial({color: 0x000000});
  scene.overrideMaterial = black;
  renderer.setRenderTarget(mask);
  renderer.render(scene, camera);
  scene.overrideMaterial = null;
  black.dispose();
  scene.background = background;
  scene.fog = fog;
  for (const object of hidden) object.visible = true;
  const material = new THREE.ShaderMaterial({
    uniforms: {
      mask: {value: mask.texture}, sunUv: {value: sunUv}, sunView: {value: view.normalize()},
      tans: {value: new THREE.Vector2(tanX, tanY)},
      width: {value: THREE.MathUtils.degToRad(TUNE.rW0 + TUNE.rW1 * rays.spread)},
      // Narrower rays are brighter near the sun: the same light over a smaller glow.
      gain: {value: TUNE.rGain * rays.intensity * Math.pow((TUNE.rW0 + TUNE.rW1) / (TUNE.rW0 + TUNE.rW1 * rays.spread), TUNE.rK)}, density: {value: TUNE.rDensity}, decay: {value: TUNE.rDecay},
      veil: {value: TUNE.rVeil}, leak: {value: TUNE.rLeak}, veilWidth: {value: TUNE.rVeilW},
      sunColor: {value: sunColorForRays()},
    },
    vertexShader: FULLSCREEN_VERTEX,
    fragmentShader: `
uniform sampler2D mask; uniform vec2 sunUv; uniform vec3 sunView; uniform vec2 tans;
uniform float width; uniform float gain; uniform float density; uniform float decay; uniform vec3 sunColor; uniform float veil; uniform float leak; uniform float veilWidth;
varying vec2 vUv;
float glowAt( vec2 uv, float w ) {
  vec3 d = normalize( vec3( ( uv.x * 2.0 - 1.0 ) * tans.x, ( uv.y * 2.0 - 1.0 ) * tans.y, -1.0 ) );
  float angle = acos( clamp( dot( d, sunView ), -1.0, 1.0 ) );
  return exp( - angle / w );
}
float glow( vec2 uv ) { return glowAt( uv, width ); }
void main() {
  const int N = 64;
  vec2 stepUv = ( sunUv - vUv ) * density / float( N );
  vec2 uv = vUv;
  float weight = 1.0, sum = 0.0, total = 0.0;
  for ( int i = 0; i < N; i ++ ) {
    float inside = step( 0.0, uv.x ) * step( uv.x, 1.0 ) * step( 0.0, uv.y ) * step( uv.y, 1.0 );
    float sky = inside > 0.5 ? texture2D( mask, uv ).r : 1.0;
    sum += sky * glow( uv ) * weight;
    total += weight;
    weight *= decay;
    uv += stepUv;
  }
  // The sky gets the rays, shadows and all, plus a little glow that nothing blocks;
  // objects get a haze of the glow on top (Studio lightens the object in front of the
  // sun as well).
  float object = 1.0 - texture2D( mask, vUv ).r;
  float haze = glowAt( vUv, width * veilWidth );
  gl_FragColor = vec4( sunColor * gain * ( sum / total + ( veil * object + leak * ( 1.0 - object ) ) * haze ), 1.0 );
}`,
    depthTest: false,
    depthWrite: false,
  });
  drawFullscreen(material, out);
  material.dispose();
  mask.dispose();
  return true;
}

function sunColorForRays() {
  return new THREE.Color(TUNE.sunR, TUNE.sunG, TUNE.sunB);
}

function compositeMaterial(effects) {
  const corrections = effects.corrections;
  const uniforms = {
    scene: {value: null},
    neon: {value: null},
    bloom: {value: null},
    rays: {value: null},
    raysStrength: {value: 0},
    neonStrength: {value: effects.neon.length ? NEON_GLOW_STRENGTH : 0},
    bloomStrength: {value: effects.bloom ? effects.bloom.intensity : 0},
    exposure: {value: Math.pow(2, effects.exposure) * (effects.modern ? TUNE.exposure : 1)},
    tone: {value: effects.modern ? TUNE.tone : 0},
    ccBrightness: {value: corrections.reduce((sum, c) => sum + c.brightness, 0)},
    ccContrast: {value: corrections.reduce((product, c) => product * (1 + c.contrast), 1)},
    ccSaturation: {value: corrections.reduce((product, c) => product * (1 + c.saturation), 1)},
    ccTint: {value: corrections.reduce((tint, c) => tint.multiply(c.tint), new THREE.Color(1, 1, 1))},
  };
  return new THREE.ShaderMaterial({
    uniforms,
    vertexShader: FULLSCREEN_VERTEX,
    fragmentShader: `
uniform sampler2D scene; uniform sampler2D neon; uniform sampler2D bloom;
uniform sampler2D rays; uniform float raysStrength;
uniform float neonStrength; uniform float bloomStrength; uniform float exposure; uniform int tone;
uniform float ccBrightness; uniform float ccContrast; uniform float ccSaturation; uniform vec3 ccTint;
varying vec2 vUv;
vec3 toSRGB(vec3 c) {
  c = clamp(c, 0.0, 1.0);
  return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c));
}
void main() {
  vec3 color = texture2D(scene, vUv).rgb * exposure;
  color += texture2D(neon, vUv).rgb * neonStrength;
  color += texture2D(bloom, vUv).rgb * bloomStrength;
  color += texture2D(rays, vUv).rgb * raysStrength;
  color *= ccTint;
  if (tone == 1) {
    // ACES filmic (Narkowicz fit).
    color = clamp((color * (2.51 * color + 0.03)) / (color * (2.43 * color + 0.59) + 0.14), 0.0, 1.0);
  } else if (tone == 2) {
    // Reinhard on luminance-preserving max channel.
    float m = max(color.r, max(color.g, color.b));
    color *= (1.0 + m / 4.0) / (1.0 + m);
  } else if (tone == 3) {
    // Reinhard per channel: very bright colours drift toward white, as Roblox's do
    // (bright orange Neon turns yellow).
    color = color * (1.0 + color / 4.0) / (1.0 + color);
  }
  vec3 srgb = toSRGB(color);
  srgb += ccBrightness;
  srgb = (srgb - 0.5) * ccContrast + 0.5;
  float grey = dot(srgb, vec3(0.2126, 0.7152, 0.0722));
  srgb = mix(vec3(grey), srgb, ccSaturation);
  gl_FragColor = vec4(clamp(srgb, 0.0, 1.0), 1.0);
}`,
    depthTest: false,
    depthWrite: false,
  });
}

const TONE_GLSL = (() => {
  const f = PARTICLE_FIT;
  return `
vec3 rbxTone(vec3 pre) {
  pre = max(pre, vec3(1e-6));
  float m = max(pre.r, max(pre.g, pre.b));
  float mg = pow(m, ${f.g.toFixed(4)});
  float M = mg / (mg + ${f.c.toFixed(4)});
  vec3 r = pow(pre / m, vec3(${f.p.toFixed(4)}));
  vec3 x = pow(m, ${(1 - f.t).toFixed(4)}) * pow(pre, vec3(${f.t.toFixed(4)}));
  vec3 w = 1.0 - exp(-pow(x / ${f.m0.toFixed(4)}, vec3(${f.n.toFixed(4)})));
  return M * (r * (1.0 - w) + w);
}
vec3 rbxUntone(vec3 y) {
  y = clamp(y, 0.0, 0.999);
  return pow(${f.c.toFixed(4)} * y / (1.0 - y), vec3(1.0 / ${f.g.toFixed(4)}));
}`;
})();

// Particles in a scene that is not tone-mapped (no Lighting, or legacy lighting): the
// picture without them is taken back to Studio's HDR values (the inverse of its tone
// curve), the particles are blended there as Studio blends them, and the result is
// tone-mapped again. Only what the particles add is kept, so every pixel without a
// particle stays exactly as it was.
function compositeParticles(sceneTarget, camera) {
  const size = renderer.getSize(new THREE.Vector2());
  const hdr = makeTarget(size.x, size.y);
  const autoClear = renderer.autoClear;
  const clearColor = renderer.getClearColor(new THREE.Color());
  const clearAlpha = renderer.getClearAlpha();
  const background = scene.background;
  // Depth of what can hide particles: the opaque scene.
  const hidden = [];
  scene.traverse(object => {
    if ((object.isMesh || object.isLineSegments) && object.visible && (object.material?.transparent || object.userData?.rhrEffect)) {
      hidden.push(object);
      object.visible = false;
    }
  });
  const depthOnly = new THREE.MeshBasicMaterial({colorWrite: false});
  scene.overrideMaterial = depthOnly;
  scene.background = null;
  camera.layers.set(0);
  renderer.setRenderTarget(hdr);
  renderer.setClearColor(0x000000, 0);
  renderer.clear();
  renderer.render(scene, camera);
  scene.overrideMaterial = null;
  for (const object of hidden) object.visible = true;
  renderer.autoClear = false;
  const untone = new THREE.ShaderMaterial({
    uniforms: {source: {value: sceneTarget.texture}},
    vertexShader: FULLSCREEN_VERTEX,
    fragmentShader: `uniform sampler2D source; varying vec2 vUv; ${TONE_GLSL}
void main() { gl_FragColor = vec4(rbxUntone(texture2D(source, vUv).rgb), 1.0); }`,
    depthTest: false,
    depthWrite: false,
  });
  drawFullscreen(untone, hdr);
  // Still without the background: a flat sky texture (no Studio install) is drawn by
  // every render, and would cover the whole picture under the particles.
  camera.layers.set(PARTICLE_LAYER);
  renderer.setRenderTarget(hdr);
  renderer.render(scene, camera);
  scene.background = background;
  camera.layers.enable(0);
  renderer.autoClear = autoClear;
  renderer.setClearColor(clearColor, clearAlpha);
  const out = makeTarget(size.x, size.y);
  const combine = new THREE.ShaderMaterial({
    uniforms: {source: {value: sceneTarget.texture}, hdr: {value: hdr.texture}},
    vertexShader: FULLSCREEN_VERTEX,
    fragmentShader: `uniform sampler2D source; uniform sampler2D hdr; varying vec2 vUv; ${TONE_GLSL}
void main() {
  vec3 base = texture2D(source, vUv).rgb;
  vec3 shown = rbxTone(texture2D(hdr, vUv).rgb) - rbxTone(rbxUntone(base));
  gl_FragColor = vec4(max(base + shown, 0.0), 1.0);
}`,
    depthTest: false,
    depthWrite: false,
  });
  drawFullscreen(combine, out);
  for (const material of [depthOnly, untone, combine]) material.dispose();
  hdr.dispose();
  return out;
}

// Draw the frame: straight to the canvas when there is nothing to post-process.
function renderFrame(camera) {
  if (!postEffects) postEffects = readPostEffects(sceneIndex);
  const effects = postEffects;
  const separateParticles = !viewportMode && !effects.modern && particleState.drawn > 0;
  if (viewportMode || (!separateParticles && !effects.modern && !effects.neon.length && !effects.bloom && !effects.sunRays && !effects.corrections.length && !effects.exposure)) {
    renderer.setRenderTarget(null);
    renderer.render(scene, camera);
    return;
  }
  const size = renderer.getSize(new THREE.Vector2());
  let main = makeTarget(size.x, size.y);
  main.samples = 4;
  renderer.setRenderTarget(main);
  if (separateParticles) camera.layers.disable(PARTICLE_LAYER);
  renderer.render(scene, camera);
  if (separateParticles) {
    const withParticles = compositeParticles(main, camera);
    main.dispose();
    main = withParticles;
  }

  const scale = size.y / 1080;
  const quarter = [Math.ceil(size.x / 4), Math.ceil(size.y / 4)];
  const neonRaw = makeTarget(...quarter);
  const neonScratch = makeTarget(...quarter);
  const neonBlur = makeTarget(...quarter);
  if (effects.neon.length) {
    renderNeonBuffer(camera, neonRaw);
    gaussian(neonRaw, neonScratch, neonBlur, (NEON_GLOW_RADIUS_PX * scale) / 4);
  }
  const bloomBlur = makeTarget(...quarter);
  if (effects.bloom) {
    // Bright pass at quarter resolution: what is brighter than the threshold.
    const bright = new THREE.ShaderMaterial({
      uniforms: {source: {value: main.texture}, threshold: {value: effects.bloom.threshold * 0.5}},
      vertexShader: FULLSCREEN_VERTEX,
      fragmentShader: `
uniform sampler2D source; uniform float threshold; varying vec2 vUv;
void main() {
  vec3 c = texture2D(source, vUv).rgb;
  float l = max(c.r, max(c.g, c.b));
  gl_FragColor = vec4(c * max(0.0, l - threshold) / max(l, 1e-4), 1.0);
}`,
      depthTest: false,
      depthWrite: false,
    });
    drawFullscreen(bright, neonScratch);
    bright.dispose();
    const scratch = makeTarget(...quarter);
    gaussian(neonScratch, scratch, bloomBlur, (effects.bloom.size * scale) / 8);
    scratch.dispose();
  }
  const raysOut = makeTarget(...quarter);
  const raysOn = effects.sunRays ? renderSunRays(camera, effects.sunRays, quarter, raysOut) : false;
  const composite = compositeMaterial(effects);
  composite.uniforms.rays.value = raysOut.texture;
  composite.uniforms.raysStrength.value = raysOn ? 1 : 0;
  composite.uniforms.scene.value = main.texture;
  composite.uniforms.neon.value = neonBlur.texture;
  composite.uniforms.bloom.value = bloomBlur.texture;
  drawFullscreen(composite, null);
  composite.dispose();
  for (const target of [main, neonRaw, neonScratch, neonBlur, bloomBlur, raysOut]) target.dispose();
}

async function main() {
  const response = await fetch(params.get('ir') || '/__rhr_ir__.json');
  if (!response.ok) throw new Error(`IR request failed: ${response.status}`);
  const ir = await response.json();
  mark('IR fetched');
  const roots = ir.roots || [];
  const index = buildNodeIndex(roots);
  sceneIndex = index;
  use2022Materials = computeUse2022Materials(index);
  {
    const lighting = nodesOfClass(index, 'Lighting')[0];
    const value = Number(lighting?.props?.EnvironmentSpecularScale ?? (lighting ? 0 : 1));
    environmentSpecularScale = Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 1;
  }
  let camera;
  if (viewportMode) {
    const viewport = findNodeByPath(index, params.get('path') || '');
    if (!viewport) throw new Error(`ViewportFrame path not found: ${params.get('path')}`);
    configureViewportLights(viewport);
    for (const child of Object.values(viewport.children || {})) addNode(child, scene);
    await Promise.all(meshGeometryJobs);
    await Promise.all(materialTextureJobs);
    await stylePlaceholderMeshes();
    await dressCharacters(buildNodeIndex([viewport]));
    configureEnvironment(index);
    const cameraNode = findCamera(buildNodeIndex([viewport]));
    camera = new THREE.PerspectiveCamera();
    // Games assign CurrentCamera (a Camera instance) at runtime; the saved place
    // stores the authored pose in the ViewportFrame's own CameraCFrame property
    // instead. Prefer an explicit Camera child, then CameraCFrame, then fallback.
    configureCamera(camera, cameraNode || (viewport.props?.CameraCFrame ? { props: { CFrame: viewport.props.CameraCFrame } } : null));
    renderer.render(scene, camera);
  } else {
    const cameraNode = findCamera(index);
    for (const root of roots) addNode(root, scene);
    mark('parts built');
    await addTerrain(index);
    mark('terrain');
    await Promise.all(meshGeometryJobs);
    mark('meshes and unions loaded');
    await Promise.all(materialTextureJobs);
    await stylePlaceholderMeshes();
    mark('material textures loaded');
    await dressCharacters(index);
    mark('characters dressed');
    await addSurfaceImages(index);
    addAttachmentAnchors(index);
    mark('decals and attachments');
    if (params.get('effects') !== '0') simulateParticles(index);
    mark('particle simulation');
    addLocalLights(index);
    await configureSky(index);
    configureAtmosphere(index);
    if (!scene.background && findFirstClass(index, 'Lighting')) {
      scene.background = (await studioDefaultSky()) || defaultSkyTexture(atmosphereHorizon);
    }
    const skyCube = scene.background?.isCubeTexture ? scene.background : null;
    if (modernLighting(index)) {
      configureModernEnvironment(index, skyCube);
    } else {
      configureEnvironment(index);
    }
    await prepareClouds(index);
    await prepareSun(index);
    if (skyCube) {
      // Drawn as a dome so the Atmosphere can veil it.
      scene.background = null;
      scene.add(makeSkyDome(skyCube));
    }
    configureSceneLights(index);
    mark('sky, atmosphere and lights');
    camera = new THREE.PerspectiveCamera();
    camera.layers.enable(PARTICLE_LAYER);
    configureCamera(camera, cameraNode);

    const focusPath = params.get('focus');
    // A model with no Camera of its own (most .rbxm files) is framed as a whole rather
    // than seen from a fixed spot near the origin it may be nowhere near.
    const requestedView = params.get('view') || (!cameraNode && !parseVectorParam('camera') ? 'iso' : null);
    let framedCenter = null;
    if (focusPath || requestedView) {
      framedCenter = frameScene(camera, index, focusPath, requestedView || 'iso');
      // A framed view stands back as far as the build is big, which for a whole map
      // is hundreds of studs of fog. It exists to show the layout, so cap the fog at
      // about a quarter at the framed centre (exp(-(d*density)^2) = 0.75).
      if (scene.fog?.isFogExp2) {
        // At most a quarter fogged at the framed centre: (d / L)^p <= -ln(0.75).
        const distance = camera.position.distanceTo(framedCenter);
        const power = atmosphereState?.curve?.power || 1;
        scene.fog.density = Math.min(scene.fog.density, 0.2877 ** (1 / power) / Math.max(distance, 1));
      }
    }
    const cameraOverride = parseVectorParam('camera');
    const lookAtOverride = parseVectorParam('lookAt');
    if (cameraOverride) camera.position.copy(cameraOverride);
    if (lookAtOverride) camera.lookAt(lookAtOverride);
    else if (cameraOverride && framedCenter) camera.lookAt(framedCenter);
    camera.updateMatrixWorld(true);
    fitSunShadow(camera, lookAtOverride || framedCenter || null);
    pruneLocalLights(camera);
    mark('camera and framing');
    addTerrainGrass(camera);
    mark('terrain grass');
    if (modernLighting(index)) buildSkyVisibility(camera);
    mark('sky visibility grid');
    // --no-effects leaves out particles, Beams and Trails alike.
    if (params.get('effects') !== '0') {
      await addBeams(index, camera);
      await addTrails(index, camera);
    }
    await addParticles(camera);
    addHighlights(index);
    mark('effects built');
    await reportCamera(camera);
    await reportNotes();
    renderFrame(camera);
    mark('first frame (shaders compiled)');
  }
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  renderFrame(camera);
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  mark('second frame');
  if (!viewportMode) {
    await addBillboards(index, camera);
    await addSurfaceGuis(index, camera);
    mark('in-world UI');
  }
  if (profiling) {
    try {
      await fetch('/__rhr_timing__.json', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(pageMarks)});
    } catch (_) {
      // Timing is advisory.
    }
  }
  document.documentElement.dataset.rhrReady = 'true';
}

// Everything one render leaves behind, back to how a fresh page starts. Kept: the
// renderer and its compiled shaders, keptLoads, the Draco decoder, static files.
function resetScene() {
  // Scene meshes hold copies of kept geometry (fitted, scaled), never the kept one
  // itself, and disposing a material leaves its textures alone.
  scene.traverse(object => {
    if (object.geometry) object.geometry.dispose();
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    for (const material of materials) material?.dispose?.();
  });
  environmentTexture?.dispose?.();
  scene = new THREE.Scene();
  meshByNode.clear();
  anchorByNode.clear();
  for (const cache of [sceneTextureCache, sceneMeshGeometryCache, sceneDataTextureCache, sceneUnionCache,
    robloxMapCache, studioTextureCache, materialTextureCache]) cache.clear();
  meshGeometryJobs.length = 0;
  materialTextureJobs.length = 0;
  meshParseFailures.length = 0;
  robloxMaterialsUsed.clear();
  lookAlikeMaterialsUsed.clear();
  environmentMaterials.clear();
  framingIgnored.length = 0;
  use2022Materials = true;
  environmentTexture = null;
  environmentSpecularScale = 1;
  materialVariantsByName = null;
  sceneIndex = null;
  terrainSummary = null;
  terrainGrassSource = null;
  terrainGrid = null;
  skyVisibility = null;
  atmosphereState = null;
  atmosphereHorizon = null;
  sunLight = null;
  sunDirection = null;
  cloudState = null;
  sunState = null;
  postEffects = null;
  localLightsDropped = 0;
  charactersDressed = 0;
  layeredClothingFitted = 0;
  partsWithoutDecals.clear();
  for (const target of clothingTargets) target.dispose();
  clothingTargets.length = 0;
  Object.assign(particleState, {emitters: [], time: null, auto: false, idle: [], orphan: 0, missingTextures: new Set(), drawn: 0});
  effectSceneLight = new THREE.Color(1, 1, 1);
  Object.assign(highlightState, {drawn: 0, skipped: 0});
  document.querySelector('#rhr-overlay').replaceChildren();
  delete document.documentElement.dataset.rhrReady;
  delete document.documentElement.dataset.rhrError;
}

if (persistentPage) {
  // Called by the warm worker: draw one scene, resolve with {ok} or {error}.
  window.rhrRender = async ({query, base, width: w, height: h}) => {
    try {
      resetScene();
      dataBase = base || '';
      width = Math.max(1, w);
      height = Math.max(1, h);
      renderer.setSize(width, height, false);
      configure(query);
      await main();
      return {ok: true};
    } catch (error) {
      document.documentElement.dataset.rhrError = String(error);
      return {error: String(error)};
    }
  };
  document.documentElement.dataset.rhrPersistent = 'ready';
} else {
  try {
    await main();
  } catch (error) {
    document.documentElement.dataset.rhrError = String(error);
    throw error;
  }
}
