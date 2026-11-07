import io

from printmanager.db import get_db

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff"
    b"\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\xa0\xa0\x00\x00\x00\x00IEND\xaeB`\x82"
)


def make_item(auth, name="Benchy", **extra):
    data = {"name": name, "description": "Test boat", **extra}
    resp = auth.post("/items/new", data=data, content_type="multipart/form-data")
    assert resp.status_code == 302
    return int(resp.headers["Location"].rsplit("/", 1)[-1])


def job_status(app, job_id):
    with app.app_context():
        return get_db().execute(
            "SELECT * FROM print_jobs WHERE id = ?", (job_id,)
        ).fetchone()


# --- auth -------------------------------------------------------------------


def test_pages_require_login(client):
    for url in ("/", "/queue", "/history", "/items/new"):
        resp = client.get(url)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


def test_login_and_logout(client):
    from conftest import Session

    s = Session(client)
    bad = s.login(password="wrong")
    assert bad.status_code == 200
    assert b"Invalid username or password" in bad.data

    ok = s.login()
    assert ok.status_code == 302
    assert client.get("/").status_code == 200

    s.post("/logout")
    assert client.get("/").status_code == 302


def test_login_redirect_is_same_site_only(client):
    from conftest import Session

    resp = Session(client).post(
        "/login?next=//evil.example",
        data={"username": "alice", "password": "pw-alice"},
    )
    assert resp.headers["Location"] == "/"


def test_post_without_csrf_token_is_rejected(auth, client):
    assert client.post("/items/new", data={"name": "x"}).status_code == 400


# --- inventory --------------------------------------------------------------


def test_create_edit_and_delete_item(auth):
    item_id = make_item(auth, "Phone stand", model_url="https://example.com/m")
    page = auth.get(f"/items/{item_id}")
    assert b"Phone stand" in page.data
    assert b"https://example.com/m" in page.data

    auth.post(
        f"/items/{item_id}/edit",
        data={"name": "Tablet stand"},
        content_type="multipart/form-data",
    )
    assert b"Tablet stand" in auth.get("/").data

    auth.post(f"/items/{item_id}/delete")
    assert auth.get(f"/items/{item_id}").status_code == 404


