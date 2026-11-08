import io
import zipfile

from test_app import PNG, make_item
from test_files import ASCII_STL, disk_files, file_rows, make_3mf


def make_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    buf.seek(0)
    return buf


def upload(auth, item_id, buf, name="model.zip"):
    return auth.post(
        f"/items/{item_id}/files",
        data={"files": (buf, name), "next": f"/items/{item_id}/edit"},
        content_type="multipart/form-data",
        follow_redirects=True,
    )


def test_zip_adds_models_and_all_images(auth, app):
    item = make_item(auth)
    buf = make_zip({
        "Benchy/a.stl": ASCII_STL, "Benchy/b.3mf": make_3mf(),
        "Benchy/photos/1.png": PNG, "Benchy/photos/2.png": PNG, "3.png": PNG,
        "readme.txt": b"hi", "__MACOSX/._a.stl": b"junk", ".DS_Store": b"x",
    })
    page = upload(auth, item, buf).data.decode()
    rows = file_rows(app, item)
    assert sorted(r["original_name"] for r in rows) == ["1.png", "2.png", "3.png", "a.stl", "b.3mf"]
    assert {r["kind"] for r in rows} == {"image", "model"}
    assert "skipped 1 file" in page  # only readme.txt counts as skipped
    assert not [n for n in disk_files(app) if not n.endswith((".stl", ".3mf", ".png", ".webp"))]


def test_zip_with_nothing_usable_and_bad_zip(auth, app):
    item = make_item(auth)
    page = upload(auth, item, make_zip({"a.txt": b"x"})).data.decode()
    assert "no STL, 3MF or image files" in page
    page = upload(auth, item, io.BytesIO(b"not a zip")).data.decode()
    assert "valid zip" in page
    assert file_rows(app, item) == []


def test_invalid_files_inside_zip_are_reported(auth, app):
    item = make_item(auth)
    page = upload(auth, item, make_zip({"ok.stl": ASCII_STL, "bad.png": b"nope"})).data.decode()
    assert [r["original_name"] for r in file_rows(app, item)] == ["ok.stl"]
    assert "bad.png" in page


def test_zip_path_traversal_names_are_flattened(auth, app):
    item = make_item(auth)
    upload(auth, item, make_zip({"../../evil.stl": ASCII_STL}))
    assert [r["original_name"] for r in file_rows(app, item)] == ["evil.stl"]
    assert all("/" not in r["stored_name"] for r in file_rows(app, item))


def test_zip_bomb_is_stopped(auth, app):
    app.config["ZIP_MAX_UNCOMPRESSED_MB"] = 1
    item = make_item(auth)
    big = b"solid x\n" + b"0" * (3 * 1024 * 1024)
    page = upload(auth, item, make_zip({"big.stl": big})).data.decode()
    assert "too much data" in page
    assert file_rows(app, item) == [] and disk_files(app) == []


def test_zip_on_new_item(auth, app):
    resp = auth.post(
        "/items/new",
        data={"name": "From zip", "files": (make_zip({"a.stl": ASCII_STL, "p.png": PNG}), "x.zip")},
        content_type="multipart/form-data",
    )
    item = int(resp.headers["Location"].rsplit("/", 1)[-1])
    assert len(file_rows(app, item)) == 2
