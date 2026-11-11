import sqlite3

from printmanager import create_app
from printmanager.db import get_db
from test_app import job_status, make_item


def queue(auth, item, qty):
    auth.post(f"/items/{item}/queue", data={"quantity": str(qty)})


def first_job(app):
    with app.app_context():
        return dict(get_db().execute("SELECT * FROM print_jobs ORDER BY id DESC LIMIT 1").fetchone())


def progress(auth, job, count, direction="add"):
    return auth.post(f"/jobs/{job}/progress", data={"count": str(count), "direction": direction})


def test_partial_progress_keeps_job_in_queue_until_all_done(auth, app):
    item = make_item(auth)
    queue(auth, item, 5)
    job = first_job(app)["id"]
    page = auth.get("/queue").data.decode()
    assert "0 of 5 done" in page and 'name="count"' in page and "Finish all" in page

    progress(auth, job, 2)
    row = first_job(app)
    assert row["done_qty"] == 2 and row["status"] == "queued"
    assert "2 of 5 done" in auth.get("/queue").data.decode()
    assert b"Undo" in auth.get("/queue").data

    progress(auth, job, 1, "undo")
    assert first_job(app)["done_qty"] == 1
    progress(auth, job, 4)
    row = first_job(app)
    assert row["status"] == "completed" and row["done_qty"] == 5 and row["completed_at"]
    assert row["picked_up_at"] is None  # waits in "Ready for pickup"


def test_cannot_overshoot_or_use_bad_counts(auth, app):
    item = make_item(auth)
    queue(auth, item, 3)
    job = first_job(app)["id"]
    for bad in ("4", "0", "-1", "x"):
        progress(auth, job, bad)
    assert first_job(app)["done_qty"] == 0
    progress(auth, job, 9, "undo")  # undo can't go below zero
    assert first_job(app)["done_qty"] == 0
    assert auth.post("/jobs/999/progress", data={"count": "1"}).status_code == 404


def test_chips_count_finished_units_immediately(auth, app):
    item = make_item(auth)
    queue(auth, item, 5)
    progress(auth, first_job(app)["id"], 2)
    page = auth.get("/").data.decode()
    assert "2 printed" in page and "3 queued" in page


def test_finish_all_then_print_again_keeps_the_original(auth, app):
    item = make_item(auth)
    queue(auth, item, 4)
    job = first_job(app)["id"]
    progress(auth, job, 1)
    auth.post(f"/jobs/{job}/complete")
    assert first_job(app)["done_qty"] == 4
    auth.post(f"/jobs/{job}/pickup")

    page = auth.get("/history").data.decode()
    assert 'name="quantity" value="1"' in page  # not pre-filled with the old quantity
    auth.post(f"/jobs/{job}/again", data={"quantity": "2", "next": "/history"})
    with app.app_context():
        rows = [dict(r) for r in get_db().execute("SELECT * FROM print_jobs ORDER BY id")]
    assert [(r["status"], r["quantity"], r["done_qty"]) for r in rows] == [("completed", 4, 4), ("queued", 2, 0)]
    assert "4 &times;" in auth.get("/history").data.decode()   # the original is still there
    assert "2 &times;" in auth.get("/queue").data.decode()


def test_print_again_copies_part_and_color_and_validates(auth, app):
    item = make_item(auth)
    with app.app_context():
        db = get_db()
        db.execute("INSERT INTO print_jobs (item_id, quantity, status, notes, file_name, filament_name,"
                   " filament_material, filament_color, done_qty, completed_at) VALUES"
                   " (?, 5, 'completed', 'fast', 'b.stl', 'Red', 'PETG', 'ff0000', 5, '2026-01-01 00:00:00')", (item,))
        db.commit()
    job = first_job(app)["id"]
    for bad in ("0", "abc", "1000", ""):
        auth.post(f"/jobs/{job}/again", data={"quantity": bad})
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM print_jobs").fetchone()[0] == 1  # bad quantities add nothing
    auth.post(f"/jobs/{job}/again", data={})  # blank form field = default quantity of 1
    row = first_job(app)
    assert row["id"] != job and row["quantity"] == 1
    assert (row["file_name"], row["filament_name"], row["filament_color"], row["notes"]) == ("b.stl", "Red", "ff0000", "fast")
    assert auth.post("/jobs/999/again", data={}).status_code == 404


def test_single_item_jobs_unchanged(auth, app):
    item = make_item(auth)
    queue(auth, item, 1)
    page = auth.get("/queue").data.decode()
    assert 'name="count"' not in page and "Finish all" not in page and "Mark done" in page


def test_old_completed_jobs_are_counted_as_fully_done(tmp_path):
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
        INSERT INTO print_jobs (item_id, quantity, status) VALUES (1, 6, 'completed'), (1, 3, 'queued');
    """)
    con.commit(); con.close()
    app = create_app({"TESTING": True, "SECRET_KEY": "t", "DATABASE": str(db),
                      "UPLOAD_FOLDER": str(tmp_path / "u")})
    with app.app_context():
        rows = [r["done_qty"] for r in get_db().execute("SELECT done_qty FROM print_jobs ORDER BY id")]
    assert rows == [6, 0]
