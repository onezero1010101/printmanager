import io
import re
import struct
import zipfile

import pytest

from fake_spoolman import spool
from printmanager import files as files_module
from printmanager import modelsize
from printmanager.db import get_db
from printmanager.tags import parse_tags
from test_app import make_item
from test_files import by_name, file_rows
from test_spoolman import configure, item_with_files, jobs


def box_stl(x, y, z):
    """Binary STL with two triangles spanning exactly x * y * z at the origin."""
    tris = [
        (0, 0, 0, x, 0, 0, 0, y, 0),
        (0, 0, z, x, y, z, 0, 0, 0),
    ]
    data = b"\x00" * 80 + struct.pack("<I", len(tris))
    for t in tris:
        data += struct.pack("<12fH", 0, 0, 1, *t, 0)
    return data


def ascii_stl(x, y, z):
    return (
        f"solid s\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex {x} 0 0\n"
        f"vertex 0 {y} {z}\nendloop\nendfacet\nendsolid s\n"
    ).encode()


def threemf(unit="millimeter", size=(10, 20, 30), transform=None):
    x, y, z = size
    item = f' transform="{transform}"' if transform else ""
    xml = f"""<?xml version="1.0"?>
<model unit="{unit}" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
 <resources><object id="1" type="model"><mesh>
  <vertices><vertex x="0" y="0" z="0"/><vertex x="{x}" y="0" z="0"/><vertex x="0" y="{y}" z="{z}"/></vertices>
  <triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object></resources>
 <build><item objectid="1"{item}/></build></model>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("3D/3dmodel.model", xml)
    return buf.getvalue()


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


# --- measuring ---------------------------------------------------------------

def test_stl_sizes_binary_and_ascii(tmp_path):
    assert modelsize.model_size(write(tmp_path, "a.stl", box_stl(10, 20, 30)), "stl") == pytest.approx((10, 20, 30))
    assert modelsize.model_size(write(tmp_path, "b.stl", ascii_stl(5, 6, 7)), "stl") == pytest.approx((5, 6, 7))


def test_3mf_units_and_transform(tmp_path):
    assert modelsize.model_size(write(tmp_path, "a.3mf", threemf()), "3mf") == pytest.approx((10, 20, 30))
    assert modelsize.model_size(write(tmp_path, "b.3mf", threemf("centimeter")), "3mf") == pytest.approx((100, 200, 300))
    assert modelsize.model_size(write(tmp_path, "c.3mf", threemf("inch", (1, 1, 1))), "3mf") == pytest.approx((25.4, 25.4, 25.4))
    moved = threemf(transform="1 0 0 0 1 0 0 0 1 500 500 0")
    assert modelsize.model_size(write(tmp_path, "d.3mf", moved), "3mf") == pytest.approx((10, 20, 30))


def test_unreadable_files_have_no_size(tmp_path):
    assert modelsize.model_size(write(tmp_path, "x.stl", b""), "stl") is None
    assert modelsize.model_size(write(tmp_path, "y.stl", b"solid nothing\nendsolid\n"), "stl") is None
    assert modelsize.model_size(write(tmp_path, "z.3mf", b"not a zip"), "3mf") is None
    nan = b"\x00" * 80 + struct.pack("<I", 1) + struct.pack("<12fH", 0, 0, 1, *([float("nan")] * 9), 0)
    assert modelsize.model_size(write(tmp_path, "n.stl", nan), "stl") is None


# --- fit rule ----------------------------------------------------------------

def test_check_fit_cases():
    bed, margin = (220, 220, 250), 5
    assert modelsize.check_fit((200, 200, 100), bed, margin)["status"] == "fits"
    assert modelsize.check_fit((210, 100, 10), bed, margin)["status"] == "fits"      # 210 is the limit
    assert modelsize.check_fit((211, 100, 10), bed, margin)["status"] == "rotate"    # stands on its side
    r = modelsize.check_fit((300, 300, 300), bed, margin)
    assert r["status"] == "big" and r["over"] > 0
    assert modelsize.check_fit((100, 100, 10), (10, 10, 10), 6)["status"] == "big"  # margin eats the bed


def test_fit_turned_flat_and_on_side():
    bed, margin = (100, 200, 50), 0
    assert modelsize.check_fit((150, 80, 10), bed, margin)["text"] == "Fits turned flat"
    assert modelsize.check_fit((20, 10, 190), bed, margin)["text"] == "Fits on its side"


# --- stored at upload, settings, display -------------------------------------

def set_bed(auth, x="220", y="220", z="250", margin="5"):
    return auth.post("/settings", data={
        "spoolman_url": "", "location_mode": "any", "bed_x": x, "bed_y": y, "bed_z": z,
        "bed_margin": margin})


def upload_models(auth, app, *models):
    files = [(io.BytesIO(data), name) for name, data in models]
    resp = auth.post("/items/new", data={"name": "Sized", "files": files},
                     content_type="multipart/form-data")
    return int(resp.headers["Location"].rsplit("/", 1)[-1])


def test_size_is_stored_at_upload_and_shown(auth, app):
    item = upload_models(auth, app, ("big.stl", box_stl(300, 100, 20)), ("ok.stl", box_stl(50, 40, 30)))
    row = by_name(app, item, "ok.stl")
    assert (row["dim_x"], row["dim_y"], row["dim_z"], row["dims_done"]) == (50, 40, 30, 1)
    page = auth.get(f"/items/{item}").data.decode()
    assert "50 × 40 × 30 mm" in page
    assert "Fits" not in page  # no bed set yet, so no badge


def test_badges_follow_bed_setting_without_remeasuring(auth, app):
    item = upload_models(auth, app, ("big.stl", box_stl(300, 300, 20)), ("ok.stl", box_stl(50, 40, 30)),
                         ("long.stl", box_stl(230, 100, 20)))
    assert set_bed(auth).status_code == 302
    page = auth.get(f"/items/{item}").data.decode()
    assert "✓ Fits" in page and "Too big by" in page and "Fits on its side" in page
    set_bed(auth, "400", "400", "400")
    page = auth.get(f"/items/{item}").data.decode()
    assert "Too big" not in page


def test_bed_settings_validation_and_off_switch(auth):
    for bad in (dict(x="220", y="", z="250"), dict(x="-1"), dict(x="abc"), dict(margin="-3"), dict(margin="200"),
                dict(x="8", y="8", margin="5")):
        resp = set_bed(auth, **bad)
        assert resp.status_code == 302
    page = auth.get("/settings").data.decode()
    assert 'name="bed_x" value=""' in page
    set_bed(auth)
    assert 'name="bed_x" value="220"' in auth.get("/settings").data.decode()
    set_bed(auth, "", "", "")
    assert 'name="bed_x" value=""' in auth.get("/settings").data.decode()


def test_queue_row_shows_fit_for_file_or_worst_model(auth, app):
    item = upload_models(auth, app, ("big.stl", box_stl(300, 300, 20)), ("ok.stl", box_stl(50, 40, 30)))
    set_bed(auth)
    ok = by_name(app, item, "ok.stl")["id"]
    auth.post(f"/items/{item}/queue", data={"quantity": "1", "file_id": str(ok)})
    page = auth.get("/queue").data.decode()
    assert "✓ Fits" in page and "Too big" not in page
    auth.post(f"/items/{item}/queue", data={"quantity": "1"})  # whole item: worst model wins
    assert "Too big" in auth.get("/queue").data.decode()


def test_existing_files_are_measured_once_on_startup(auth, app):
    item = upload_models(auth, app, ("a.stl", box_stl(11, 12, 13)), ("junk.stl", b"solid x\nendsolid\n"))
    with app.app_context():
        db = get_db()
        db.execute("UPDATE item_files SET dim_x = NULL, dim_y = NULL, dim_z = NULL, dims_done = 0")
        db.commit()
        assert files_module.measure_missing_models() == 2
        assert files_module.measure_missing_models() == 0   # nothing is retried
    assert by_name(app, item, "a.stl")["dim_x"] == 11
    junk = by_name(app, item, "junk.stl")
    assert junk["dim_x"] is None and junk["dims_done"] == 1


def test_zip_models_are_measured(auth, app):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.stl", box_stl(7, 8, 9))
    buf.seek(0)
    item = make_item(auth)
    auth.post(f"/items/{item}/files", data={"files": (buf, "m.zip"), "next": f"/items/{item}"},
              content_type="multipart/form-data")
    assert by_name(app, item, "a.stl")["dim_z"] == 9


# --- quick queue color -------------------------------------------------------

def test_inventory_quick_queue_has_color_choice(auth, app, spoolman_server):
    item = make_item(auth)
    assert 'name="filament"' not in auth.get("/").data.decode()  # Spoolman off: no dropdown
    configure(auth, spoolman_server.url, "Tim")
    for view in ("cards", "list"):
        page = auth.get(f"/?view={view}").data.decode()
        assert 'name="filament"' in page and "PETG · Red" in page
    auth.post(f"/items/{item}/queue", data={"quantity": "1", "filament": "5", "next": "/"})
    assert jobs(app)[0]["filament_name"] == "Red"


# --- tags --------------------------------------------------------------------

def test_parse_tags():
    assert parse_tags("gift, Functional,  #gift , ,  two   words ") == (["gift", "Functional", "two words"], None)
    assert parse_tags("")[0] == []
    assert parse_tags("x" * 31)[1] and parse_tags(",".join(f"t{i}" for i in range(21)))[1]


def add_item(auth, name, tags, **extra):
    resp = auth.post("/items/new", data={"name": name, "tags": tags, **extra})
    return int(resp.headers["Location"].rsplit("/", 1)[-1])


def listed(auth, url):
    page = auth.get(url).data.decode()
    return re.findall(r'<h2><a href="/items/\d+">(\w+)</a>', page)


def test_tags_saved_shown_and_edited(auth, app):
    item = add_item(auth, "Alpha", "gift, Functional")
    page = auth.get(f"/items/{item}").data.decode()
    assert "gift" in page and "Functional" in page
    assert b'value="Functional, gift"' in auth.get(f"/items/{item}/edit").data
    auth.post(f"/items/{item}/edit", data={"name": "Alpha", "tags": "gift"})
    assert "Functional" not in auth.get(f"/items/{item}").data.decode()
    auth.post(f"/items/{item}/edit", data={"name": "Alpha", "tags": ""})
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM item_tags").fetchone()[0] == 0


def test_bad_tags_block_the_save_and_keep_input(auth, app):
    resp = auth.post("/items/new", data={"name": "Nope", "tags": "x" * 40}, follow_redirects=True)
    assert b"characters or fewer" in resp.data and b"Nope" in resp.data
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0


def test_tag_filter_requires_all_tags_and_ignores_case(auth):
    add_item(auth, "Alpha", "gift, small")
    add_item(auth, "Bravo", "gift")
    add_item(auth, "Charlie", "small, Other")
    assert listed(auth, "/?tag=gift") == ["Alpha", "Bravo"]
    assert listed(auth, "/?tag=GIFT,small") == ["Alpha"]
    assert listed(auth, "/?tag=nothing") == []
    assert listed(auth, "/?tag=small&q=charl") == ["Charlie"]
    assert listed(auth, "/?q=other") == ["Charlie"]   # search covers tags


def test_tag_sidebar_counts_and_toggle_links(auth):
    add_item(auth, "Alpha", "gift, small")
    add_item(auth, "Bravo", "gift")
    add_item(auth, "Charlie", "small, other")
    page = auth.get("/").data.decode()
    assert "Tags" in page and "tag-list" in page
    assert 'href="/?tag=gift"' in page
    page = auth.get("/?tag=gift").data.decode()
    assert "Showing items with all selected tags" in page
    assert 'class="tag active" href="/"' in page            # the active tag links back to unselected
    assert "other" not in page.split("tag-list")[1].split("</ul>")[0]  # would leave nothing


def test_deleting_item_removes_its_tags(auth, app):
    item = add_item(auth, "Alpha", "gift")
    auth.post(f"/items/{item}/delete")
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM item_tags").fetchone()[0] == 0
