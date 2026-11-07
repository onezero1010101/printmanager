// 3D viewer for STL and 3MF files on the item page (three.js, bundled in static/vendor).
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import {
  THREE,
  loadModel,
  addLights,
  createPreviewRenderer,
  uploadPreview,
} from './modelrender.js';

const container = document.getElementById('viewer');
const nameEl = document.getElementById('viewer-name');
const dimsEl = document.getElementById('viewer-dims');
const msgEl = document.getElementById('viewer-msg');
const buttons = Array.from(document.querySelectorAll('[data-view]'));

const HELP = 'Drag to rotate, scroll or pinch to zoom, right-drag to pan.';
const AUTO_LOAD_LIMIT = 30 * 1024 * 1024; // don't auto-open huge files on page load

if (container && buttons.length) start();

function start() {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  } catch (err) {
    container.hidden = true;
    msgEl.textContent = "This browser can't show 3D previews. You can still download the files.";
    return;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  container.appendChild(renderer.domElement);

  const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 10000);
  camera.up.set(0, 0, 1); // STL and 3MF files are Z-up, like a printer bed
  addLights(scene);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.addEventListener('change', render);

  let current = null;
  let grid = null;
  let loadId = 0;

  function render() {
    renderer.render(scene, camera);
  }

  function resize() {
    const w = container.clientWidth;
    const h = container.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    render();
  }
  new ResizeObserver(resize).observe(container);
  resize();

  function clearModel() {
    for (const obj of [current, grid]) {
      if (!obj) continue;
      scene.remove(obj);
      obj.traverse((node) => {
        if (node.geometry) node.geometry.dispose();
        if (node.material) {
          (Array.isArray(node.material) ? node.material : [node.material]).forEach((m) => m.dispose());
        }
      });
    }
    current = null;
    grid = null;
  }

  function place(object) {
    clearModel();
    const box = new THREE.Box3().setFromObject(object);
    if (box.isEmpty()) throw new Error('Nothing to show');
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());

    // Centre on the plate and sit the model on it.
    object.position.add(new THREE.Vector3(-center.x, -center.y, -box.min.z));
    scene.add(object);
    current = object;

    const maxDim = Math.max(size.x, size.y, size.z, 1e-3);
    const plate = Math.max(Math.ceil((Math.max(size.x, size.y) * 1.6) / 10) * 10, 50);
    grid = new THREE.GridHelper(
      plate, plate / 10,
      dark ? 0x56606e : 0x8f9aab,
      dark ? 0x333a44 : 0xd2d8e0
    );
    grid.rotation.x = Math.PI / 2; // GridHelper is Y-up; lay it on the XY plane
    grid.position.z = -maxDim * 0.0005;
    scene.add(grid);

    const dist = maxDim * 2.2;
    controls.target.set(0, 0, size.z / 2);
    controls.minDistance = maxDim * 0.2;
    controls.maxDistance = maxDim * 20;
    camera.position.set(dist * 0.9, -dist * 1.1, size.z / 2 + dist * 0.7);
    camera.near = Math.max(maxDim / 1000, 0.001);
    camera.far = maxDim * 100;
    camera.updateProjectionMatrix();
    controls.update();
    render();

    const fmt = (v) => Number(v.toFixed(1));
    dimsEl.textContent = fmt(size.x) + ' × ' + fmt(size.y) + ' × ' + fmt(size.z) + ' mm';
  }

  // Items without a photo get a static picture of their first model for the
  // inventory cards. The model is already on screen, so draw it from here.
  async function savePreview(button) {
    const uploadUrl = container.dataset.previewUrl;
    if (!uploadUrl || button.dataset.id !== container.dataset.previewModel || !current) return;
    delete container.dataset.previewUrl; // only once
    let picture = null;
    try {
      picture = createPreviewRenderer();
      const blob = await picture.render(current.clone());
      const url = await uploadPreview(uploadUrl, button.dataset.id, blob);
      if (url) {
        const placeholder = document.querySelector('.detail-photo .no-photo');
        if (placeholder) {
          const img = document.createElement('img');
          img.id = 'detail-preview';
          img.className = 'is-preview';
          img.alt = '3D preview';
          img.src = url;
          placeholder.replaceWith(img);
        }
      }
    } catch (err) {
      console.warn('Could not save a 3D preview picture', err);
    } finally {
      if (picture) picture.dispose();
    }
  }

  async function show(button) {
    const id = ++loadId;
    buttons.forEach((b) => b.setAttribute('aria-pressed', String(b === button)));
    nameEl.textContent = button.dataset.name;
    dimsEl.textContent = '';
    msgEl.textContent = 'Loading…';
    try {
      const object = await loadModel(button.dataset.url, button.dataset.ext);
      if (id !== loadId) return; // another file was chosen meanwhile
      place(object);
      msgEl.textContent = HELP;
      savePreview(button);
    } catch (err) {
      if (id !== loadId) return;
      console.error(err);
      clearModel();
      render();
      msgEl.textContent =
        "Couldn't display this file. It may be damaged or too large for this device. You can still download it.";
    }
  }

  buttons.forEach((button) => {
    button.addEventListener('click', () => {
      show(button);
      container.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });
  });

  const first = buttons[0];
  if (Number(first.dataset.size) <= AUTO_LOAD_LIMIT) {
    show(first);
  } else {
    msgEl.textContent = 'This file is large. Choose "View in 3D" to open it.';
  }
}
