from printmanager.folders import (
    NO_PATH,
    TOP,
    build_tree,
    common_depth,
    folders_of,
    in_folder,
    path_segments,
)


def item(item_id, path, models=1, images=1):
    return {"id": item_id, "path": path, "model_count": models, "image_count": images}


def tree_for(items, matching=None, selected="", open_all=False):
    folders = folders_of(items)
    depth = common_depth(folders.values())
    ids = {i["id"] for i in items} if matching is None else matching
    return build_tree(items, folders, depth, ids, selected, open_all), folders, depth


def names(nodes):
    return [n.name for n in nodes]


def test_path_segments_handles_every_path_style():
    assert path_segments(r"C:\Models\Hooks\a") == ["C:", "Models", "Hooks", "a"]
    assert path_segments(r"\\nas\prints\Toys") == ["nas", "prints", "Toys"]
    assert path_segments("/home/me//models/") == ["home", "me", "models"]
    assert path_segments("C:/Models\\Mixed/slashes") == ["C:", "Models", "Mixed", "slashes"]
    assert path_segments("") == [] and path_segments(None) == []


def test_item_alone_at_a_path_is_filed_under_its_parent_folder():
    folders = folders_of([item(1, r"C:\M\Hooks\Wall hook"), item(2, "")])
    assert folders == {1: ("C:", "M", "Hooks")}  # item 2 has no path, so no folder


def test_items_sharing_a_path_share_that_folder():
    folders = folders_of(
        [item(1, r"C:\M\Hooks"), item(2, r"c:\m\hooks"), item(3, r"C:\M\Toys\Benchy")]
    )
    assert folders[1] == ("C:", "M", "Hooks")
    assert folders[2] == ("c:", "m", "hooks")  # same folder, typed differently
    assert folders[3] == ("C:", "M", "Toys")  # alone, so filed under its parent


def test_common_prefix_is_hidden_but_a_last_segment_is_kept():
    deep = [("C:", "M", "Household", "Hooks"), ("C:", "M", "Toys")]
    assert common_depth(deep) == 2  # "C: / M" is shared; Toys has only one segment left
    assert common_depth([("C:", "M", "Hooks")]) == 2
    assert common_depth([]) == 0
    assert common_depth([("a",), ("b",)]) == 0
    assert common_depth([(), ("a", "b")]) == 0  # an item with no folder part: nothing is shared


def test_tree_shape_counts_and_special_nodes():
    items = [
        item(1, r"C:\M\Household\Hooks\Wall hook"),
        item(2, r"C:\M\Household\Hooks\Coat hook"),
        item(3, r"C:\M\Household\Brackets\Shelf", models=0),
        item(4, r"C:\M\Toys\Benchy", images=0),
        item(5, ""),
        item(6, "Loose name"),
    ]
    (roots, specials), folders, depth = tree_for(items)
    assert depth == 0  # the bare name "Loose name" shares nothing with the rest
    # the whole C: / M chain is visible because of that item
    c_drive = roots[0]
    assert c_drive.name == "C:" and c_drive.count == 4
    models = c_drive.children[0]
    assert models.name == "M"
    assert names(models.children) == ["Household", "Toys"]
    household = models.children[0]
    assert names(household.children) == ["Brackets", "Hooks"]
    assert household.count == 3 and household.no_model == 1
    assert models.children[1].no_photo == 1
    assert names(specials) == ["Top level", "No local path"]
    assert [n.count for n in specials] == [1, 1]
    assert household.children[1].key == "C:/M/Household/Hooks"


def test_prefix_is_trimmed_when_every_item_shares_it():
    items = [
        item(1, r"C:\M\Household\Hooks\Wall hook"),
        item(2, r"C:\M\Household\Brackets\Shelf"),
        item(3, r"C:\M\Toys\Benchy"),
    ]
    (roots, specials), _folders, depth = tree_for(items)
    assert depth == 2
    assert names(roots) == ["Household", "Toys"]
    assert roots[0].key == "C:/M/Household"  # keys keep the whole path, so URLs stay stable
    assert specials == []


def test_counts_follow_the_filters_and_empty_folders_disappear():
    items = [
        item(1, r"C:\M\Household\Hooks\Wall hook"),
        item(2, r"C:\M\Household\Brackets\Shelf", models=0),
        item(3, r"C:\M\Toys\Benchy"),
    ]
    (roots, _), _f, _d = tree_for(items, matching={2})
    assert names(roots) == ["Household"]
    assert names(roots[0].children) == ["Brackets"]
    assert roots[0].count == 1


def test_open_state_follows_the_selected_folder():
    items = [
        item(1, r"C:\M\Household\Hooks\Wall hook"),
        item(2, r"C:\M\Household\Brackets\Shelf"),
        item(3, r"C:\M\Toys\Benchy"),
    ]
    (roots, _), _f, _d = tree_for(items, selected="C:/M/Household/Hooks")
    household, toys = roots
    assert household.open and not toys.open
    assert household.children[1].open  # Hooks itself
    assert not household.children[0].open  # Brackets, a sibling

    (roots, _), _f, _d = tree_for(items, open_all=True)
    assert all(n.open for n in roots)


def test_in_folder_matches_whole_segments_and_ignores_case():
    items = [
        item(1, r"C:\M\Household\Hooks\Wall hook"),
        item(2, r"C:\M\Household2\Decoy\x"),
        item(3, ""),
        item(4, "Loose name"),
    ]
    folders = folders_of(items)

    def inside(item_id, selected):
        return in_folder(item_id, folders, selected)

    assert inside(1, "c:/m/household")
    assert inside(1, "C:/M/Household/Hooks")
    assert not inside(2, "C:/M/Household")  # Household2 is a different folder
    assert inside(1, "")  # no folder selected means everything
    assert inside(3, NO_PATH) and not inside(1, NO_PATH)
    assert inside(4, TOP) and not inside(1, TOP)
    assert not inside(3, "C:/M")
