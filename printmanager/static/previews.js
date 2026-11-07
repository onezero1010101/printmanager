// Draws static 3D pictures for inventory items that have a model but no photo.
//
// Only items whose picture is near the screen are drawn, one at a time, so a
// collapsed folder or a long list costs nothing until you scroll to it. Each
// picture is sent to the server once and then served like a photo.
const items = Array.from(document.querySelectorAll('[data-preview-model]'));
const SIZE_LIMIT = 30 * 1024 * 1024; // leave huge models to the "View in 3D" button

if (items.length) run();

async function run() {
  let lib;
  try {
    lib = await import('./modelrender.js'); // loads three.js only when there is something to draw
  } catch (err) {
    console.warn('3D previews are unavailable', err);
    return;
  }

  let renderer = null;
  let noWebGL = false;
  let busy = false;
  const waiting = [];

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          observer.unobserve(entry.target);
          waiting.push(entry.target);
        }
      }
      next();
    },
    { rootMargin: '300px' }
  );
  items.forEach((el) => observer.observe(el));

  function setLabel(el, text) {
    const placeholder = el.querySelector('.no-photo');
    if (placeholder) placeholder.textContent = text;
  }

  function showPicture(el, url) {
    const img = document.createElement('img');
    img.className = 'cover-img is-preview';
    img.alt = el.dataset.alt || '';
    img.src = url;
    const placeholder = el.querySelector('.no-photo');
    if (placeholder) placeholder.replaceWith(img);
    else el.prepend(img);
    el.removeAttribute('data-preview-model');
  }

  async function draw(el) {
    if (Number(el.dataset.size) > SIZE_LIMIT) return;
    if (!renderer) {
      try {
        renderer = lib.createPreviewRenderer();
      } catch (err) {
        noWebGL = true; // no WebGL here; the placeholders stay as they are
        return;
      }
    }
    setLabel(el, 'Drawing…');
    let model = null;
    try {
      model = await lib.loadModel(el.dataset.url, el.dataset.ext);
      const blob = await renderer.render(model);
      const url = await lib.uploadPreview(el.dataset.upload, el.dataset.previewModel, blob);
      if (url) showPicture(el, url);
      else setLabel(el, '3D model');
    } catch (err) {
      console.warn('Could not draw a preview', err);
      setLabel(el, '3D model');
    } finally {
      if (model) lib.disposeObject(model);
    }
  }

  async function next() {
    if (busy) return;
    busy = true;
    while (waiting.length && !noWebGL) {
      await draw(waiting.shift());
      await new Promise((resolve) => setTimeout(resolve, 30)); // keep the page responsive
    }
    busy = false;
    if (renderer && !waiting.length) {
      renderer.dispose();
      renderer = null;
    }
  }
}
