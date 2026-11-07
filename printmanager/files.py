"""Photos and 3D model files attached to items: upload, view, download, order."""

import os
import re
import tempfile
import uuid
import zipfile

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from .auth import login_required, safe_path
from .db import get_db

bp = Blueprint("files", __name__)

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MODEL_EXTENSIONS = {"stl", "3mf"}
IMAGE_MIMETYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}

# SQL expression (for queries that alias items as "i") giving an item's cover image id.
COVER_ID_SQL = (
    "(SELECT f.id FROM item_files f"
    " WHERE f.item_id = i.id AND f.kind = 'image'"
    " ORDER BY f.sort_order, f.id LIMIT 1)"
)


def extension(name):
    return os.path.splitext(name or "")[1].lower().lstrip(".")


def _disk_path(stored_name):
    return os.path.join(current_app.config["UPLOAD_FOLDER"], stored_name)


def _unlink(stored_name):
    try:
        os.remove(_disk_path(stored_name))
    except FileNotFoundError:
        pass


def _clean_name(filename):
    """The name people see: no directories, no control characters."""
    name = os.path.basename((filename or "").replace("\\", "/"))
    return "".join(ch for ch in name if ch.isprintable())


def _valid_content(path, ext):
    """Cheap sanity check that a file really is what its extension claims."""
    with open(path, "rb") as fh:
        head = fh.read(84)
    if ext == "stl":
        if head.lstrip()[:5].lower() == b"solid":  # ASCII STL
            return True
        if len(head) == 84:  # binary STL: 80-byte header, triangle count, 50 bytes each
            triangles = int.from_bytes(head[80:84], "little")
            return triangles > 0 and 84 + 50 * triangles <= os.path.getsize(path)
        return False
    if ext == "3mf":
        return zipfile.is_zipfile(path)
    if ext == "png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in ("jpg", "jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == "gif":
        return head.startswith((b"GIF87a", b"GIF89a"))
    if ext == "webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    return False


def save_upload(storage, item_id):
    """Store one uploaded file for an item. Raises ValueError with a readable message."""
    full_name = _clean_name(storage.filename)
    ext = extension(full_name)
    label = full_name[:80] or "File"
    if ext in IMAGE_EXTENSIONS:
        kind = "image"
    elif ext in MODEL_EXTENSIONS:
        kind = "model"
    else:
        raise ValueError(
            f"{label}: only STL, 3MF, PNG, JPG, GIF and WebP files can be added."
        )

    stored_name = f"{uuid.uuid4().hex}.{ext}"
    path = _disk_path(stored_name)
    storage.save(path)
    if not _valid_content(path, ext):
        os.remove(path)
        raise ValueError(f"{label}: this doesn't look like a valid {ext.upper()} file.")

    db = get_db()
    next_order = db.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM item_files"
        " WHERE item_id = ? AND kind = ?",
        (item_id, kind),
    ).fetchone()[0]
    cur = db.execute(
        "INSERT INTO item_files (item_id, kind, original_name, stored_name, size,"
        " sort_order, uploaded_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            item_id,
            kind,
            full_name[:200],
            stored_name,
            os.path.getsize(path),
            next_order,
            g.user["id"],
        ),
    )
    db.commit()
    return cur.lastrowid


def save_uploads(storages, item_id):
    """Store several uploads. Returns (number saved, [error messages])."""
    saved, errors = 0, []
    for storage in storages:
        if not storage or not storage.filename:
            continue
        try:
            save_upload(storage, item_id)
            saved += 1
        except ValueError as exc:
            errors.append(str(exc))
    return saved, errors


def files_for_item(item_id):
    """(images, models) for an item, each in display order."""
    rows = get_db().execute(
        "SELECT * FROM item_files WHERE item_id = ? ORDER BY sort_order, id",
        (item_id,),
    ).fetchall()
    return (
        [r for r in rows if r["kind"] == "image"],
        [r for r in rows if r["kind"] == "model"],
    )


def remove_item_files(item_id):
    """Delete every file of an item, from the database and from disk."""
    db = get_db()
    names = [
        r["stored_name"]
        for r in db.execute(
            "SELECT stored_name FROM item_files WHERE item_id = ?", (item_id,)
        )
    ]
    db.execute("DELETE FROM item_files WHERE item_id = ?", (item_id,))
    db.commit()
    for name in names:
        _unlink(name)


