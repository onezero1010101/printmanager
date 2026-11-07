import io
import os

from PIL import Image, ImageOps

from printmanager.db import get_db
from test_app import make_item
from test_files import binary_stl, file_rows, disk_files, make_3mf


def png(size=(1200, 900), color=(200, 60, 60)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def preview_png(size=(480, 360)):
    buffer = io.BytesIO()
    Image.new("RGBA", size, (0, 0, 0, 0)).save(buffer, "PNG")
    return buffer.getvalue()


def stl_file(name="m.stl"):
    return (io.BytesIO(binary_stl()), name)


def item_row(app, item_id):
    with app.app_context():
        return dict(get_db().execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone())


def post_preview(auth, item_id, model_id, data=None, name="p.png"):
    return auth.post(
        f"/items/{item_id}/preview",
        data={"model_id": str(model_id), "image": (io.BytesIO(data or preview_png()), name)},
        content_type="multipart/form-data",
    )


# --- thumbnails -------------------------------------------------------------


def test_thumbnail_is_made_on_upload_and_is_small(auth, app):
    original = png((1600, 1200))
    item_id = make_item(auth, files=[(io.BytesIO(original), "big.png")])
    row = file_rows(app, item_id)[0]
    assert any(name.endswith(".thumb.webp") for name in disk_files(app))

    resp = auth.get(f"/files/{row['id']}/thumb")
    assert resp.status_code == 200 and resp.mimetype == "image/webp"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    with Image.open(io.BytesIO(resp.data)) as thumb:
        assert thumb.format == "WEBP"
        assert max(thumb.size) <= 480
        assert thumb.size == (480, 360)  # same proportions as the original
    assert len(resp.data) < len(original)


def test_thumbnail_is_made_later_for_photos_that_have_none(auth, app):
    item_id = make_item(auth, files=[(io.BytesIO(png()), "old.png")])
    row = file_rows(app, item_id)[0]
    for name in disk_files(app):
        if name.endswith(".thumb.webp"):
            os.remove(os.path.join(app.config["UPLOAD_FOLDER"], name))  # like a photo from before thumbnails

    assert auth.get(f"/files/{row['id']}/thumb").status_code == 200
    assert any(name.endswith(".thumb.webp") for name in disk_files(app))


def test_thumbnail_respects_photo_rotation_metadata(auth, app):
    image = Image.new("RGB", (200, 100), (10, 120, 10))
    exif = Image.Exif()
    exif[0x0112] = 6  # "rotate 90 degrees": a phone photo taken in portrait
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif)
    item_id = make_item(auth, files=[(io.BytesIO(buffer.getvalue()), "portrait.jpg")])
    resp = auth.get(f"/files/{file_rows(app, item_id)[0]['id']}/thumb")
    with Image.open(io.BytesIO(resp.data)) as thumb:
        assert thumb.size == (100, 200)


def test_undecodable_image_falls_back_to_the_original(auth, app):
    junk = b"\x89PNG\r\n\x1a\n" + b"not really an image" * 5
    item_id = make_item(auth, files=[(io.BytesIO(junk), "odd.png")])
    row = file_rows(app, item_id)[0]
    resp = auth.get(f"/files/{row['id']}/thumb")
    assert resp.status_code == 200 and resp.mimetype == "image/png"
    assert resp.data == junk
    assert not any(name.endswith(".thumb.webp") for name in disk_files(app))


def test_thumbnails_are_only_for_photos_and_need_login(auth, app, client):
    item_id = make_item(auth, files=[stl_file()])
    model_id = file_rows(app, item_id)[0]["id"]
    assert auth.get(f"/files/{model_id}/thumb").status_code == 404
    assert auth.get("/files/999/thumb").status_code == 404
    anonymous = app.test_client()
    assert anonymous.get("/files/1/thumb").status_code == 302


def test_removing_a_photo_removes_its_thumbnail(auth, app):
    item_id = make_item(auth, files=[(io.BytesIO(png()), "a.png")])
    assert len(disk_files(app)) == 2  # photo and thumbnail
    auth.post(f"/files/{file_rows(app, item_id)[0]['id']}/delete")
    assert disk_files(app) == []


# --- 3D preview pictures ----------------------------------------------------


def test_preview_lifecycle(auth, app):
    item_id = make_item(auth, "Hook", files=[stl_file("hook.stl")])
    model_id = file_rows(app, item_id)[0]["id"]
    assert auth.get(f"/items/{item_id}/preview").status_code == 404  # nothing yet
    assert b"data-preview-model" in auth.get("/").data

    resp = post_preview(auth, item_id, model_id)
    assert resp.status_code == 200
    assert resp.get_json()["url"] == f"/items/{item_id}/preview?v={model_id}"

    row = item_row(app, item_id)
    assert row["preview_file_id"] == model_id and row["preview_name"].startswith("preview-")
    shown = auth.get(f"/items/{item_id}/preview")
    assert shown.status_code == 200 and shown.mimetype == "image/png"
    assert shown.headers["X-Content-Type-Options"] == "nosniff"
    assert shown.data == preview_png()

    inventory = auth.get("/").data.decode()
    assert f"/items/{item_id}/preview?v={model_id}" in inventory
    assert "data-preview-model" not in inventory  # nothing left to draw
    assert "is-preview" in inventory

    detail = auth.get(f"/items/{item_id}").data.decode()
    assert 'id="detail-preview"' in detail and "data-preview-url" not in detail


