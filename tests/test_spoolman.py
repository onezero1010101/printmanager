import io
import re

from conftest import Session
from fake_spoolman import spool
from printmanager import create_app, spoolman
from printmanager.db import get_db
from test_app import make_item
from test_files import ASCII_STL


def configure(auth, url, location=""):
    mode = "only" if location else "any"
    resp = auth.post("/settings", data={
        "spoolman_url": url, "location_mode": mode, "location": location})
    assert resp.status_code == 302


def item_with_files(auth, *names):
    files = [(io.BytesIO(ASCII_STL), n) for n in names]
    resp = auth.post("/items/new", data={"name": "Multi", "files": files},
                     content_type="multipart/form-data")
    return int(resp.headers["Location"].rsplit("/", 1)[-1])


def file_id(app, item_id, name):
    with app.app_context():
        return get_db().execute(
            "SELECT id FROM item_files WHERE item_id = ? AND original_name = ?",
            (item_id, name)).fetchone()["id"]


def jobs(app):
    with app.app_context():
        return [dict(r) for r in get_db().execute("SELECT * FROM print_jobs ORDER BY id")]


# --- option building ---------------------------------------------------------

def test_options_skip_archived_empty_and_merge_duplicates():
    spools = [
        spool(1, 4, "Black", "PLA", "000000"), spool(2, 7, "Black", "PLA", "000000"),
        spool(3, 5, "Old", "PLA", "00ff00", archived=True),
        spool(4, 8, "Empty", "PLA", "0000ff", remaining=0),
    ]
    opts = spoolman.build_options(spools)
    assert [(o["id"], o["name"]) for o in opts] == [(4, "Black")]


def test_location_filter_is_case_insensitive_and_empty_means_any():
    spools = [spool(1, 1, "A", "PLA", "111111", location="Tim"),
              spool(2, 2, "B", "PLA", "222222", location="Shed")]
    assert [o["name"] for o in spoolman.build_options(spools, "tim")] == ["A"]
    assert len(spoolman.build_options(spools, "")) == 2
    assert spoolman.build_options(spools, "nowhere") == []


def test_color_cleaning_and_multicolor():
    assert spoolman.clean_hex("#FF00aa") == "ff00aa"
    assert spoolman.clean_hex("red;x") == ""
    assert spoolman.clean_colors("ff0000, bad ,00ff00") == "ff0000,00ff00"
    opts = spoolman.build_options([spool(1, 1, "R", "PLA", "", multi_color_hexes="ff0000,00ff00")])
    assert opts[0]["color"] == "ff0000,00ff00"


def test_unreachable_spoolman_reports_error_and_is_cached():
    spools, error = spoolman.fetch_spools("http://127.0.0.1:9")
    assert spools is None and error
    assert spoolman.fetch_spools("") == (None, "No Spoolman URL set.")
    assert spoolman.fetch_spools("ftp://x")[0] is None


def test_results_are_cached(spoolman_server):
    spoolman.fetch_spools(spoolman_server.url)
    spoolman.fetch_spools(spoolman_server.url)
    assert spoolman_server.hits == 1


# --- settings ----------------------------------------------------------------

def test_settings_page_save_and_reset(auth, spoolman_server, app):
    assert b"Settings" in auth.get("/settings").data
    configure(auth, spoolman_server.url, "Tim")
    page = auth.get("/settings").data
    assert spoolman_server.url.encode() in page and b"Connected" in page
    assert b'value="Shed"' in page  # location suggestions
    auth.post("/settings", data={"reset": "1"})
    assert spoolman_server.url.encode() not in auth.get("/settings").data


def test_settings_reject_bad_url_and_require_login(auth, client):
    auth.post("/settings", data={"spoolman_url": "javascript:alert(1)", "location_mode": "any"})
    assert b"javascript" not in auth.get("/settings").data
    assert Session(client.application.test_client()).get("/settings").status_code == 302