def _get_file(file_id):
    row = get_db().execute(
        "SELECT * FROM item_files WHERE id = ?", (file_id,)
    ).fetchone()
    if row is None:
        abort(404)
    return row


def _reorder(f, action):
    db = get_db()
    ids = [
        r["id"]
        for r in db.execute(
            "SELECT id FROM item_files WHERE item_id = ? AND kind = ?"
            " ORDER BY sort_order, id",
            (f["item_id"], f["kind"]),
        )
    ]
    i = ids.index(f["id"])
    if action == "cover":
        ids.insert(0, ids.pop(i))
    elif action == "up" and i > 0:
        ids[i - 1], ids[i] = ids[i], ids[i - 1]
    elif action == "down" and i < len(ids) - 1:
        ids[i + 1], ids[i] = ids[i], ids[i + 1]
    for position, file_id in enumerate(ids):
        db.execute("UPDATE item_files SET sort_order = ? WHERE id = ?", (position, file_id))
    db.commit()


@bp.app_template_filter("filesize")
def filesize(num):
    num = float(num or 0)
    for unit in ("B", "KB", "MB"):
        if num < 1024:
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


@bp.app_template_filter("fileext")
def fileext(name):
    return extension(name).upper()


@bp.get("/files/<int:file_id>/raw")
@login_required
def raw(file_id):
    """The file itself, for showing images and feeding the 3D viewer."""
    f = _get_file(file_id)
    mimetype = IMAGE_MIMETYPES.get(extension(f["stored_name"]), "application/octet-stream")
    response = send_file(
        _disk_path(f["stored_name"]), mimetype=mimetype, conditional=True, max_age=86400
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.get("/files/<int:file_id>/download")
@login_required
def download(file_id):
    f = _get_file(file_id)
    return send_file(
        _disk_path(f["stored_name"]),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=f["original_name"],
        conditional=True,
    )


@bp.get("/items/<int:item_id>/download-all")
@login_required
def download_all(item_id):
    """Every 3D model of an item in one zip."""
    item = get_db().execute(
        "SELECT id, name FROM items WHERE id = ?", (item_id,)
    ).fetchone()
    if item is None:
        abort(404)
    _images, models = files_for_item(item_id)
    if not models:
        abort(404)

    archive = tempfile.TemporaryFile()
    used = set()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as zf:
        for f in models:
            arcname = f["original_name"]
            base, ext = os.path.splitext(arcname)
            n = 1
            while arcname.lower() in used:
                n += 1
                arcname = f"{base} ({n}){ext}"
            used.add(arcname.lower())
            try:
                zf.write(_disk_path(f["stored_name"]), arcname)
            except FileNotFoundError:
                continue
    archive.seek(0)
    zip_name = (re.sub(r"[^\w\- ]+", "", item["name"]).strip() or "models") + ".zip"
    return send_file(
        archive, mimetype="application/zip", as_attachment=True, download_name=zip_name
    )


@bp.post("/items/<int:item_id>/files")
@login_required
def upload(item_id):
    """Add files to an existing item (used by drag and drop on the edit page)."""
    item = get_db().execute("SELECT id FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        abort(404)
    saved, errors = save_uploads(request.files.getlist("files"), item_id)
    edit_url = url_for("inventory.edit_item", item_id=item_id)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        images, models = files_for_item(item_id)
        html = render_template(
            "_file_list.html",
            images=images,
            models=models,
            editable=True,
            next_url=edit_url,
        )
        status = 400 if errors and not saved else 200
        return jsonify(html=html, saved=saved, errors=errors), status

    for message in errors:
        flash(message, "error")
    if saved:
        flash(f"Added {saved} file{'s' if saved != 1 else ''}.", "success")
    return redirect(safe_path(request.form.get("next"), edit_url))


@bp.post("/files/<int:file_id>/<action>")
@login_required
def update_file(file_id, action):
    f = _get_file(file_id)
    if action == "delete":
        db = get_db()
        db.execute("DELETE FROM item_files WHERE id = ?", (file_id,))
        db.commit()
        _unlink(f["stored_name"])
        flash(f"Removed {f['original_name']}.", "success")
    elif action in ("up", "down") or (action == "cover" and f["kind"] == "image"):
        _reorder(f, action)
    else:
        abort(404)
    return redirect(
        safe_path(
            request.form.get("next"),
            url_for("inventory.edit_item", item_id=f["item_id"]),
        )
    )
