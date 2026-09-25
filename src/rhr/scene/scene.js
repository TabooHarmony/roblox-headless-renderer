import * as THREE from '../vendor/three/three.module.js';
import { SunLight } from '../vendor/three/lights/SunLight.js';
import { flipbookLayout, hashSeed, particleLook, playEmitter, playHorizon, playSchedule } from '../particles/sim.js';

const params = new URLSearchParams(location.search);
const viewportMode = params.get('mode') === 'viewport';
const canvas = document.querySelector('#rhr-scene');
if (viewportMode) document.body.style.background = 'transparent';
const width = Math.max(1, window.innerWidth);
const height = Math.max(1, window.innerHeight);
const renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: viewportMode});
renderer.setPixelRatio(1);
renderer.setSize(width, height, false);
renderer.outputColorSpace = THREE.SRGBColorSpace;
// Constants fitted against Studio (see configureAtmosphere, configureModernEnvironment).
// The `tune` query parameter (JSON, from RHR_SCENE_TUNE) overrides them while
// calibrating; normal renders never set it.
const TUNE = Object.assign({
  sunK: 1.625, skyK: 1.175, ambK: 0.1, skyBg: 1.0375, fogL: 1.0, fogDecayMix: 0.4375,
  exposure: 1.475, tone: 3, sunR: 1.0, sunG: 0.965, sunB: 0.91, pRough: 0.72, spRough: 0.33, aoK: 1.0, aoReach: 64,
}, (() => { try { return JSON.parse(params.get('tune') || '{}'); } catch (_) { return {}; } })());
// Shadows are on unless the caller turns them off (Studio draws them by default).
const shadowsRequested = !viewportMode && params.get('shadows') !== '0';
renderer.shadowMap.enabled = shadowsRequested;
renderer.shadowMap.type = THREE.PCFShadowMap;
renderer.setClearColor(viewportMode ? 0x000000 : 0x20242b, viewportMode ? 0 : 1);

const scene = new THREE.Scene();
const meshByNode = new Map();
const anchorByNode = new Map();
const sceneTextureCache = new Map();
const sceneMeshGeometryCache = new Map();
const meshGeometryJobs = [];
const materialTextureJobs = [];
const flatMaterials = params.get('flatMaterials') === '1';
const sceneAssetManifest = fetch('/__rhr_assets__.json')
  .then(response => response.ok ? response.json() : {})
  .catch(() => ({}));
