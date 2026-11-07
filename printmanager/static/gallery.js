// Item page: clicking a thumbnail swaps the large photo.
(function () {
  var main = document.getElementById('gallery-main');
  var thumbs = document.getElementById('gallery-thumbs');
  if (!main || !thumbs) return;
  var link = document.getElementById('gallery-link');
  var download = document.getElementById('gallery-download');

  thumbs.addEventListener('click', function (event) {
    var btn = event.target.closest('.thumb-btn');
    if (!btn) return;
    main.src = btn.dataset.src;
    if (link) link.href = btn.dataset.src;
    if (download) download.href = btn.dataset.download;
    thumbs.querySelectorAll('.thumb-btn').forEach(function (other) {
      other.classList.toggle('active', other === btn);
    });
  });
})();
