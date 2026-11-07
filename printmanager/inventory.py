import os
import re
import uuid
from collections import Counter

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from .auth import login_required
from .db import get_db

bp = Blueprint("inventory", __name__)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

ITEM_LIST_SQL = """
SELECT i.*,
       COALESCE(SUM(CASE WHEN j.status = 'queued' THEN j.quantity END), 0) AS queued_qty,
       COALESCE(SUM(CASE WHEN j.status = 'printing' THEN j.quantity END), 0) AS printing_qty,
       COALESCE(SUM(CASE WHEN j.status = 'completed' THEN j.quantity END), 0) AS completed_qty
FROM items i
LEFT JOIN print_jobs j ON j.item_id = i.id
WHERE i.name LIKE ? OR i.description LIKE ?
GROUP BY i.id
ORDER BY i.name COLLATE NOCASE
"""


def _save_image(storage):
    ext = os.path.splitext(storage.filename)[1].lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("Photo must be a PNG, JPG, GIF or WebP image.")
    name = f"{uuid.uuid4().hex}.{ext}"
    storage.save(os.path.join(current_app.config["UPLOAD_FOLDER"], name))
    return name


def _remove_image(name):
    if not name:
        return
    try:
        os.remove(os.path.join(current_app.config["UPLOAD_FOLDER"], name))
    except FileNotFoundError:
        pass


def group_items(items):
    """Group items by the folder that contains their local path.

    Works with Windows (C:\\a\\b), UNC (\\\\nas\\share) and Linux (/a/b) paths.
    A path shared by several items is treated as a folder holding them, and
    they are grouped under it. Otherwise the folder is the path minus its last
    segment, so an item alone in its own folder, such as
    C:\\Models\\Household\\Hooks\\Wall hook, is filed under Household / Hooks.
    The part of the folder path shared by every group is dropped from the
    headings. Returns [(heading, [items])], sorted, with items that have no
    path last.
    """
    groups = {}  # case-insensitive folder key -> (folder as first typed, items)
    unfiled = []
    parsed = []
    for item in items:
        segments = [s for s in re.split(r"[\\/]+", item["path"] or "") if s]
        if segments:
            parsed.append((item, segments))
        else:
            unfiled.append(item)

    # Several items with exactly the same path means that path is a folder
    # holding all of them.
    shared = Counter(tuple(s.casefold() for s in segs) for _item, segs in parsed)
    for item, segments in parsed:
        full = tuple(s.casefold() for s in segments)
        if shared[full] > 1:
            folder, key = segments, full
        else:
            folder, key = segments[:-1], full[:-1]
        groups.setdefault(key, (folder, []))[1].append(item)

    keys = sorted(groups)
    common = 0
    if keys:
        limit = max(min(len(k) for k in keys) - 1, 0)  # always keep a last segment
        while common < limit and len({k[common] for k in keys}) == 1:
            common += 1

    result = []
    for key in keys:
        folder, members = groups[key]
        result.append((" / ".join(folder[common:]) or "Top level", members))
    if unfiled:
        result.append(("No folder path", unfiled))
    return result


def _get_item(item_id):
    item = get_db().execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        abort(404)
    return item


@bp.get("/")
@login_required
def index():
    q = request.args.get("q", "").strip()
    like = f"%{q}%"
    items = get_db().execute(ITEM_LIST_SQL, (like, like)).fetchall()
    groups = group_items(items)
    can_group = len(groups) > 1
    return render_template(
        "inventory.html",
        items=items,
        q=q,
        groups=groups,
        can_group=can_group,
        use_groups=can_group and request.args.get("group") != "0",
    )


@bp.route("/items/new", methods=("GET", "POST"))
@login_required
def new_item():
    return _item_form(None)


@bp.route("/items/<int:item_id>/edit", methods=("GET", "POST"))
@login_required
def edit_item(item_id):
    return _item_form(_get_item(item_id))


def _item_form(item):
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        model_url = request.form.get("model_url", "").strip()
        # Stored exactly as typed (Windows, UNC and Linux paths all work); the
        # app only displays it and never touches the filesystem.
        path = request.form.get("path", "").strip()

        error = None
        if not name:
            error = "Name is required."
        elif len(name) > 120:
            error = "Name must be 120 characters or fewer."
        elif len(path) > 500:
            error = "Local file path must be 500 characters or fewer."
        elif model_url and not model_url.lower().startswith(("http://", "https://")):
            error = "Model link must start with http:// or https://."

        new_image = None
        upload = request.files.get("image")
        if not error and upload and upload.filename:
            try:
                new_image = _save_image(upload)
            except ValueError as exc:
                error = str(exc)

        if error:
            flash(error, "error")
        else:
            db = get_db()
            if item is None:
                cur = db.execute(
                    "INSERT INTO items (name, description, model_url, path,"
                    " image_filename, created_by) VALUES (?, ?, ?, ?, ?, ?)",
                    (name, description, model_url, path, new_image, g.user["id"]),
                )
                item_id = cur.lastrowid
            else:
                old_image = item["image_filename"]
                final_image = old_image
                if new_image:
                    final_image = new_image
                elif request.form.get("remove_image"):
                    final_image = None
                db.execute(
                    "UPDATE items SET name = ?, description = ?, model_url = ?,"
                    " path = ?, image_filename = ? WHERE id = ?",
                    (name, description, model_url, path, final_image, item["id"]),
                )
                if final_image != old_image:
                    _remove_image(old_image)
                item_id = item["id"]
            db.commit()
            flash("Item saved.", "success")
            return redirect(url_for("inventory.item_detail", item_id=item_id))

    form = request.form if request.method == "POST" else None
    return render_template("item_form.html", item=item, form=form)


@bp.get("/items/<int:item_id>")
@login_required
def item_detail(item_id):
    item = _get_item(item_id)
    jobs = get_db().execute(
        "SELECT j.*, u.username AS queued_by_name FROM print_jobs j"
        " LEFT JOIN users u ON u.id = j.queued_by"
        " WHERE j.item_id = ? ORDER BY j.id DESC",
        (item_id,),
    ).fetchall()
    return render_template("item_detail.html", item=item, jobs=jobs)


@bp.post("/items/<int:item_id>/delete")
@login_required
def delete_item(item_id):
    item = _get_item(item_id)
    db = get_db()
    db.execute("DELETE FROM items WHERE id = ?", (item_id,))
    db.commit()
    _remove_image(item["image_filename"])
    flash(f"Deleted {item['name']}.", "success")
    return redirect(url_for("inventory.index"))


@bp.get("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    response = send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.cache_control.max_age = 86400
    return response
