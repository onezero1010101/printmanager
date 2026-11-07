// Shared 3D code (three.js, bundled in static/vendor): loading STL and 3MF
// files, the lighting, and a small offscreen renderer that draws the static
// preview pictures shown on cards.
import * as THREE from 'three';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { ThreeMFLoader } from 'three/addons/loaders/3MFLoader.js';

export { THREE };

export async function loadModel(url, ext) {
  const response = await fetch(url, { credentials: 'same-origin' });
  if (!response.ok) throw new Error('HTTP ' + response.status);
  const buffer = await response.arrayBuffer();

  if (ext === 'stl') {
    const geometry = new STLLoader().parse(buffer);
    geometry.computeVertexNormals(); // many exporters leave the stored normals empty
    const material = new THREE.MeshStandardMaterial({
      color: 0x6f9fd8,
      roughness: 0.55,
      metalness: 0.1,
      side: THREE.DoubleSide,
    });
    return new THREE.Mesh(geometry, material);
  }
  if (ext === '3mf') {
    return new ThreeMFLoader().parse(buffer);
  }
  throw new Error('Unsupported type ' + ext);
}

export function addLights(scene) {
  scene.add(new THREE.HemisphereLight(0xffffff, 0x556070, 1.7));
  const key = new THREE.DirectionalLight(0xffffff, 2.2);
  key.position.set(1, -1.5, 2);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xffffff, 0.8);
  fill.position.set(-1.5, 1, 0.5);
  scene.add(fill);
}

export function disposeObject(object) {
  object.traverse((node) => {
    if (node.geometry) node.geometry.dispose();
    if (node.material) {
      (Array.isArray(node.material) ? node.material : [node.material]).forEach((m) => m.dispose());
    }
  });
}

// Draws pictures of models on a transparent background (so they sit well on
// light and dark cards). Throws if WebGL isn't available.
export function createPreviewRenderer(width = 480, height = 360) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(width, height, false);
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  addLights(scene);
  const camera = new THREE.PerspectiveCamera(35, width / height, 0.1, 10000);
  camera.up.set(0, 0, 1); // STL and 3MF files are Z-up, like a printer bed

  return {
    // `object` is added to the preview scene, so pass something that isn't
    // already on screen (for example object.clone()). Its geometry is left alone.
    async render(object) {
      scene.add(object);
      try {
        const box = new THREE.Box3().setFromObject(object);
        if (box.isEmpty()) throw new Error('Nothing to show');
        object.position.sub(box.getCenter(new THREE.Vector3()));
        const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1e-3);
        const distance = (radius / Math.sin((camera.fov * Math.PI) / 360)) * 1.05;
        camera.position.set(0.9, -1.1, 0.7).normalize().multiplyScalar(distance);
        camera.near = Math.max(distance - radius * 1.5, radius / 100);
        camera.far = distance + radius * 2;
        camera.lookAt(0, 0, 0);
        camera.updateProjectionMatrix();
        renderer.render(scene, camera);
        const blob = await new Promise((resolve) => renderer.domElement.toBlob(resolve, 'image/png'));
        if (!blob) throw new Error('Could not capture the picture');
        return blob;
      } finally {
        scene.remove(object);
      }
    },
    dispose() {
      renderer.dispose();
      renderer.forceContextLoss();
    },
  };
}

export function csrfToken() {
  const meta = document.querySelector('meta[name=csrf-token]');
  return meta ? meta.content : '';
}

// Send a rendered picture to the server. Resolves to the picture's URL, or null.
export async function uploadPreview(uploadUrl, modelId, blob) {
  const form = new FormData();
  form.append('_csrf', csrfToken());
  form.append('model_id', String(modelId));
  form.append('image', blob, 'preview.png');
  const response = await fetch(uploadUrl, {
    method: 'POST',
    body: form,
    credentials: 'same-origin',
    headers: { 'X-Requested-With': 'XMLHttpRequest' },
  });
  if (!response.ok) return null;
  const reply = await response.json();
  return reply.url || null;
}