def test_saved_any_location_beats_environment_default(tmp_path, spoolman_server):
    app = create_app({"TESTING": True, "SECRET_KEY": "t",
                      "DATABASE": str(tmp_path / "e.db"), "UPLOAD_FOLDER": str(tmp_path / "u"),
                      "SPOOLMAN_URL": spoolman_server.url, "SPOOLMAN_LOCATION": "Tim"})
    from printmanager.db import add_user
    with app.app_context():
        add_user("alice", "pw-alice")
    s = Session(app.test_client()); s.login()
    with app.app_context():
        assert {o["name"] for o in spoolman.load_options()[0]} == {"Black", "Red", "Rainbow", "Weird"}
    configure(s, spoolman_server.url, "")
    with app.app_context():
        assert "Shelf" in {o["name"] for o in spoolman.load_options()[0]}


# --- queueing ----------------------------------------------------------------

def test_queue_whole_item_with_color_snapshot(auth, app, spoolman_server):
    configure(auth, spoolman_server.url, "Tim")
    item = make_item(auth)
    page = auth.get(f"/items/{item}").data
    assert b'name="filament"' in page and b"Rainbow" in page and b"Shelf" not in page
    resp = auth.post(f"/items/{item}/queue", data={"quantity": "2", "filament": "5"})
    assert resp.status_code == 302
    job = jobs(app)[0]
    assert (job["filament_name"], job["filament_material"], job["filament_color"]) == ("Red", "PETG", "ff0000")
    assert job["file_id"] is None and job["file_name"] == ""
    spoolman_server.spools.clear(); spoolman.clear_cache()
    assert b"PETG" in auth.get("/queue").data  # snapshot outlives the spool


def test_queue_single_file(auth, app, spoolman_server):
    configure(auth, spoolman_server.url)
    item = item_with_files(auth, "a.stl", "b.stl")
    fid = file_id(app, item, "b.stl")
    assert auth.get(f"/items/{item}").data.count(b'name="file_id"') == 2
    auth.post(f"/items/{item}/queue", data={"quantity": "1", "file_id": str(fid), "filament": "4"})
    job = jobs(app)[0]
    assert job["file_id"] == fid and job["file_name"] == "b.stl"
    queue = auth.get("/queue").data
    assert b"b.stl" in queue and f"/files/{fid}/download".encode() in queue


def test_file_must_be_a_model_of_this_item(auth, app):
    one, two = item_with_files(auth, "a.stl"), item_with_files(auth, "x.stl")
    other = file_id(app, two, "x.stl")
    for bad in (str(other), "abc", "999"):
        auth.post(f"/items/{one}/queue", data={"quantity": "1", "file_id": bad})
    assert jobs(app) == []


def test_unknown_or_unreachable_color_adds_nothing(auth, app, spoolman_server):
    configure(auth, spoolman_server.url, "Tim")
    item = make_item(auth)
    auth.post(f"/items/{item}/queue", data={"quantity": "1", "filament": "9"})  # other location
    auth.post(f"/items/{item}/queue", data={"quantity": "1", "filament": "x"})
    assert jobs(app) == []
    spoolman_server.fail = True; spoolman.clear_cache()
    auth.post(f"/items/{item}/queue", data={"quantity": "1", "filament": "4"})
    assert jobs(app) == []
    page = auth.get(f"/items/{item}").data
    assert b"reach Spoolman" in page
    auth.post(f"/items/{item}/queue", data={"quantity": "1"})  # no color still works
    assert len(jobs(app)) == 1


def test_without_spoolman_no_dropdown(auth):
    item = make_item(auth)
    assert b'name="filament"' not in auth.get(f"/items/{item}").data


def test_change_color_of_queued_job(auth, app, spoolman_server):
    configure(auth, spoolman_server.url)
    item = make_item(auth)
    auth.post(f"/items/{item}/queue", data={"quantity": "1"})
    jid = jobs(app)[0]["id"]
    assert b"/color" in auth.get("/queue").data
    auth.post(f"/jobs/{jid}/color", data={"filament": "5"})
    assert jobs(app)[0]["filament_name"] == "Red"
    auth.post(f"/jobs/{jid}/color", data={"filament": "999"})
    assert jobs(app)[0]["filament_name"] == "Red"
    auth.post(f"/jobs/{jid}/color", data={"filament": ""})
    assert jobs(app)[0]["filament_name"] == ""
    assert auth.post("/jobs/999/color", data={}).status_code == 404