def test_item_validation(auth):
    resp = auth.post("/items/new", data={"name": ""}, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert b"Name is required" in resp.data

    resp = auth.post(
        "/items/new",
        data={"name": "x", "model_url": "javascript:alert(1)"},
        content_type="multipart/form-data",
    )
    assert b"must start with http" in resp.data


def saved_path(app, item_id):
    with app.app_context():
        return get_db().execute(
            "SELECT path FROM items WHERE id = ?", (item_id,)
        ).fetchone()[0]


def test_local_path_is_stored_exactly_and_shown(auth, app):
    windows = r"C:\Users\me\3D Models\Benchy"
    item_id = make_item(auth, "Benchy", path=f"  {windows}  ")
    assert saved_path(app, item_id) == windows  # trimmed, otherwise untouched
    page = auth.get(f"/items/{item_id}").data.decode()
    assert windows in page
    assert "Copy" in page

    unc = r"\\nas\prints\Benchy"
    other = make_item(auth, "Clip", path=unc)
    assert saved_path(app, other) == unc

    posix = "/home/me/models/clip.stl"
    third = make_item(auth, "Hook", path=posix)
    assert saved_path(app, third) == posix


def test_local_path_can_be_edited_cleared_and_is_optional(auth, app):
    item_id = make_item(auth, "Benchy")
    assert saved_path(app, item_id) == ""
    assert b"Local files" not in auth.get(f"/items/{item_id}").data

    auth.post(
        f"/items/{item_id}/edit",
        data={"name": "Benchy", "path": r"D:\STL\Benchy"},
        content_type="multipart/form-data",
    )
    assert saved_path(app, item_id) == r"D:\STL\Benchy"
    form = auth.get(f"/items/{item_id}/edit").data.decode()
    assert r'value="D:\STL\Benchy"' in form

    auth.post(
        f"/items/{item_id}/edit",
        data={"name": "Benchy", "path": ""},
        content_type="multipart/form-data",
    )
    assert saved_path(app, item_id) == ""


def test_local_path_too_long_is_rejected(auth):
    resp = auth.post(
        "/items/new",
        data={"name": "x", "path": "a" * 501},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert b"500 characters" in resp.data


def test_existing_database_gets_path_column(tmp_path):
    import sqlite3

    from printmanager import create_app

    dbfile = tmp_path / "old.db"
    con = sqlite3.connect(dbfile)
    con.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL);
        CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            model_url TEXT NOT NULL DEFAULT '', image_filename TEXT,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT (datetime('now')));
        INSERT INTO items (name) VALUES ('Old item');
        """
    )
    con.commit()
    con.close()

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "DATABASE": str(dbfile),
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        }
    )
    with app.app_context():
        row = get_db().execute("SELECT name, path FROM items").fetchone()
    assert row["name"] == "Old item" and row["path"] == ""


def test_group_items_helper():
    from printmanager.inventory import group_items

    def item(path):
        return {"name": path, "path": path}

    groups = group_items(
        [
            item(r"C:\M\Hooks\a"),
            item(r"c:\m\hooks\b"),  # same folder, different case
            item("C:\\M\\Clips\\c/"),  # trailing slash
            item(""),
        ]
    )
    assert [h for h, _ in groups] == ["Clips", "Hooks", "No folder path"]
    assert [len(m) for _, m in groups] == [1, 2, 1]

    # UNC and Linux paths; the shared prefix is trimmed from headings
    groups = group_items(
        [
            item(r"\\nas\prints\Toys\Benchy"),
            item(r"\\nas\prints\Household\Hooks\Wall hook"),
        ]
    )
    assert [h for h, _ in groups] == ["Household / Hooks", "Toys"]
    groups = group_items([item("/home/me/models/Toys/x"), item("/home/me/models/Clips/y")])
    assert [h for h, _ in groups] == ["Clips", "Toys"]

    # a path shared by several items is a folder of its own; a file path is
    # filed under the folder containing it
    groups = group_items(
        [
            item(r"C:\M\Hooks\Wall"),
            item(r"C:\M\Hooks\Wall"),  # same folder holds two items
            item(r"C:\M\Hooks\Coat"),  # alone in its own folder
            item(r"C:\M\Toys\Benchy.stl"),
        ]
    )
    assert [h for h, _ in groups] == ["Hooks", "Hooks / Wall", "Toys"]
    assert [len(m) for _, m in groups] == [1, 2, 1]

    # one group keeps its last folder name; a bare name sits at the top level
    assert [h for h, _ in group_items([item(r"C:\Models\Hooks\a")])] == ["Hooks"]
    assert [h for h, _ in group_items([item("Benchy")])] == ["Top level"]


def test_inventory_is_grouped_by_folder(auth):
    make_item(auth, "Wall hook", path=r"C:\Models\Household\Hooks\Wall hook")
    make_item(auth, "Coat hook", path=r"C:\Models\Household\Hooks\Coat hook")
    make_item(auth, "Shelf bracket", path=r"C:\Models\Household\Brackets\Shelf bracket")
    make_item(auth, "Benchy", path=r"C:\Models\Toys\Benchy")
    make_item(auth, "Loose item")

    page = auth.get("/").data.decode()
    assert page.count('<details class="folder-group"') == 4
    headings = ["Household / Brackets", "Household / Hooks", "Toys", "No folder path"]
    positions = [page.index(f"{h} <span") for h in headings]
    assert positions == sorted(positions)
    assert 'Household / Hooks <span class="count">2</span>' in page
    assert "Show flat list" in page

    flat = auth.get("/?group=0").data.decode()
    assert "folder-group" not in flat
    assert "Group by folder" in flat
    for name in ("Wall hook", "Coat hook", "Shelf bracket", "Benchy", "Loose item"):
        assert name in flat

    searched = auth.get("/?q=hook").data.decode()
    assert "Wall hook" in searched and "Shelf bracket" not in searched


def test_items_sharing_a_folder_are_grouped_together(auth):
    shared = r"C:\Models\Household\Hooks"
    make_item(auth, "Wall hook", path=shared)
    make_item(auth, "Coat hook", path=shared)
    make_item(auth, "Shelf bracket", path=r"C:\Models\Household\Brackets\Shelf bracket")
    make_item(auth, "Benchy", path=r"C:\Models\Toys\Benchy")

    page = auth.get("/").data.decode()
    assert page.count('<details class="folder-group"') == 3
    assert 'Household / Hooks <span class="count">2</span>' in page
    assert 'Household / Brackets <span class="count">1</span>' in page


def test_no_grouping_when_items_have_no_folders(auth):
    make_item(auth, "Benchy")
    make_item(auth, "Clip")
    page = auth.get("/").data.decode()
    assert "folder-group" not in page
    assert "by folder" not in page
    assert "Benchy" in page and "Clip" in page


def test_uploads_require_login(client):
    assert client.get("/files/1/raw").status_code == 302


def test_search(auth):
    make_item(auth, "Benchy")
    make_item(auth, "Cable clip")
    page = auth.get("/?q=cable").data
    assert b"Cable clip" in page
    assert b"Benchy" not in page


# --- queue ------------------------------------------------------------------


def test_queue_lifecycle(auth, app):
    item_id = make_item(auth)
    auth.post(f"/items/{item_id}/queue", data={"quantity": "3", "notes": "blue"})

    queue = auth.get("/queue").data
    assert b"3 &times; Benchy" in queue
    assert b"blue" in queue

    job = job_status(app, 1)
    assert job["status"] == "queued" and job["quantity"] == 3

    auth.post("/jobs/1/start")
    job = job_status(app, 1)
    assert job["status"] == "printing" and job["started_at"]

    auth.post("/jobs/1/complete")
    job = job_status(app, 1)
    assert job["status"] == "completed" and job["completed_at"]

    assert b"3 &times; Benchy" in auth.get("/history").data
    assert b"3 &times; Benchy" not in auth.get("/queue").data

    auth.post("/jobs/1/requeue")
    job = job_status(app, 1)
    assert job["status"] == "queued" and job["completed_at"] is None


def test_complete_directly_from_queue(auth, app):
    item_id = make_item(auth)
    auth.post(f"/items/{item_id}/queue", data={"quantity": "1"})
    auth.post("/jobs/1/complete")
    job = job_status(app, 1)
    assert job["status"] == "completed" and job["started_at"]


def test_invalid_transition_is_refused(auth, app):
    item_id = make_item(auth)
    auth.post(f"/items/{item_id}/queue", data={"quantity": "1"})
    auth.post("/jobs/1/complete")
    auth.post("/jobs/1/start")  # completed jobs can't be started again
    assert job_status(app, 1)["status"] == "completed"


def test_bad_quantity_and_unknown_action(auth, app):
    item_id = make_item(auth)
    for qty in ("0", "-2", "abc", "1000"):
        auth.post(f"/items/{item_id}/queue", data={"quantity": qty})
    assert job_status(app, 1) is None

    auth.post(f"/items/{item_id}/queue", data={"quantity": "1"})
    assert auth.post("/jobs/1/explode").status_code == 404
    assert auth.post("/jobs/99/start").status_code == 404


def test_remove_job_and_cascade_on_item_delete(auth, app):
    item_id = make_item(auth)
    auth.post(f"/items/{item_id}/queue", data={"quantity": "1"})
    auth.post("/jobs/1/delete")
    assert job_status(app, 1) is None

    auth.post(f"/items/{item_id}/queue", data={"quantity": "2"})
    auth.post(f"/items/{item_id}/delete")
    assert job_status(app, 2) is None


def test_second_user_shares_the_queue(app):
    from conftest import Session

    alice = Session(app.test_client())
    alice.login()
    item_id = make_item(alice)
    alice.post(f"/items/{item_id}/queue", data={"quantity": "2"})

    bob = Session(app.test_client())
    bob.login("bob", "pw-bob")
    page = bob.get("/queue").data
    assert b"2 &times; Benchy" in page
    assert b"alice" in page
