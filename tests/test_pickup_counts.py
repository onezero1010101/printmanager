import sqlite3

from printmanager import create_app
from printmanager.db import get_db
from test_app import make_item
from test_bed_tags import box_stl
from test_progress import first_job, progress, queue
from test_spoolman import item_with_files, file_id, jobs


def stage(app, job_id):
    with app.app_context():
        row = get_db().execute("SELECT status, picked_up_at, completed_at FROM print_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row)


def test_finish_goes_to_ready_then_pickup_to_history(auth, app):
    item = make_item(auth)
    queue(auth, item, 1)
    auth.post("/jobs/1/start")
    auth.post("/jobs/1/complete")
    row = stage(app, 1)
    assert row["status"] == "completed" and row["picked_up_at"] is None and row["completed_at"]
    queue_page = auth.get("/queue").data.decode()
    assert "Ready for pickup" in queue_page and "Picked up" in queue_page
    assert "badge-ready" in queue_page                       # nav shows a ready count
    assert "Finished" not in auth.get("/history").data.decode()
    finished = row["completed_at"]
    auth.post("/jobs/1/pickup")
    assert stage(app, 1)["picked_up_at"]
    assert stage(app, 1)["completed_at"] == finished         # history keeps the finish time
    assert "Finished" in auth.get("/history").data.decode()
    assert "Ready for pickup" not in auth.get("/queue").data.decode()


def test_shortcut_skips_ready(auth, app):
    item = make_item(auth)
    queue(auth, item, 2)
    auth.post("/jobs/1/complete_pickup")
    assert stage(app, 1)["picked_up_at"]
    assert "Ready for pickup" not in auth.get("/queue").data.decode()
    assert b"2 &times;" in auth.get("/history").data


def test_last_copy_makes_the_job_ready(auth, app):
    item = make_item(auth)
    queue(auth, item, 3)
    progress(auth, 1, 2)
    assert stage(app, 1)["status"] == "queued"
    progress(auth, 1, 1)
    row = stage(app, 1)
    assert row["status"] == "completed" and row["picked_up_at"] is None


def test_back_to_printing_from_ready(auth, app):
    item = make_item(auth)
    queue(auth, item, 3)
    auth.post("/jobs/1/complete")
    auth.post("/jobs/1/unready")
    with app.app_context():
        row = dict(get_db().execute("SELECT * FROM print_jobs").fetchone())
    assert (row["status"], row["done_qty"], row["completed_at"], row["picked_up_at"]) == ("printing", 2, None, None)


def test_invalid_moves_are_refused(auth, app):
    item = make_item(auth)
    queue(auth, item, 1)
    auth.post("/jobs/1/pickup")        # not ready yet
    auth.post("/jobs/1/unready")
    assert stage(app, 1)["status"] == "queued"
    auth.post("/jobs/1/complete_pickup")
    auth.post("/jobs/1/unready")       # already in history
    auth.post("/jobs/1/complete")
    row = stage(app, 1)
    assert row["status"] == "completed" and row["picked_up_at"]


def test_item_page_shows_ready_and_pickup(auth, app):
    item = make_item(auth)
    queue(auth, item, 1)
    auth.post("/jobs/1/complete")
    page = auth.get(f"/items/{item}").data.decode()
    assert "chip-ready" in page and "Picked up" in page


def test_old_completed_jobs_count_as_picked_up(tmp_path):
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
        INSERT INTO print_jobs (item_id, status, completed_at) VALUES
            (1, 'completed', '2026-01-02 03:04:05'), (1, 'queued', NULL);
    """)
    con.commit(); con.close()
    app = create_app({"TESTING": True, "SECRET_KEY": "t", "DATABASE": str(db), "UPLOAD_FOLDER": str(tmp_path / "u")})
    with app.app_context():
        rows = [r["picked_up_at"] for r in get_db().execute("SELECT picked_up_at FROM print_jobs ORDER BY id")]
    assert rows == ["2026-01-02 03:04:05", None]


# --- print counts ------------------------------------------------------------

def make_two_models(auth, app):
    from test_bed_tags import upload_models
    item = upload_models(auth, app, ("a.stl", box_stl(10, 10, 10)), ("b.stl", box_stl(20, 20, 20)))
    return item, file_id(app, item, "a.stl"), file_id(app, item, "b.stl")


def test_per_model_counts(auth, app):
    item, a, b = make_two_models(auth, app)
    assert auth.get(f"/items/{item}").data.decode().count("Not printed yet") == 2
    auth.post(f"/items/{item}/queue", data={"quantity": "3", "file_id": str(a)})   # job 1: a x3
    auth.post(f"/items/{item}/queue", data={"quantity": "2"})                      # job 2: whole item x2
    auth.post("/jobs/1/complete_pickup")
    progress(auth, 2, 1)                                                          # 1 of 2 whole-item copies done
    page = auth.get(f"/items/{item}").data.decode()
    assert "Printed 4&times;" in page      # a: 3 own + 1 whole-item copy
    assert "Printed 1&times;" in page      # b: only the whole-item copy
    assert "Printed 4&times; in total" in page
    assert "Not printed yet" not in page


def test_counts_include_ready_and_survive_file_removal(auth, app):
    item, a, b = make_two_models(auth, app)
    auth.post(f"/items/{item}/queue", data={"quantity": "2", "file_id": str(a)})
    auth.post("/jobs/1/complete")                       # ready, not yet picked up
    assert "Printed 2&times;" in auth.get(f"/items/{item}").data.decode()
    auth.post(f"/files/{a}/delete", data={"next": f"/items/{item}"})
    page = auth.get(f"/items/{item}").data.decode()
    assert "Printed 2&times; in total" in page          # item total still includes it
    assert page.count("Not printed yet") == 1           # b is unaffected by the orphaned job


def test_inventory_card_chip_counts_copies(auth, app):
    item = make_item(auth)
    queue(auth, item, 3)
    progress(auth, 1, 2)
    assert "2 printed" in auth.get("/").data.decode()


# --- bulk pickup ---------------------------------------------------------------

def ready_jobs(auth, item, n):
    for _ in range(n):
        queue(auth, item, 1)
    with auth.client.application.app_context():
        ids = [r["id"] for r in get_db().execute("SELECT id FROM print_jobs ORDER BY id")]
    for job in ids:
        auth.post(f"/jobs/{job}/complete")
    return ids


def test_bulk_pickup_moves_only_ticked_jobs(auth, app):
    item = make_item(auth)
    a, b, c = ready_jobs(auth, item, 3)
    page = auth.get("/queue").data.decode()
    assert page.count('name="job"') == 3 and 'id="ready-all"' in page
    auth.post("/jobs/pickup", data={"job": [str(a), str(c), "junk", str(a)], "next": "/queue"})
    assert stage(app, a)["picked_up_at"] and stage(app, c)["picked_up_at"]
    assert stage(app, b)["picked_up_at"] is None
    page = auth.get("/queue").data.decode()
    assert page.count('name="job"') == 1


def test_bulk_pickup_ignores_other_jobs_and_empty_selection(auth, app):
    item = make_item(auth)
    queue(auth, item, 1)                      # still queued, not ready
    resp = auth.post("/jobs/pickup", data={"job": ["1", "999"]}, follow_redirects=True)
    assert b"aren&#39;t waiting" in resp.data
    assert stage(app, 1)["status"] == "queued"
    resp = auth.post("/jobs/pickup", data={}, follow_redirects=True)
    assert b"Tick the jobs" in resp.data
