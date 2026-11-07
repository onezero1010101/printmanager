// Turns <select class="color-select"> into a dropdown that shows colour swatches.
// The native select stays in the page (hidden) and holds the value, so forms and
// no-JavaScript use keep working.
(function () {
  function swatchBackground(hexes) {
    var colors = (hexes || '').split(',').filter(function (c) { return /^[0-9a-fA-F]{6}$/.test(c); });
    if (!colors.length) return '';
    if (colors.length === 1) return '#' + colors[0];
    var step = 100 / colors.length;
    return 'linear-gradient(90deg,' + colors.map(function (c, i) {
      return '#' + c + ' ' + (i * step) + '% ' + ((i + 1) * step) + '%';
    }).join(',') + ')';
  }

  function dot(hexes) {
    var s = document.createElement('span');
    s.className = 'swatch';
    var bg = swatchBackground(hexes);
    if (bg) s.style.background = bg; else s.classList.add('swatch-none');
    return s;
  }

  function enhance(select) {
    if (select.dataset.enhanced) return;
    select.dataset.enhanced = '1';

    var wrap = document.createElement('div');
    wrap.className = 'cp';
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'cp-button';
    button.setAttribute('aria-haspopup', 'listbox');
    button.setAttribute('aria-expanded', 'false');
    var list = document.createElement('ul');
    list.className = 'cp-list';
    list.setAttribute('role', 'listbox');
    list.hidden = true;

    select.classList.add('cp-native');
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');
    select.parentNode.insertBefore(wrap, select.nextSibling);
    wrap.appendChild(button);
    wrap.appendChild(list);

    function label(opt) {
      var span = document.createElement('span');
      span.textContent = opt.textContent;
      return span;
    }
    function paintButton() {
      var opt = select.options[select.selectedIndex] || select.options[0];
      button.textContent = '';
      button.appendChild(dot(opt && opt.dataset.color));
      button.appendChild(label(opt));
    }
    function close() { list.hidden = true; button.setAttribute('aria-expanded', 'false'); }
    function open() {
      document.querySelectorAll('.cp-list').forEach(function (l) { l.hidden = true; });
      list.hidden = false;
      button.setAttribute('aria-expanded', 'true');
    }

    Array.prototype.forEach.call(select.options, function (opt, i) {
      var li = document.createElement('li');
      li.setAttribute('role', 'option');
      li.tabIndex = -1;
      if (opt.disabled) li.className = 'cp-disabled';
      li.appendChild(dot(opt.dataset.color));
      li.appendChild(label(opt));
      function pick() {
        if (opt.disabled) return;
        select.selectedIndex = i;
        paintButton();
        close();
        button.focus();
        select.dispatchEvent(new Event('change', { bubbles: true }));
        if (select.hasAttribute('data-autosubmit') && select.form) select.form.submit();
      }
      li.addEventListener('click', pick);
      li.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); }
      });
      list.appendChild(li);
    });

    button.addEventListener('click', function () { list.hidden ? open() : close(); });
    button.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown' && list.hidden) { e.preventDefault(); open(); }
      if (e.key === 'ArrowDown' && !list.hidden) {
        e.preventDefault();
        var first = list.querySelector('li:not(.cp-disabled)');
        if (first) first.focus();
      }
    });
    list.addEventListener('keydown', function (e) {
      var items = Array.prototype.filter.call(list.children, function (li) { return !li.classList.contains('cp-disabled'); });
      var at = items.indexOf(document.activeElement);
      if (e.key === 'ArrowDown' && items[at + 1]) { e.preventDefault(); items[at + 1].focus(); }
      if (e.key === 'ArrowUp' && at > 0) { e.preventDefault(); items[at - 1].focus(); }
      if (e.key === 'Escape') { close(); button.focus(); }
    });
    document.addEventListener('click', function (e) { if (!wrap.contains(e.target)) close(); });
    paintButton();
  }

  function init() { document.querySelectorAll('select.color-select').forEach(enhance); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();

  // The "Add to queue" popovers close when another one opens.
  document.addEventListener('toggle', function (e) {
    if (e.target.classList && e.target.classList.contains('queue-pop') && e.target.open) {
      document.querySelectorAll('details.queue-pop[open]').forEach(function (d) { if (d !== e.target) d.open = false; });
    }
  }, true);
})();
