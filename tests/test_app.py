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


def test_photo_upload_serving_and_removal(auth, app):
    item_id = make_item(auth, image=(io.BytesIO(PNG), "boat.png"))
    with app.app_context():
        filename = get_db().execute(
            "SELECT image_filename FROM items WHERE id = ?", (item_id,)
        ).fetchone()[0]
    assert filename.endswith(".png")

    img = auth.get(f"/uploads/{filename}")
    assert img.status_code == 200
    assert img.headers["X-Content-Type-Options"] == "nosniff"

    auth.post(
        f"/items/{item_id}/edit",
        data={"name": "Benchy", "remove_image": "1"},
        content_type="multipart/form-data",
    )
    assert auth.get(f"/uploads/{filename}").status_code == 404


def test_non_image_upload_rejected(auth):
    resp = auth.post(
        "/items/new",
        data={"name": "x", "image": (io.BytesIO(b"<script>"), "evil.html")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert b"PNG, JPG, GIF or WebP" in resp.data


def test_uploads_require_login(client):
    assert client.get("/uploads/anything.png").status_code == 302


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
