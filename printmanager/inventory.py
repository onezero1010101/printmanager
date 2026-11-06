import os
import uuid

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
WHERE (i.name LIKE ? OR i.description LIKE ? OR i.path LIKE ?)
  AND (? = '' OR i.path = ? OR substr(i.path, 1, length(?) + 1) = ? || '/')
GROUP BY i.id
ORDER BY i.name COLLATE NOCASE
"""


def normalize_path(raw):
    """Turn 'a\\b//c/' into 'a/b/c'. Paths are labels for organizing, never opened."""
    parts = [p.strip() for p in (raw or "").replace("\\", "/").split("/")]
    return "/".join(p for p in parts if p and p not in (".", ".."))


@bp.app_template_global("folder_crumbs")
def folder_crumbs(path):
    """[(name, full_path), ...] for each level of a folder path."""
    crumbs, acc = [], []
    for part in (path or "").split("/"):
        if part:
            acc.append(part)
            crumbs.append((part, "/".join(acc)))
    return crumbs


def _subfolders(paths, current):
    """Immediate child folders of `current` as (name, full_path, item_count)."""
    prefix = current + "/" if current else ""
    counts = {}
    for p in paths:
        if current and not p.startswith(prefix):
            continue
        rest = p[len(prefix):]
        if rest:
            child = rest.split("/", 1)[0]
            counts[child] = counts.get(child, 0) + 1
    return [
        (name, prefix + name, counts[name])
        for name in sorted(counts, key=str.casefold)
    ]


def _all_folders():
    """Every folder (including parents of deeper ones) for form suggestions."""
    folders = set()
    for row in get_db().execute("SELECT DISTINCT path FROM items WHERE path != ''"):
        for _name, full in folder_crumbs(row["path"]):
            folders.add(full)
    return sorted(folders, key=str.casefold)


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


def _get_item(item_id):
    item = get_db().execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        abort(404)
    return item


@bp.get("/")
@login_required
def index():
    q = request.args.get("q", "").strip()
    folder = normalize_path(request.args.get("folder", ""))
    like = f"%{q}%"
    db = get_db()
    items = db.execute(
        ITEM_LIST_SQL, (like, like, like, folder, folder, folder, folder)
    ).fetchall()
    paths = [r["path"] for r in db.execute("SELECT path FROM items WHERE path != ''")]
    return render_template(
        "inventory.html",
        items=items,
        q=q,
        folder=folder,
        subfolders=_subfolders(paths, folder),
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
        path = normalize_path(request.form.get("path", ""))

        error = None
        if not name:
            error = "Name is required."
        elif len(name) > 120:
            error = "Name must be 120 characters or fewer."
        elif len(path) > 300:
            error = "Folder path must be 300 characters or fewer."
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
    # "Add item" from inside a folder pre-fills that folder.
    prefill_path = normalize_path(request.args.get("path", "")) if item is None else ""
    return render_template(
        "item_form.html",
        item=item,
        form=form,
        folders=_all_folders(),
        prefill_path=prefill_path,
    )


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
