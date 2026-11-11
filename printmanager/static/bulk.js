// Queue page: "Select all" for the ready-for-pickup checkboxes.
(function () {
  var all = document.getElementById('ready-all');
  var button = document.getElementById('ready-pickup');
  var count = document.getElementById('ready-count');
  if (!all || !button) return;
  all.parentNode.hidden = false; // without JavaScript the box stays hidden; the others still work

  var boxes = Array.prototype.slice.call(document.querySelectorAll('input.job-check'));

  function refresh() {
    var on = boxes.filter(function (b) { return b.checked; }).length;
    all.checked = on > 0 && on === boxes.length;
    all.indeterminate = on > 0 && on < boxes.length;
    button.disabled = on === 0;
    count.textContent = on ? '(' + on + ')' : '';
  }

  all.addEventListener('change', function () {
    boxes.forEach(function (b) { b.checked = all.checked; });
    refresh();
  });
  boxes.forEach(function (b) { b.addEventListener('change', refresh); });
  refresh();
})();