def test_swatch_css_filter_blocks_injection(app):
    f = app.jinja_env.filters["swatch_css"]
    assert f("ff0000") == "#ff0000"
    assert f("red;background:url(x)") == ""
    assert f("ff0000,00ff00").startswith("linear-gradient(")


def test_old_database_is_migrated(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT);
        CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, description TEXT DEFAULT '',
            model_url TEXT DEFAULT '', image_filename TEXT, created_by INTEGER, created_at TEXT);
        CREATE TABLE print_jobs (id INTEGER PRIMARY KEY, item_id INTEGER, quantity INTEGER DEFAULT 1,
            status TEXT DEFAULT 'queued', notes TEXT DEFAULT '', queued_by INTEGER,
            queued_at TEXT, started_at TEXT, completed_at TEXT);
        INSERT INTO items (id, name) VALUES (1, 'Old');
        INSERT INTO print_jobs (item_id) VALUES (1);
    """)
    con.commit(); con.close()
    app = create_app({"TESTING": True, "SECRET_KEY": "t", "DATABASE": str(db),
                      "UPLOAD_FOLDER": str(tmp_path / "u")})
    with app.app_context():
        row = get_db().execute("SELECT * FROM print_jobs").fetchone()
        assert row["filament_name"] == "" and row["file_id"] is None


# --- spools page and low-stock level -------------------------------------------

def test_spools_page_lists_non_archived_with_vendor_and_low(auth, spoolman_server):
    spoolman_server.spools.append(spool(10, 20, "Nearly", "PLA", "123456", remaining=40, vendor="Acme"))
    configure(auth, spoolman_server.url, "Tim")
    page = auth.get("/spools").data.decode()
    assert "Elegoo" in page and "Acme" in page          # vendor is shown here
    assert "Old" not in page                            # archived
    assert "Shelf" not in page                          # other location
    assert "low</span>" in page and "empty</span>" in page
    assert "740 g of" in page.replace("&nbsp;", " ") or "741 g" in page or "740" in page
    for sort in ("material", "name", "remaining", "bogus"):
        assert auth.get(f"/spools?sort={sort}").status_code == 200


def test_spools_page_states(auth, spoolman_server):
    assert b"set up" in auth.get("/spools").data
    configure(auth, "http://127.0.0.1:9")
    assert b"reach Spoolman" in auth.get("/spools").data


def test_low_threshold_setting(auth, spoolman_server):
    configure(auth, spoolman_server.url)
    assert b"low</span>" not in auth.get("/spools").data
    auth.post("/settings", data={"spoolman_url": spoolman_server.url, "location_mode": "any",
                                 "low_spool_grams": "800"})
    assert b"low</span>" in auth.get("/spools").data
    resp = auth.post("/settings", data={"spoolman_url": spoolman_server.url, "low_spool_grams": "-5"})
    assert resp.status_code == 302
    assert b'value="800"' in auth.get("/settings").data


def test_length_falls_back_to_weight_calculation():
    rows = spoolman.build_spool_rows([spool(1, 1, "A", "PLA", "111111", remaining=1000,
                                           density=1.24, diameter=1.75)])
    assert 330 < rows[0]["remaining_m"] < 340   # about 335 m per kg of PLA


def test_color_dropdown_has_no_vendor(auth, spoolman_server):
    configure(auth, spoolman_server.url)
    item = make_item(auth)
    page = auth.get(f"/items/{item}").data.decode()
    assert "PLA · Black" in page and "Elegoo" not in page


def test_spools_default_to_fullest_first_and_empty_last(auth, spoolman_server):
    configure(auth, spoolman_server.url)
    page = auth.get("/spools").data.decode()
    grams = [int(g) for g in re.findall(r"(\d+) g(?: of \d+ g)? left", page)]
    assert grams == sorted(grams, reverse=True) and grams[0] == 740 and grams[-1] == 0
