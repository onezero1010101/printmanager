// Drag and drop for the add/edit item pages.
//
//   data-mode="attach"  (new item)      dropped files are kept in the form's file
//                                       input and sent when the form is saved.
//   data-mode="upload"  (existing item) dropped files are uploaded right away,
//                                       one at a time with a progress bar, and
//                                       the file list on the page is refreshed.
//
// Files can be dropped anywhere on the page. Without JavaScript the plain file
// input still works (the "Upload" button is only hidden when this script runs).
(function () {
  var zone = document.getElementById('dropzone');
  if (!zone) return;

  var mode = zone.dataset.mode;
  var input = zone.querySelector('input[type=file]');
  var list = zone.querySelector('.drop-list');
  var fallbackButton = zone.querySelector('.drop-submit');
  if (fallbackButton) fallbackButton.hidden = true;

  var ALLOWED = /\.(stl|3mf|png|jpe?g|gif|webp|zip)$/i;
  var pending = new DataTransfer(); // attach mode: files waiting for Save
  var queue = [];                   // upload mode: files waiting to upload
  var busy = false;

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }

  function note(text, className) {
    var li = document.createElement('li');
    if (className) li.className = className;
    li.textContent = text;
    list.appendChild(li);
    return li;
  }

  // ---- receiving files -----------------------------------------------------

  function hasFiles(event) {
    var types = (event.dataTransfer && event.dataTransfer.types) || [];
    return Array.prototype.indexOf.call(types, 'Files') !== -1;
  }

  function over(event) {
    if (!hasFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
    zone.classList.add('dragging');
  }

  window.addEventListener('dragenter', over);
  window.addEventListener('dragover', over);
  window.addEventListener('dragleave', function (event) {
    if (event.relatedTarget === null) zone.classList.remove('dragging');
  });
  window.addEventListener('drop', function (event) {
    if (!hasFiles(event)) return;
    event.preventDefault(); // otherwise the browser would open the file
    zone.classList.remove('dragging');
    add(event.dataTransfer.files);
  });
  input.addEventListener('change', function () { add(input.files); });

  function add(fileList) {
    var accepted = [];
    var skipped = [];
    Array.prototype.forEach.call(fileList, function (file) {
      (ALLOWED.test(file.name) ? accepted : skipped).push(file);
    });
    if (skipped.length) {
      note('Skipped (only STL, 3MF, ZIP and PNG/JPG/GIF/WebP files): ' +
           skipped.map(function (f) { return f.name; }).join(', '), 'drop-error');
    }
    if (mode === 'attach') {
      accepted.forEach(function (file) {
        var duplicate = Array.prototype.some.call(pending.files, function (p) {
          return p.name === file.name && p.size === file.size &&
                 p.lastModified === file.lastModified;
        });
        if (!duplicate) pending.items.add(file);
      });
      input.files = pending.files;
      renderPending();
    } else {
      accepted.forEach(function (file) { queue.push(file); });
      input.value = '';
      uploadNext();
    }
  }

  // ---- attach mode (new item) ---------------------------------------------

  function renderPending() {
    list.innerHTML = '';
    Array.prototype.forEach.call(pending.files, function (file, index) {
      var li = document.createElement('li');
      var label = document.createElement('span');
      label.textContent = file.name + ' (' + formatSize(file.size) + ')';
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'btn btn-small';
      remove.textContent = 'Remove';
      remove.addEventListener('click', function () { removePending(index); });
      li.appendChild(label);
      li.appendChild(remove);
      list.appendChild(li);
    });
  }

  function removePending(index) {
    var next = new DataTransfer();
    Array.prototype.forEach.call(pending.files, function (file, i) {
      if (i !== index) next.items.add(file);
    });
    pending = next;
    input.files = pending.files;
    renderPending();
  }

  if (mode === 'attach') {
    var form = zone.closest('form');
    if (form) {
      form.addEventListener('submit', function () {
        var button = form.querySelector('button[type=submit]');
        if (button && pending.files.length) {
          // Large files can take a while; show that something is happening.
          setTimeout(function () {
            button.disabled = true;
            button.textContent = 'Saving…';
          }, 0);
        }
      });
    }
  }

  // ---- upload mode (existing item) ----------------------------------------

  function uploadNext() {
    if (busy || !queue.length) return;
    busy = true;
    var file = queue.shift();

    var row = document.createElement('li');
    var label = document.createElement('span');
    label.textContent = file.name + ' (' + formatSize(file.size) + ')';
    var bar = document.createElement('progress');
    bar.max = 100;
    bar.value = 0;
    var status = document.createElement('span');
    status.className = 'muted';
    row.appendChild(label);
    row.appendChild(bar);
    row.appendChild(status);
    list.appendChild(row);

    function finish(text, failed) {
      bar.remove();
      status.textContent = text;
      if (failed) row.className = 'drop-error';
      else setTimeout(function () { row.remove(); }, 2500);
      busy = false;
      uploadNext();
    }

    var data = new FormData();
    data.append('_csrf', zone.dataset.csrf);
    data.append('files', file);

    var xhr = new XMLHttpRequest();
    xhr.open('POST', zone.dataset.url);
    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
    xhr.upload.onprogress = function (event) {
      if (event.lengthComputable) bar.value = (event.loaded / event.total) * 100;
    };
    xhr.onload = function () {
      var reply = null;
      try { reply = JSON.parse(xhr.responseText); } catch (e) { /* not JSON */ }
      if (!reply) {
        finish(xhr.status === 413 ? 'Too large for the upload limit' :
               'Upload failed (HTTP ' + xhr.status + ')', true);
        return;
      }
      document.getElementById('file-list').innerHTML = reply.html;
      if (reply.saved) {
        finish('Added', false);
      } else {
        finish((reply.errors && reply.errors[0]) || 'Not added', true);
      }
    };
    xhr.onerror = function () { finish('Upload failed (network error)', true); };
    xhr.send(data);
  }
})();