def test_replacing_a_preview_deletes_the_old_picture(auth, app):
    item_id = make_item(auth, files=[stl_file()])
    model_id = file_rows(app, item_id)[0]["id"]
    post_preview(auth, item_id, model_id)
    first = item_row(app, item_id)["preview_name"]
    post_preview(auth, item_id, model_id)
    second = item_row(app, item_id)["preview_name"]
    assert first != second
    assert first not in disk_files(app) and second in disk_files(app)


def test_bad_previews_are_refused(auth, app):
    item_id = make_item(auth, files=[stl_file("a.stl"), stl_file("b.stl")])
    first, second = [r["id"] for r in file_rows(app, item_id)]

    stale = post_preview(auth, item_id, second)  # only the first model gets a preview
    assert stale.status_code == 409
    assert post_preview(auth, item_id, "abc").status_code == 409
    assert post_preview(auth, item_id, first, data=b"GIF89a....").status_code == 400
    assert post_preview(auth, item_id, first, data=b"\x89PNG\r\n\x1a\nbroken").status_code == 400
    assert post_preview(auth, item_id, first, data=preview_png((8, 8))).status_code == 400
    assert post_preview(auth, item_id, first, data=preview_png((3000, 100))).status_code == 400
    assert post_preview(auth, item_id, first, data=b"\x89PNG\r\n\x1a\n" + b"0" * 1_600_000).status_code == 400
    assert item_row(app, item_id)["preview_name"] is None
    assert not any(n.startswith("preview-") for n in disk_files(app))

    assert post_preview(auth, 999, first).status_code == 404
    no_models = make_item(auth, "Empty")
    assert post_preview(auth, no_models, first).status_code == 409


def test_preview_upload_needs_login_and_csrf(auth, app, client):
    item_id = make_item(auth, files=[stl_file()])
    model_id = file_rows(app, item_id)[0]["id"]
    no_token = app.test_client()
    assert no_token.post(f"/items/{item_id}/preview", data={"model_id": str(model_id)}).status_code == 400
    assert app.test_client().get(f"/items/{item_id}/preview").status_code == 302


def test_a_photo_takes_priority_over_the_preview(auth, app):
    item_id = make_item(auth, files=[stl_file(), (io.BytesIO(png((60, 40))), "p.png")])
    html = auth.get("/").data.decode()
    assert "data-preview-model" not in html and "/thumb" in html
    detail = auth.get(f"/items/{item_id}").data.decode()
    assert "data-preview-url" not in detail


def test_preview_is_dropped_when_the_first_model_changes(auth, app):
    item_id = make_item(auth, files=[stl_file("a.stl"), (io.BytesIO(make_3mf()), "b.3mf")])
    a, b = [r["id"] for r in file_rows(app, item_id)]
    post_preview(auth, item_id, a)
    old = item_row(app, item_id)["preview_name"]

    auth.post(f"/files/{b}/up")  # b becomes the first model
    row = item_row(app, item_id)
    assert row["preview_name"] is None and row["preview_file_id"] is None
    assert old not in disk_files(app)
    assert f"data-preview-model=\"{b}\"" in auth.get("/").data.decode()

    post_preview(auth, item_id, b)
    auth.post(f"/files/{b}/delete")  # deleting the model the picture shows
    assert item_row(app, item_id)["preview_name"] is None
    assert not any(n.startswith("preview-") for n in disk_files(app))


def test_adding_a_second_model_keeps_the_preview(auth, app):
    item_id = make_item(auth, files=[stl_file("a.stl")])
    a = file_rows(app, item_id)[0]["id"]
    post_preview(auth, item_id, a)
    auth.post(
        f"/items/{item_id}/files",
        data={"files": (io.BytesIO(make_3mf()), "b.3mf")},
        content_type="multipart/form-data",
    )
    assert item_row(app, item_id)["preview_file_id"] == a


def test_preview_stops_being_shown_once_it_is_out_of_date(auth, app):
    item_id = make_item(auth, files=[stl_file("a.stl")])
    a = file_rows(app, item_id)[0]["id"]
    post_preview(auth, item_id, a)
    with app.app_context():  # simulate a leftover from before the model changed
        db = get_db()
        db.execute("UPDATE items SET preview_file_id = ? WHERE id = ?", (a + 100, item_id))
        db.commit()
    html = auth.get("/").data.decode()
    assert "data-preview-model" in html and "/preview?v=" not in html


def test_deleting_an_item_deletes_its_preview(auth, app):
    item_id = make_item(auth, files=[stl_file()])
    post_preview(auth, item_id, file_rows(app, item_id)[0]["id"])
    assert any(n.startswith("preview-") for n in disk_files(app))
    auth.post(f"/items/{item_id}/delete")
    assert disk_files(app) == []


def test_queue_and_history_show_the_preview_picture(auth, app):
    item_id = make_item(auth, files=[stl_file()])
    model_id = file_rows(app, item_id)[0]["id"]
    post_preview(auth, item_id, model_id)
    auth.post(f"/items/{item_id}/queue", data={"quantity": "1"})
    assert f"/items/{item_id}/preview?v={model_id}".encode() in auth.get("/queue").data
