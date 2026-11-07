import io
import os
import sqlite3
import struct
import zipfile

from conftest import Session
from printmanager import create_app
from printmanager.db import add_user, get_db
from test_app import PNG, make_item

ASCII_STL = (
    b"solid t\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\n"
    b"vertex 0 1 0\nendloop\nendfacet\nendsolid t\n"
)
XHR = {"X-Requested-With": "XMLHttpRequest"}


def binary_stl(triangles=1):
    header = b"\x00" * 80 + struct.pack("<I", triangles)
    triangle = struct.pack("<12fH", 0, 0, 1, 0, 0, 0, 10, 0, 0, 0, 10, 0, 0)
    return header + triangle * triangles


def make_3mf():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("3D/3dmodel.model", "<model/>")
    return buffer.getvalue()


def file_rows(app, item_id):
    with app.app_context():
        rows = get_db().execute(
            "SELECT * FROM item_files WHERE item_id = ? ORDER BY kind, sort_order, id",
            (item_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def disk_files(app):
    return os.listdir(app.config["UPLOAD_FOLDER"])


def by_name(app, item_id, name):
    return next(r for r in file_rows(app, item_id) if r["original_name"] == name)


# --- adding items with files ------------------------------------------------


def test_add_item_with_several_files_in_one_save(auth, app):
    item_id = make_item(
        auth,
        "Hook",
        files=[
            (io.BytesIO(binary_stl()), "hook_a.stl"),
            (io.BytesIO(make_3mf()), "hook_b.3mf"),
            (io.BytesIO(PNG), "front.png"),
            (io.BytesIO(PNG), "side.png"),
        ],
    )
    got = sorted((r["kind"], r["original_name"]) for r in file_rows(app, item_id))
    assert got == [
        ("image", "front.png"),
        ("image", "side.png"),
        ("model", "hook_a.stl"),
        ("model", "hook_b.3mf"),
    ]

    page = auth.get(f"/items/{item_id}").data.decode()
    assert "hook_a.stl" in page and "hook_b.3mf" in page
    assert "View in 3D" in page
    assert "Download all models (zip)" in page
    assert 'id="gallery-thumbs"' in page  # two photos -> thumbnail strip
    assert "viewer.js" in page


def test_invalid_files_are_rejected_but_item_is_still_saved(auth, app):
    item_id = make_item(
        auth,
        "Mixed",
        files=[
            (io.BytesIO(b"<html>not an stl</html>"), "fake.stl"),
            (io.BytesIO(b"hello"), "notes.txt"),
            (io.BytesIO(b"not a zip"), "bad.3mf"),
            (io.BytesIO(b"not a png"), "bad.png"),
            (io.BytesIO(ASCII_STL), "ok.stl"),
        ],
    )
    assert [r["original_name"] for r in file_rows(app, item_id)] == ["ok.stl"]
    assert len(disk_files(app)) == 1  # rejected uploads leave nothing behind

    page = auth.get(f"/items/{item_id}").data.decode()
    assert "valid STL file" in page
    assert "only STL, 3MF" in page


def test_invalid_form_asks_to_add_files_again(auth):
    resp = auth.post(
        "/items/new",
        data={"name": "", "files": (io.BytesIO(binary_stl()), "a.stl")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert b"Add them again" in resp.data


def test_add_and_edit_pages_have_drop_zones(auth):
    make_item(auth, "Hook")
    assert b'data-mode="attach"' in auth.get("/items/new").data
    edit = auth.get("/items/1/edit").data
    assert b'data-mode="upload"' in edit
    assert b"dropzone.js" in edit


def test_upload_limit_is_enforced(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "DATABASE": str(tmp_path / "t.db"),
            "UPLOAD_FOLDER": str(tmp_path / "up"),
            "MAX_CONTENT_LENGTH": 4000,
        }
    )
    with app.app_context():
        add_user("alice", "pw")
    s = Session(app.test_client())
    s.login("alice", "pw")
    resp = s.post(
        "/items/new",
        data={"name": "Big", "files": (io.BytesIO(binary_stl(200)), "big.stl")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 413


# --- adding files to an existing item ---------------------------------------


def test_upload_to_existing_item_adds_to_the_listing(auth, app):
    item_id = make_item(auth, files=[(io.BytesIO(binary_stl()), "first.stl")])

    resp = auth.post(
        f"/items/{item_id}/files",
        data={"files": (io.BytesIO(make_3mf()), "second.3mf")},
        content_type="multipart/form-data",
        headers=XHR,
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["saved"] == 1 and body["errors"] == []
    assert "first.stl" in body["html"] and "second.3mf" in body["html"]
    assert len(file_rows(app, item_id)) == 2

    bad = auth.post(
        f"/items/{item_id}/files",
        data={"files": (io.BytesIO(b"x"), "x.txt")},
        content_type="multipart/form-data",
        headers=XHR,
    )
    assert bad.status_code == 400
    assert bad.get_json()["saved"] == 0 and bad.get_json()["errors"]
    assert len(file_rows(app, item_id)) == 2


def test_upload_without_javascript_redirects_back_to_edit_page(auth, app):
    item_id = make_item(auth)
    resp = auth.post(
        f"/items/{item_id}/files",
        data={"files": (io.BytesIO(PNG), "a.png"), "next": f"/items/{item_id}/edit"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/items/{item_id}/edit")
    assert len(file_rows(app, item_id)) == 1


def test_edit_page_lists_files_with_controls(auth):
    item_id = make_item(
        auth,
        files=[(io.BytesIO(binary_stl()), "a.stl"), (io.BytesIO(PNG), "p.png")],
    )
    page = auth.get(f"/items/{item_id}/edit").data.decode()
    assert "a.stl" in page and "p.png" in page
    assert "Remove" in page and "Download" in page


# --- downloads --------------------------------------------------------------


def test_download_gives_original_name_and_content(auth, app):
    stl = binary_stl(2)
    item_id = make_item(auth, files=[(io.BytesIO(stl), "my model.stl")])
    file_id = file_rows(app, item_id)[0]["id"]

    download = auth.get(f"/files/{file_id}/download")
    assert download.status_code == 200
    assert download.data == stl
    assert "attachment" in download.headers["Content-Disposition"]
    assert "my model.stl" in download.headers["Content-Disposition"]

    raw = auth.get(f"/files/{file_id}/raw")
    assert raw.data == stl
    assert raw.headers["Content-Type"].startswith("application/octet-stream")
    assert raw.headers["X-Content-Type-Options"] == "nosniff"


def test_images_are_served_with_an_image_type(auth, app):
    item_id = make_item(auth, files=[(io.BytesIO(PNG), "p.png")])
    file_id = file_rows(app, item_id)[0]["id"]
    assert auth.get(f"/files/{file_id}/raw").headers["Content-Type"] == "image/png"


def test_files_require_login(client):
    for url in ("/files/1/raw", "/files/1/download", "/items/1/download-all"):
        resp = client.get(url)
        assert resp.status_code == 302 and "/login" in resp.headers["Location"]


def test_download_all_models_as_zip(auth, app):
    item_id = make_item(
        auth,
        "Wall hook!",
        files=[
            (io.BytesIO(binary_stl(1)), "part.stl"),
            (io.BytesIO(binary_stl(2)), "part.stl"),  # same name twice
            (io.BytesIO(PNG), "pic.png"),  # photos are not in the models zip
        ],
    )
    resp = auth.get(f"/items/{item_id}/download-all")
    assert resp.status_code == 200 and resp.mimetype == "application/zip"
    assert 'filename="Wall hook.zip"' in resp.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        assert sorted(zf.namelist()) == ["part (2).stl", "part.stl"]
        assert zf.read("part.stl") == binary_stl(1)

    no_models = make_item(auth, "Photos only", files=[(io.BytesIO(PNG), "p.png")])
    assert auth.get(f"/items/{no_models}/download-all").status_code == 404


# --- cover image and ordering -----------------------------------------------


def test_cover_and_ordering(auth, app):
    item_id = make_item(
        auth,
        files=[
            (io.BytesIO(PNG), "a.png"),
            (io.BytesIO(PNG), "b.png"),
            (io.BytesIO(PNG), "c.png"),
            (io.BytesIO(binary_stl()), "m.stl"),
        ],
    )

    def images():
        return [r["original_name"] for r in file_rows(app, item_id) if r["kind"] == "image"]

    assert images() == ["a.png", "b.png", "c.png"]

    auth.post(f"/files/{by_name(app, item_id, 'c.png')['id']}/cover")
    assert images() == ["c.png", "a.png", "b.png"]
    cover_id = by_name(app, item_id, "c.png")["id"]
    assert f"/files/{cover_id}/thumb".encode() in auth.get("/").data  # card shows the cover

    auth.post(f"/files/{by_name(app, item_id, 'c.png')['id']}/down")
    assert images() == ["a.png", "c.png", "b.png"]
    auth.post(f"/files/{by_name(app, item_id, 'b.png')['id']}/up")
    assert images() == ["a.png", "b.png", "c.png"]

    model_id = by_name(app, item_id, "m.stl")["id"]
    assert auth.post(f"/files/{model_id}/cover").status_code == 404
    assert auth.post(f"/files/{model_id}/explode").status_code == 404


def test_queue_and_history_show_the_cover_image(auth, app):
    item_id = make_item(auth, files=[(io.BytesIO(PNG), "p.png")])
    cover_id = file_rows(app, item_id)[0]["id"]
    auth.post(f"/items/{item_id}/queue", data={"quantity": "1"})
    assert f"/files/{cover_id}/thumb".encode() in auth.get("/queue").data


# --- deleting ---------------------------------------------------------------


def test_removing_a_file_deletes_it_from_disk(auth, app):
    item_id = make_item(auth, files=[(io.BytesIO(PNG), "a.png")])
    row = file_rows(app, item_id)[0]
    path = os.path.join(app.config["UPLOAD_FOLDER"], row["stored_name"])
    assert os.path.exists(path)

    auth.post(f"/files/{row['id']}/delete")
    assert not os.path.exists(path)
    assert file_rows(app, item_id) == []


def test_deleting_an_item_deletes_all_its_files(auth, app):
    item_id = make_item(
        auth, files=[(io.BytesIO(PNG), "a.png"), (io.BytesIO(binary_stl()), "m.stl")]
    )
    assert len(disk_files(app)) == 2
    auth.post(f"/items/{item_id}/delete")
    assert disk_files(app) == []
    assert file_rows(app, item_id) == []


# --- templates --------------------------------------------------------------


def test_confirm_dialogs_are_valid_html(auth):
    item_id = make_item(auth)
    auth.post(f"/items/{item_id}/queue", data={"quantity": "1"})
    page = auth.get("/queue").data.decode()
    # the attribute must be single-quoted around the JSON string, or it breaks
    assert """onsubmit='return confirm("Remove this job from the queue?")'""" in page


# --- upgrading an older database --------------------------------------------


def test_existing_single_photo_becomes_a_gallery_image(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "abc123.png").write_bytes(PNG)

    dbfile = tmp_path / "old.db"
    con = sqlite3.connect(dbfile)
    con.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL);
        CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            model_url TEXT NOT NULL DEFAULT '', path TEXT NOT NULL DEFAULT '',
            image_filename TEXT, created_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT (datetime('now')));
        INSERT INTO items (name, image_filename) VALUES ('Old item', 'abc123.png');
        """
    )
    con.commit()
    con.close()

    config = {
        "TESTING": True,
        "SECRET_KEY": "test",
        "DATABASE": str(dbfile),
        "UPLOAD_FOLDER": str(uploads),
    }
    for _ in range(2):  # starting again must not duplicate anything
        app = create_app(config)
        with app.app_context():
            db = get_db()
            rows = db.execute("SELECT * FROM item_files").fetchall()
            assert len(rows) == 1
            assert rows[0]["kind"] == "image"
            assert rows[0]["stored_name"] == "abc123.png"
            assert rows[0]["size"] == len(PNG)
            assert db.execute("SELECT image_filename FROM items").fetchone()[0] is None
            columns = {r["name"] for r in db.execute("PRAGMA table_info(items)")}
            assert {"path", "preview_name", "preview_file_id"} <= columns