const sceneMeshManifest = fetch('/__rhr_meshes__.json')
  .then(response => response.ok ? response.json() : {})
  .catch(() => ({}));

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
      uvs.push(Number(uv[0]), 1 - Number(uv[1]));
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
  const assetId = meshAssetId(uri);
  if (!assetId) return null;
  if (sceneMeshGeometryCache.has(assetId)) return sceneMeshGeometryCache.get(assetId);
  const promise = (async () => {
    const manifest = await sceneMeshManifest;
    const url = manifest[assetId];
    if (!url) return null;
    const response = await fetch(url);
    if (!response.ok) return null;
    return withoutBadVertices(await parseRobloxMesh(await response.arrayBuffer()));
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
    if (meshType === 'Sphere' || meshType === 'Head') {
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
const extrasManifest = fetch('/__rhr_extras__.json')
  .then(response => (response.ok ? response.json() : {}))
  .catch(() => ({}));
const robloxMaterialTable = flatMaterials
  ? Promise.resolve(null)
  : fetch('./roblox_materials.json').then(r => (r.ok ? r.json() : null)).catch(() => null);
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
    return new Promise(resolve => new THREE.TextureLoader().load(url, texture => {
      texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
      texture.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
      texture.colorSpace = color ? THREE.SRGBColorSpace : THREE.NoColorSpace;
      resolve(texture);
    }, undefined, () => resolve(null)));
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
const materialCredits = flatMaterials
  ? Promise.resolve({})
  : fetch('./materials/credits.json').then(r => (r.ok ? r.json() : {})).then(j => j.materials || {}).catch(() => ({}));
const materialTextureCache = new Map();

function loadMaterialTextures(name) {
  if (materialTextureCache.has(name)) return materialTextureCache.get(name);
  const promise = materialCredits.then(async credits => {
    const entry = credits[name];
    if (!entry) return null;
    const loader = new THREE.TextureLoader();
    const load = url => new Promise(resolve => loader.load(url, resolve, undefined, () => resolve(null)));
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

function applyMaterialTexture(mesh, materialName, geometryReady = Promise.resolve(), node = null, index = null) {
  if (flatMaterials || !materialName) return;
  if (surfaceAppearanceOf(node)) return;  // the SurfaceAppearance replaces the material's look
  const variant = node && index ? materialVariant(index, node, materialName) : null;
  if (!variant && ['Plastic', 'SmoothPlastic', 'Neon', 'Glass', 'ForceField'].includes(materialName)) {
    if (materialName === 'Plastic' || materialName === 'SmoothPlastic') applyPlasticDetail(mesh, node, geometryReady);
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
      return new Promise(resolve => new THREE.TextureLoader().load(url, texture => {
        texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
        texture.colorSpace = THREE.NoColorSpace;
        texture.repeat.set(1 / repeat, 1 / repeat);
        texture.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
        resolve(texture);
      }, undefined, () => resolve(null)));
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

function applyPlasticDetail(mesh, node, geometryReady) {
  const isBox = node?.className === 'Part' && ['Block', undefined].includes(node.props?.Shape?.name ?? node.props?.shape?.name);
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
    if (!tiles.some(Boolean)) return;
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
  }
  applyMaterialTexture(mesh, materialName, geometryReady, node, sceneIndex);
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
// Each face takes the material of its solid voxel, and the texture for its
// direction (Roblox gives Grass, Asphalt and others separate top, side and bottom
// textures), projected along the face's main axis in world space. Where two
// materials meet the edge is hard; Roblox blends them. Water is its own surface,
// only where it meets air.
let terrainSummary = null;

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
      corner.push({ox, oy, oz, inside: isInside(material), occupancy});
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
  return {positions, normals, quads};
}

// One geometry per (material, texture direction), with world-space box-projected UVs.
function terrainGeometries(surface, faceKind) {
  const {positions, normals, quads} = surface;
  const groups = new Map();
  for (const quad of quads) {
    const [a, b, c, d, material] = quad;
    const ny = (normals[a * 3 + 1] + normals[b * 3 + 1] + normals[c * 3 + 1] + normals[d * 3 + 1]) / 4;
    const kind = faceKind(ny);
    const groupKey = `${material}|${kind}`;
    let group = groups.get(groupKey);
    if (!group) groups.set(groupKey, group = {material, kind, positions: [], normals: [], uvs: []});
    for (const index of [a, b, c, a, c, d]) {
      const x = positions[index * 3], y = positions[index * 3 + 1], z = positions[index * 3 + 2];
      const nx = normals[index * 3], nyv = normals[index * 3 + 1], nz = normals[index * 3 + 2];
      group.positions.push(x, y, z);
      group.normals.push(nx, nyv, nz);
      const ax = Math.abs(nx), ay = Math.abs(nyv), az = Math.abs(nz);
      if (ay >= ax && ay >= az) group.uvs.push(x / TERRAIN_TILE_STUDS, z / TERRAIN_TILE_STUDS);
      else if (ax >= az) group.uvs.push(z / TERRAIN_TILE_STUDS, y / TERRAIN_TILE_STUDS);
      else group.uvs.push(x / TERRAIN_TILE_STUDS, y / TERRAIN_TILE_STUDS);
    }
  }
  return [...groups.values()].map(group => {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(group.positions, 3));
    geometry.setAttribute('normal', new THREE.Float32BufferAttribute(group.normals, 3));
    geometry.setAttribute('uv', new THREE.Float32BufferAttribute(group.uvs, 2));
    return {geometry, material: group.material, kind: group.kind, triangles: group.positions.length / 9};
  });
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
  const kindOf = ny => (ny > 0.5 ? 'top' : ny < -0.5 ? 'bottom' : 'side');
  const jobs = [];
  let triangles = 0;
  const materialsDrawn = new Set();
  for (const part of [...terrainGeometries(ground, kindOf), ...terrainGeometries(water, () => 'top')]) {
    const name = names[part.material];
    const isWater = part.material === WATER;
    materialsDrawn.add(name);
    triangles += part.triangles;
    const raw = terrain.rawColors?.[name];
    const natural = terrain.colors?.[name];
    const color = isWater
      ? colorValue(terrainNode?.props?.WaterColor, 0x0c545c)
      : new THREE.Color().setRGB(...(natural || [128, 128, 128]).map(c => c / 255), THREE.SRGBColorSpace);
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
    if (isWater || flatMaterials) continue;
    jobs.push((async () => {
      // A MaterialVariant override: its image in real colours, tinted by the place's
      // MaterialColor (white leaves it as is).
      const variant = materialVariant(index, null, name);
      const own = variant ? await loadVariantTextures(variant) : null;
      const tint = raw || [255, 255, 255];
      if (own) {
        meshMaterial.color.setRGB(tint[0] / 255, tint[1] / 255, tint[2] / 255, THREE.SRGBColorSpace);
        const tile = Number(variant.props?.StudsPerTile) || 10;
        const uv = part.geometry.attributes.uv;
        for (let i = 0; i < uv.count; i += 1) uv.setXY(i, uv.getX(i) * TERRAIN_TILE_STUDS / tile, uv.getY(i) * TERRAIN_TILE_STUDS / tile);
        applyMaps(meshMaterial, own);
        mesh.userData.rhrMaterialVariant = variant.name;
        return;
      }
      const roblox = await loadRobloxMaterial(name, part.kind);
      if (roblox) {
        // Roblox's terrain textures are pale: it multiplies them by the material's
        // base colour (the install's materials2022.json), scaled by the place's
        // MaterialColor over the default one. Without the install, the default
        // colour stands in for the base colour.
        robloxMaterialsUsed.add(name);
        const fallback = terrain.defaultColors?.[name] || tint;
        const base = terrain.baseColors?.[name] || fallback;
        const channel = k => (base[k] / 255) * Math.min(2, tint[k] / Math.max(1, fallback[k]));
        meshMaterial.color.setRGB(channel(0), channel(1), channel(2), THREE.SRGBColorSpace);
        applyMaps(meshMaterial, roblox);
        meshMaterial.onBeforeCompile = () => {};  // terrain colour maps are not tint masks
        meshMaterial.customProgramCacheKey = () => 'rhr-terrain';
        return;
      }
      const lookAlike = await loadMaterialTextures(name);
      if (!lookAlike) return;
      lookAlikeMaterialsUsed.add(name);
      meshMaterial.map = lookAlike.map;
      if (lookAlike.normalMap) meshMaterial.normalMap = lookAlike.normalMap;
      meshMaterial.needsUpdate = true;
    })());
  }
  await Promise.all(jobs);
  terrainSummary = {triangles, materials: [...materialsDrawn]};
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
  const assetId = contentAssetId(uri);
  if (!assetId) return null;
  if (sceneTextureCache.has(assetId)) return sceneTextureCache.get(assetId);

  const promise = (async () => {
    const manifest = await sceneAssetManifest;
    const url = manifest[assetId];
    if (!url) return null;
    const loader = new THREE.TextureLoader();
    const texture = await new Promise(resolve => loader.load(url, resolve, undefined, () => resolve(null)));
    if (texture) texture.colorSpace = THREE.SRGBColorSpace;
    return texture;
  })();
  sceneTextureCache.set(assetId, promise);
  return promise;
}

// A normal, roughness or metalness map: the same cached image, read as data (no sRGB).
const sceneDataTextureCache = new Map();
async function loadSceneDataTexture(uri) {
  const assetId = contentAssetId(uri);
  if (!assetId) return null;
  if (sceneDataTextureCache.has(assetId)) return sceneDataTextureCache.get(assetId);
  const promise = (async () => {
    const manifest = await sceneAssetManifest;
    const url = manifest[assetId];
    if (!url) return null;
    const texture = await new Promise(resolve => new THREE.TextureLoader().load(url, resolve, undefined, () => resolve(null)));
    if (texture) {
      texture.colorSpace = THREE.NoColorSpace;
      texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
    }
    return texture;
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

async function addSurfaceImage(node, parentNode) {
  const parentMesh = meshByNode.get(parentNode);
  if (!parentMesh) return;
  const baseTexture = await loadSceneTexture(node.props?.Texture);
  if (!baseTexture) return;
  const face = node.props?.Face?.name || 'Front';
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
      if (parent) jobs.push(addSurfaceImage(node, parent));
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

function beamRibbonGeometry(points, tangents, widths, camera, faceCamera, normal, textureMode, textureLength, colorSequence, transparencySequence) {
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
    const u = textureMode === 'Stretch' ? distances[index] / totalLength : distances[index] / Math.max(1e-6, textureLength);
    uvs.push(u, 0, u, 1);
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
    );
    const localTransparency = Math.max(0, Math.min(1, Number(node.props?.LocalTransparencyModifier ?? 0)));
    const materialOpacity = 1 - localTransparency;
    const brightness = Math.max(0, Number(node.props?.Brightness ?? 1));
    const texture = node.props?.Texture ? await loadSceneTexture(node.props.Texture) : null;
    if (texture) {
      texture.wrapS = THREE.RepeatWrapping;
      texture.wrapT = THREE.ClampToEdgeWrapping;
      texture.needsUpdate = true;
    }
    const material = effectMaterial(texture, brightness, materialOpacity, node.props?.LightEmission);
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
    const u = textureMode === 'Stretch'
      ? (1 - ages[index]) * textureLength
      : distances[index] / Math.max(1e-6, textureLength);
    uvs.push(u, 0, u, 1);
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
    const texture = node.props?.Texture ? await loadSceneTexture(node.props.Texture) : null;
    if (texture) {
      texture.wrapS = THREE.RepeatWrapping;
      texture.wrapT = THREE.ClampToEdgeWrapping;
      texture.needsUpdate = true;
    }
    const localTransparency = Math.max(0, Math.min(1, Number(node.props?.LocalTransparencyModifier ?? 0)));
    const materialOpacity = 1 - localTransparency;
    const brightness = Math.max(0, Number(node.props?.Brightness ?? 1));
    const material = effectMaterial(texture, brightness, materialOpacity, node.props?.LightEmission);
    const mesh = new THREE.Mesh(geometry, material);
    mesh.userData.rhrDecoration = true;
    mesh.userData.rhrEffect = true;
    centerForSorting(mesh);
    scene.add(mesh);
  }
}

// Particles, Beams and Trails blend by LightEmission: 0 is ordinary transparency,
// 1 adds the effect's light to what is behind it (it can only brighten), and values in
// between mix the two. Written premultiplied: colour * alpha is added, and what is
// behind is dimmed by alpha * (1 - LightEmission).
function effectMaterial(map, brightness, opacity, lightEmission) {
  const emission = Math.max(0, Math.min(1, Number(lightEmission ?? 0)));
  const material = new THREE.MeshBasicMaterial({
    map,
    color: new THREE.Color(brightness, brightness, brightness),
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
        let score = 0;
        for (const particle of particles) {
          const look = particleLook(emitter.props, particle);
          score += look.size * look.size * Math.max(0, 1 - look.transparency);
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

let softDotTexture = null;
function softDot() {
  if (softDotTexture) return softDotTexture;
  const n = 64;
  const data = new Uint8Array(n * n * 4);
  for (let y = 0; y < n; y += 1) {
    for (let x = 0; x < n; x += 1) {
      const r = Math.hypot(x + 0.5 - n / 2, y + 0.5 - n / 2) / (n / 2);
      const i = (y * n + x) * 4;
      data[i] = data[i + 1] = data[i + 2] = 255;
      data[i + 3] = Math.round(255 * Math.max(0, 1 - r) ** 1.5);
    }
  }
  softDotTexture = new THREE.DataTexture(data, n, n);
  softDotTexture.needsUpdate = true;
  return softDotTexture;
}

async function particleTexture(uri) {
  const texture = await loadSceneTexture(uri);
  if (texture) return texture;
  particleState.missingTextures.add(String(uri));
  return softDot();
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
    const material = effectMaterial(texture, brightness, 1, props.LightEmission);
    const mesh = new THREE.Mesh(geometry, material);
    mesh.userData.rhrDecoration = true;
    mesh.userData.rhrEffect = true;
    // The particles already moved by ZOffset, so the sort sees it too: it changes
    // which effect is drawn over which, as in Roblox.
    centerForSorting(mesh);
    scene.add(mesh);
    particleState.drawn += quads.length;
  }
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
async function loadSquareCube(urls) {
  const images = await Promise.all(urls.map(url => new Promise(resolve => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => resolve(null);
    image.src = url;
  })));
  if (images.some(image => !image)) return null;
  const largest = Math.max(...images.map(image => Math.max(image.naturalWidth, image.naturalHeight)));
  const size = Math.min(1024, 2 ** Math.ceil(Math.log2(Math.max(16, largest))));
  const faces = images.map(image => {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = size;
    canvas.getContext('2d').drawImage(image, 0, 0, size, size);
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
    THREE.ShaderChunk.fog_fragment = THREE.ShaderChunk.fog_fragment.replace(
      'float fogFactor = 1.0 - exp( - fogDensity * fogDensity * vFogDepth * vFogDepth );',
      `float fogFactor = 1.0 - exp( - pow( fogDensity * vFogDepth, ${curve.power.toFixed(3)} ) );`,
    );
    scene.fog = new THREE.FogExp2(fogColor, 1 / curve.length);
  }
  atmosphereState = {fogColor, haze, curve};
  // No sky image: the default gradient sky keeps the atmosphere colour at the horizon.
  atmosphereHorizon = fogColor.clone();
}

// A sky cube drawn on a dome around the camera, so the Atmosphere can veil it the
// way Roblox does (see configureAtmosphere).
function makeSkyDome(cube) {
  const haze = atmosphereState ? atmosphereState.haze : 0;
  const material = new THREE.ShaderMaterial({
    uniforms: {
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
varying vec3 vDir;
void main() {
  vec3 d = normalize(vDir);
  vec3 s = rotation * d;
  vec3 c = textureCube(sky, vec3(-s.x, s.y, s.z)).rgb * intensity;
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
  if (terrainSummary) {
    notes.push(`terrain drawn smooth (${terrainSummary.materials.join(', ')}); materials meet with a hard edge where Roblox blends them`);
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
    notes.push(`${particleState.missingTextures.size} particle texture(s) could not be loaded; those particles are drawn as soft dots`);
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
  const corrections = children.filter(c => c.className === 'ColorCorrectionEffect' && enabled(c));
  const neon = [];
  scene.traverse(object => {
    if (object.isMesh && object.userData?.rhrNode?.props?.Material?.name === 'Neon') neon.push(object);
  });
  const exposure = Number(lighting?.props?.ExposureCompensation ?? 0);
  return {
    lighting: lightingIndex,
    neon,
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

function compositeMaterial(effects) {
  const corrections = effects.corrections;
  const uniforms = {
    scene: {value: null},
    neon: {value: null},
    bloom: {value: null},
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

// Draw the frame: straight to the canvas when there is nothing to post-process.
function renderFrame(camera) {
  if (!postEffects) postEffects = readPostEffects(sceneIndex);
  const effects = postEffects;
  if (viewportMode || (!effects.modern && !effects.neon.length && !effects.bloom && !effects.corrections.length && !effects.exposure)) {
    renderer.setRenderTarget(null);
    renderer.render(scene, camera);
    return;
  }
  const size = renderer.getSize(new THREE.Vector2());
  const main = makeTarget(size.x, size.y);
  main.samples = 4;
  renderer.setRenderTarget(main);
  renderer.render(scene, camera);

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
  const composite = compositeMaterial(effects);
  composite.uniforms.scene.value = main.texture;
  composite.uniforms.neon.value = neonBlur.texture;
  composite.uniforms.bloom.value = bloomBlur.texture;
  drawFullscreen(composite, null);
  composite.dispose();
  for (const target of [main, neonRaw, neonScratch, neonBlur, bloomBlur]) target.dispose();
}

async function main() {
  const response = await fetch(params.get('ir') || '/__rhr_ir__.json');
  if (!response.ok) throw new Error(`IR request failed: ${response.status}`);
  const ir = await response.json();
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
    await addTerrain(index);
    await Promise.all(meshGeometryJobs);
    await Promise.all(materialTextureJobs);
    await stylePlaceholderMeshes();
    await addSurfaceImages(index);
    addAttachmentAnchors(index);
    if (params.get('effects') !== '0') simulateParticles(index);
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
    if (skyCube) {
      // Drawn as a dome so the Atmosphere can veil it.
      scene.background = null;
      scene.add(makeSkyDome(skyCube));
    }
    configureSceneLights(index);
    camera = new THREE.PerspectiveCamera();
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
    if (modernLighting(index)) buildSkyVisibility(camera);
    await addBeams(index, camera);
    await addTrails(index, camera);
    await addParticles(camera);
    await reportCamera(camera);
    await reportNotes();
    renderFrame(camera);
  }
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  renderFrame(camera);
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  if (!viewportMode) {
    await addBillboards(index, camera);
    await addSurfaceGuis(index, camera);
  }
  document.documentElement.dataset.rhrReady = 'true';
}

try {
  await main();
} catch (error) {
  document.documentElement.dataset.rhrError = String(error);
  throw error;
}
