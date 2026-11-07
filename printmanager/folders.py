"""The inventory's folder tree, worked out from each item's local path.

Paths can be Windows (C:\\a\\b), UNC (\\\\nas\\share\\b) or Linux (/a/b). They are only
labels: nothing here touches the filesystem.
"""

import re
from collections import Counter

NO_PATH = "__nopath__"  # folder key for items that have no local path
TOP = "__top__"  # folder key for items whose path has no folder part (just a name)

_SPLIT = re.compile(r"[\\/]+")


def path_segments(path):
    return [s for s in _SPLIT.split(path or "") if s]


def _fold(segments):
    return tuple(s.casefold() for s in segments)


class Node:
    def __init__(self, name, key):
        self.name = name
        self.key = key  # full folder path joined with "/", used in URLs
        self.children = {}  # while building: casefolded name -> Node; afterwards a sorted list
        self.count = 0  # items inside (including sub-folders) that match the current filters
        self.no_model = 0
        self.no_photo = 0
        self.open = False


def folders_of(items):
    """{item id: folder as a tuple of segments} for every item that has a path.

    A path used by several items is a folder holding them all. A path used by
    just one item is that item's own folder or file, so the item is filed under
    the parent: C:\\Models\\Hooks\\Wall hook goes under C: / Models / Hooks.
    """
    parsed = {}
    for item in items:
        segments = path_segments(item["path"])
        if segments:
            parsed[item["id"]] = tuple(segments)
    shared = Counter(_fold(segments) for segments in parsed.values())
    return {
        item_id: (segments if shared[_fold(segments)] > 1 else segments[:-1])
        for item_id, segments in parsed.items()
    }


def common_depth(folders):
    """How many leading segments every folder shares (hidden from the tree).

    The last segment of the shortest folder is always kept visible.
    """
    keys = {_fold(f) for f in folders}
    if not keys:
        return 0
    limit = max(min(len(k) for k in keys) - 1, 0)
    depth = 0
    while depth < limit and len({k[depth] for k in keys}) == 1:
        depth += 1
    return depth


def in_folder(item_id, folders, selected):
    """Is the item inside the selected folder (or one of its sub-folders)?"""
    if selected == NO_PATH:
        return item_id not in folders
    if selected == TOP:
        return item_id in folders and not folders[item_id]
    wanted = _fold(path_segments(selected))
    if not wanted:
        return True
    folder = folders.get(item_id)
    return folder is not None and _fold(folder)[: len(wanted)] == wanted


def build_tree(items, folders, depth, matching_ids, selected="", open_all=False):
    """Folder tree for the sidebar: (nodes, special nodes).

    The tree's shape comes from every item, so it stays put while filtering;
    the counts only include items whose id is in matching_ids, and folders with
    nothing matching are left out. Each node knows how many of its items lack a
    3D model or a photo. Nodes on the way to the selected folder are marked open
    (all of them when open_all is set).
    """
    roots = {}
    specials = {NO_PATH: Node("No local path", NO_PATH), TOP: Node("Top level", TOP)}

    for item in sorted(items, key=lambda i: i["id"]):
        folder = folders.get(item["id"])
        if folder is None:
            chain = [specials[NO_PATH]]
        elif not folder:
            chain = [specials[TOP]]
        else:
            chain, level = [], roots
            for i in range(depth, len(folder)):
                node = level.get(folder[i].casefold())
                if node is None:
                    node = level[folder[i].casefold()] = Node(folder[i], "/".join(folder[: i + 1]))
                chain.append(node)
                level = node.children
        if item["id"] in matching_ids:
            for node in chain:
                node.count += 1
                node.no_model += 0 if item["model_count"] else 1
                node.no_photo += 0 if item["image_count"] else 1

    wanted = _fold(path_segments(selected)) if selected not in ("", NO_PATH, TOP) else ()

    def finish(level):
        nodes = sorted(
            (n for n in level.values() if n.count), key=lambda n: n.name.casefold()
        )
        for node in nodes:
            mine = _fold(path_segments(node.key))
            node.open = open_all or (bool(wanted) and wanted[: len(mine)] == mine)
            node.children = finish(node.children)
        return nodes

    return finish(roots), [specials[k] for k in (TOP, NO_PATH) if specials[k].count]
