// Folder tree on the inventory page: remembers which folders were open, plus
// "Expand all" / "Collapse all" and the folded-up panel on small screens.
(function () {
  var tree = document.getElementById('tree');
  if (!tree) return;

  var KEY = 'printmanager.tree.open';
  var forced = tree.hasAttribute('data-force-open'); // searching/filtering shows every match
  var folders = Array.prototype.slice.call(tree.querySelectorAll('details[data-key]'));

  function read() {
    try {
      var saved = JSON.parse(localStorage.getItem(KEY) || '[]');
      return Array.isArray(saved) ? saved : [];
    } catch (e) {
      return [];
    }
  }

  function save() {
    if (forced) return; // don't overwrite what you chose with a temporary, filtered view
    try {
      localStorage.setItem(KEY, JSON.stringify(
        folders.filter(function (d) { return d.open; }).map(function (d) { return d.dataset.key; })
      ));
    } catch (e) { /* storage unavailable: the tree just starts collapsed each time */ }
  }

  if (!forced) {
    var remembered = read();
    folders.forEach(function (d) {
      if (remembered.indexOf(d.dataset.key) !== -1) d.open = true;
    });
  }

  // "toggle" doesn't bubble, so listen while it travels down.
  tree.addEventListener('toggle', save, true);

  function setAll(open) {
    folders.forEach(function (d) { d.open = open; });
    save();
  }
  var expand = document.getElementById('tree-expand');
  var collapse = document.getElementById('tree-collapse');
  if (expand) expand.addEventListener('click', function () { setAll(true); });
  if (collapse) collapse.addEventListener('click', function () { setAll(false); });

  // On narrow screens the whole tree folds up under a "Folders" heading.
  var panel = document.getElementById('tree-panel');
  if (panel && window.matchMedia) {
    var narrow = window.matchMedia('(max-width: 860px)');
    var apply = function () { panel.open = !narrow.matches; };
    apply();
    if (narrow.addEventListener) narrow.addEventListener('change', apply);
  }
})();
