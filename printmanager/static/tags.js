// Item form: click a tag used before to add it to the Tags box.
(function () {
  document.querySelectorAll('[data-tag-suggest]').forEach(function (box) {
    var input = document.getElementById(box.getAttribute('data-tag-suggest'));
    if (!input) return;
    box.hidden = false;

    function current() {
      return input.value.split(',').map(function (t) { return t.trim(); }).filter(Boolean);
    }
    function refresh() {
      var have = current().map(function (t) { return t.toLowerCase(); });
      box.querySelectorAll('[data-tag]').forEach(function (b) {
        var on = have.indexOf(b.getAttribute('data-tag').toLowerCase()) !== -1;
        b.classList.toggle('active', on);
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
    }
    box.addEventListener('click', function (e) {
      var b = e.target.closest('[data-tag]');
      if (!b) return;
      var tag = b.getAttribute('data-tag');
      var tags = current();
      var at = tags.map(function (t) { return t.toLowerCase(); }).indexOf(tag.toLowerCase());
      if (at === -1) tags.push(tag); else tags.splice(at, 1);
      input.value = tags.join(', ');
      refresh();
      input.focus();
    });
    input.addEventListener('input', refresh);
    refresh();
  });
})();
