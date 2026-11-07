import io
import re

from PIL import Image

from conftest import Session
from test_app import make_item
from test_files import binary_stl

HOOKS = r"C:\Models\Household\Hooks"


def png(size=(1200, 900), color=(200, 60, 60)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def stl_file(name="m.stl"):
    return (io.BytesIO(binary_stl()), name)


def photo(name="p.png"):
    return (io.BytesIO(png((40, 30))), name)


def populate(auth):
    """Five items across folders. Which ones lack a model, a photo or a path:

    Wall hook      path, model, photo
    Coat hook      path, model, no photo
    Shelf bracket  path, no model, photo
    Benchy         path, model, photo
    Loose item     no path, no model, no photo
    """
    make_item(auth, "Wall hook", path=HOOKS + r"\Wall hook", files=[stl_file(), photo()])
    make_item(auth, "Coat hook", path=HOOKS + r"\Coat hook", files=[stl_file()])
    make_item(auth, "Shelf bracket", path=r"C:\Models\Household\Brackets\Shelf", files=[photo()])
    make_item(auth, "Benchy", path=r"C:\Models\Toys\Benchy", files=[stl_file(), photo()])
    make_item(auth, "Loose item")


def page(auth, url="/"):
    return auth.get(url).data.decode()


def card_names(html):
    return re.findall(r'<h2><a href="/items/\d+">([^<]+)</a></h2>', html)


def row_names(html):
    return re.findall(r'class="row-title" href="/items/\d+">([^<]+)</a>', html)


# --- folder tree ------------------------------------------------------------


def test_tree_lists_folders_with_counts_and_special_nodes(auth):
    populate(auth)
    html = page(auth)
    assert 'data-key="C:/Models/Household"' in html
    assert 'data-key="C:/Models/Household/Hooks"' not in html or "Hooks" in html
    assert ">Household</a>" in html and ">Toys</a>" in html
    assert ">No local path</a>" in html
    assert "All items" in html
    assert sorted(card_names(html)) == [
        "Benchy", "Coat hook", "Loose item", "Shelf bracket", "Wall hook"
    ]


def test_selecting_a_folder_shows_only_its_items_including_subfolders(auth):
    populate(auth)
    make_item(auth, "Decoy", path=r"C:\Models\Household2\Decoy\x", files=[photo()])

    household = card_names(page(auth, "/?folder=C:/Models/Household"))
    assert sorted(household) == ["Coat hook", "Shelf bracket", "Wall hook"]  # not Decoy, not Toys

    hooks = card_names(page(auth, "/?folder=c:/models/household/hooks"))  # any capitalisation
    assert sorted(hooks) == ["Coat hook", "Wall hook"]

    assert card_names(page(auth, "/?folder=__nopath__")) == ["Loose item"]
    html = page(auth, "/?folder=C:/Models/Nowhere")
    assert "Nothing here" in html and "Show all items" in html


def test_current_folder_is_highlighted_with_breadcrumbs_and_open_ancestors(auth):
    populate(auth)
    html = page(auth, "/?folder=C:/Models/Household/Hooks")
    assert '<h2 class="inv-title">Hooks</h2>' in html
    assert 'class="tree-link current"' in html
    assert re.search(r'<details data-key="C:/Models/Household" open>', html)
    assert not re.search(r'<details data-key="C:/Models/Toys"[^>]* open>', html)


def test_missing_model_counts_show_up_in_the_tree(auth):
    populate(auth)
    html = page(auth)
    assert 'title="1 without a 3D model"' in html  # Household/Brackets has Shelf bracket


# --- filters ----------------------------------------------------------------


def test_filter_chips_show_how_many_items_are_missing_each_thing(auth):
    populate(auth)
    html = page(auth)
    assert re.search(r"No local path <span>1</span>", html)
    assert re.search(r"No 3D model <span>2</span>", html)  # Shelf bracket, Loose item
    assert re.search(r"No photo <span>2</span>", html)  # Coat hook, Loose item


def test_each_filter_lists_the_right_items(auth):
    populate(auth)
    assert card_names(page(auth, "/?missing=path")) == ["Loose item"]
    assert sorted(card_names(page(auth, "/?missing=model"))) == ["Loose item", "Shelf bracket"]
    assert sorted(card_names(page(auth, "/?missing=photo"))) == ["Coat hook", "Loose item"]


def test_filters_combine_and_work_with_folders_and_search(auth):
    populate(auth)
    assert card_names(page(auth, "/?missing=model,photo")) == ["Loose item"]
    assert card_names(page(auth, "/?missing=photo&folder=C:/Models/Household")) == ["Coat hook"]
    assert card_names(page(auth, "/?missing=photo&q=coat")) == ["Coat hook"]
    assert card_names(page(auth, "/?missing=photo&q=zzz")) == []
    assert card_names(page(auth, "/?missing=bogus")) != []  # unknown filters are ignored


def test_filters_prune_the_tree_and_open_everything(auth):
    populate(auth)
    html = page(auth, "/?missing=model")
    assert ">Brackets</a>" in html  # Shelf bracket lives there
    assert ">Toys</a>" not in html  # nothing in Toys lacks a model
    assert "data-force-open" in html
    assert re.search(r'<details data-key="C:/Models/Household" open>', html)
    assert 'aria-pressed="true"' in html


def test_search_matches_the_local_path_too(auth):
    populate(auth)
    assert card_names(page(auth, "/?q=toys")) == ["Benchy"]  # only in Benchy's path
    assert sorted(card_names(page(auth, "/?q=hook"))) == ["Coat hook", "Wall hook"]


def test_items_show_what_they_are_missing(auth):
    populate(auth)
    html = page(auth, "/?folder=__nopath__")
    for label in ("No path", "No model", "No photo"):
        assert f'<span class="chip chip-gap">{label}</span>' in html
    complete = page(auth, "/?q=benchy")
    assert "chip-gap" not in complete


# --- views ------------------------------------------------------------------


def test_list_view_and_it_is_remembered(auth):
    populate(auth)
    assert "inv-rows" not in page(auth)  # cards by default
    html = page(auth, "/?view=list")
    assert 'class="inv-rows"' in html and 'class="grid"' not in html
    assert sorted(row_names(html)) == [
        "Benchy", "Coat hook", "Loose item", "Shelf bracket", "Wall hook"
    ]
    assert "inv-rows" in page(auth, "/")  # the choice sticks, with no query string
    assert 'class="grid"' in page(auth, "/?view=cards")
    assert 'class="grid"' in page(auth, "/")


def test_every_link_keeps_the_current_filters(auth):
    populate(auth)
    html = page(auth, "/?folder=C:/Models/Household&missing=photo&q=hook")
    assert 'name="folder" value="C:/Models/Household"' in html  # search form keeps the folder
    assert 'name="missing" value="photo"' in html
    assert re.search(r'href="/\?[^"]*missing=photo[^"]*view=list', html) or "view=list" in html


def test_empty_inventory_shows_the_welcome_panel(auth):
    html = page(auth)
    assert "No items yet" in html
    assert "filter-bar" not in html


def test_queue_form_returns_to_the_same_view(auth):
    populate(auth)
    html = page(auth, "/?folder=C:/Models/Toys&view=list")
    assert 'name="next" value="/?folder=C:/Models/Toys&amp;view=list"' in html


# --- pictures on cards ------------------------------------------------------


def test_cards_use_small_thumbnails_not_the_original_photo(auth):
    make_item(auth, "Boat", files=[(io.BytesIO(png()), "boat.png")])
    html = page(auth)
    assert re.search(r'<img class="cover-img" src="/files/\d+/thumb"', html)
    assert "/raw" not in html


def test_cards_with_a_model_but_no_photo_ask_the_browser_for_a_preview(auth):
    make_item(auth, "Hook", files=[stl_file("hook.stl")])
    html = page(auth)
    assert "data-preview-model=" in html
    assert 'data-ext="stl"' in html
    assert "/items/1/preview" in html  # the upload address
    assert "previews.js" in html
    assert ">3D model<" in html  # placeholder while waiting


def test_no_preview_is_requested_when_there_is_a_photo_or_no_model(auth):
    make_item(auth, "Has photo", files=[stl_file(), photo()])
    make_item(auth, "Nothing")
    html = page(auth)
    assert "data-preview-model=" not in html
    assert "previews.js" not in html
