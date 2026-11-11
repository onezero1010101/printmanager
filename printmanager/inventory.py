from flask import (
    Blueprint,
    abort,
    flash,
    g,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

from .auth import login_required
from .db import get_db
from .files import (
    COVER_ID_SQL,
    FIRST_MODEL_ID_SQL,
    files_for_item,
    remove_item_files,
    save_uploads,
)
from .tags import all_tags, parse_tags, set_tags, tags_by_item
from .folders import (
    NO_PATH,
    TOP,
    build_tree,
    common_depth,
    folders_of,
    in_folder,
    path_segments,
)

bp = Blueprint("inventory", __name__)

ITEM_LIST_SQL = f"""
SELECT i.*,
       {COVER_ID_SQL} AS cover_id,
       {FIRST_MODEL_ID_SQL} AS first_model_id,
       (SELECT COUNT(*) FROM item_files f WHERE f.item_id = i.id AND f.kind = 'image') AS image_count,
       (SELECT COUNT(*) FROM item_files f WHERE f.item_id = i.id AND f.kind = 'model') AS model_count,
       COALESCE(SUM(CASE WHEN j.status = 'queued' THEN j.quantity - j.done_qty END), 0) AS queued_qty,
       COALESCE(SUM(CASE WHEN j.status = 'printing' THEN j.quantity - j.done_qty END), 0) AS printing_qty,
       COALESCE(SUM(j.done_qty), 0) AS completed_qty
FROM items i
LEFT JOIN print_jobs j ON j.item_id = i.id
GROUP BY i.id
ORDER BY i.name COLLATE NOCASE
"""

# "Missing" filters: key -> (label, is this item missing it?)
MISSING = {
    "path": ("No local path", lambda i: not i["path"]),
    "model": ("No 3D model", lambda i: not i["model_count"]),
    "photo": ("No photo", lambda i: not i["image_count"]),
}
VIEWS = ("cards", "list")


def _load_items():
    """Every item as a dict, with its counts and what its card needs to show."""
    db = get_db()
    items = [dict(row) for row in db.execute(ITEM_LIST_SQL)]
    models = {
        row["id"]: row
        for row in db.execute(
            "SELECT id, stored_name, size FROM item_files WHERE kind = 'model'"
        )
    }
    tags = tags_by_item(db)
    for item in items:
        item["tags"] = tags.get(item["id"], [])
        model = models.get(item["first_model_id"])
        item["first_model_ext"] = model["stored_name"].rsplit(".", 1)[-1] if model else ""
        item["first_model_size"] = model["size"] if model else 0
        has_preview = (
            bool(item["preview_name"]) and item["preview_file_id"] == item["first_model_id"]
        )
        # No photo, but a model: the browser should draw a picture of it (see previews.js).
        item["needs_preview"] = (
            not item["cover_id"] and bool(item["first_model_id"]) and not has_preview
        )
    return items


@bp.get("/")
@login_required
def index():
    q = request.args.get("q", "").strip()
    folder = request.args.get("folder", "").strip()
    missing = []
    for key in request.args.get("missing", "").split(","):
        if key in MISSING and key not in missing:
            missing.append(key)
    selected_tags = []
    for raw in request.args.get("tag", "").split(","):
        raw = raw.strip()
        if raw and raw.casefold() not in [t.casefold() for t in selected_tags]:
            selected_tags.append(raw)
    view = request.args.get("view")
    if view not in VIEWS:
        view = request.cookies.get("pm_view")
    if view not in VIEWS:
        view = "cards"

    items = _load_items()
    folders = folders_of(items)
    depth = common_depth(folders.values())

    needle = q.casefold()
    wanted = {t.casefold() for t in selected_tags}

    def has_all_tags(item, extra=()):
        have = {t.casefold() for t in item["tags"]}
        return wanted <= have and all(e.casefold() in have for e in extra)

    searched = [
        item
        for item in items
        if (
            not needle
            or needle in f"{item['name']}\n{item['description']}\n{item['path']}\n{' '.join(item['tags'])}".casefold()
        )
        and all(MISSING[key][1](item) for key in missing)
    ]
    matching = [item for item in searched if has_all_tags(item)]
    filtering = bool(needle or missing or selected_tags)
    tree, specials = build_tree(
        items,
        folders,
        depth,
        {item["id"] for item in matching},
        selected=folder,
        open_all=filtering,
    )

    visible = [item for item in matching if in_folder(item["id"], folders, folder)]
    for item in visible:
        item["folder_label"] = " / ".join(folders[item["id"]][depth:]) if item["id"] in folders else ""

    def link(**overrides):
        """URL of this page with some settings changed (empty values are dropped)."""
        params = {"q": q, "folder": folder, "missing": ",".join(missing),
                  "tag": ",".join(selected_tags)}
        params.update(overrides)
        return url_for("inventory.index", **{k: v for k, v in params.items() if v})

    chips = []
    for key, (label, is_missing) in MISSING.items():
        active = key in missing
        toggled = [k for k in missing if k != key] if active else missing + [key]
        chips.append(
            {
                "key": key,
                "label": label,
                "count": sum(1 for item in items if is_missing(item)),
                "active": active,
                "url": link(missing=",".join(toggled)),
            }
        )

    def tag_url(name):
        """This page with a tag added to the filter (or taken off if it's already there)."""
        key = name.casefold()
        if key in wanted:
            rest = [t for t in selected_tags if t.casefold() != key]
        else:
            rest = selected_tags + [name]
        return link(tag=",".join(rest))

    # Tag list for the sidebar: how many items in this view each tag would leave.
    in_view = [item for item in searched if in_folder(item["id"], folders, folder)]
    narrowed = [item for item in in_view if has_all_tags(item)]
    tag_counts = []
    for name in all_tags(get_db()):
        active = name.casefold() in wanted
        count = len(narrowed) if active else sum(
            1 for item in narrowed if has_all_tags(item, (name,))
        )
        if count or active:
            tag_counts.append({"name": name, "count": count, "active": active, "url": tag_url(name)})

    segments = path_segments(folder)
    crumbs = (
        [(segments[i], "/".join(segments[: i + 1])) for i in range(depth, len(segments))]
        if folder not in ("", NO_PATH, TOP)
        else []
    )
    if folder == NO_PATH:
        title = "No local path"
    elif folder == TOP:
        title = "Top level"
    elif crumbs:
        title = crumbs[-1][0]
    else:
        title = "All items"

    response = make_response(
        render_template(
            "inventory.html",
            items=visible,
            total_items=len(items),
            total_matching=len(matching),
            q=q,
            folder=folder,
            missing=missing,
            filtering=filtering,
            view=view,
            tree=tree,
            specials=specials,
            chips=chips,
            crumbs=crumbs,
            title=title,
            link=link,
            tag_url=tag_url,
            tag_counts=tag_counts,
            selected_tags=selected_tags,
        )
    )
    if request.args.get("view") in VIEWS:
        response.set_cookie("pm_view", view, max_age=365 * 24 * 3600, samesite="Lax", httponly=True)
    return response


def _get_item(item_id):
    item = get_db().execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        abort(404)
    return item


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
        tags, tag_error = parse_tags(request.form.get("tags", ""))
        error = error or tag_error

        if error:
            flash(error, "error")
            if any(f.filename for f in request.files.getlist("files")):
                flash("Your files weren't added. Add them again once the form is fixed.", "error")
        else:
            db = get_db()
            if item is None:
                cur = db.execute(
                    "INSERT INTO items (name, description, model_url, path, created_by)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (name, description, model_url, path, g.user["id"]),
                )
                item_id = cur.lastrowid
            else:
                db.execute(
                    "UPDATE items SET name = ?, description = ?, model_url = ?,"
                    " path = ? WHERE id = ?",
                    (name, description, model_url, path, item["id"]),
                )
                item_id = item["id"]
            set_tags(db, item_id, tags)
            db.commit()

            saved, errors = save_uploads(request.files.getlist("files"), item_id)
            for message in errors:
                flash(message, "error")
            flash(
                "Item saved."
                + (f" Added {saved} file{'s' if saved != 1 else ''}." if saved else ""),
                "success",
            )
            return redirect(url_for("inventory.item_detail", item_id=item_id))

    form = request.form if request.method == "POST" else None
    images, models = files_for_item(item["id"]) if item else ([], [])
    if form is not None:
        tags_text = form.get("tags", "")
    else:
        tags_text = ", ".join(tags_by_item(get_db()).get(item["id"], [])) if item else ""
    return render_template(
        "item_form.html",
        item=item,
        tags_text=tags_text,
        known_tags=all_tags(get_db()),
        form=form,
        images=images,
        models=models,
        editable=True,
        next_url=url_for("inventory.edit_item", item_id=item["id"]) if item else None,
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
    images, models = files_for_item(item_id)
    first = models[0] if models else None
    has_preview = bool(
        first and item["preview_name"] and item["preview_file_id"] == first["id"]
    )
    return render_template(
        "item_detail.html",
        item=item,
        jobs=jobs,
        tags=tags_by_item(get_db()).get(item_id, []),
        images=images,
        models=models,
        viewer=True,
        editable=False,
        next_url=url_for("inventory.item_detail", item_id=item_id),
        show_preview=has_preview and not images,
        needs_preview=bool(first) and not images and not has_preview,
    )


@bp.post("/items/<int:item_id>/delete")
@login_required
def delete_item(item_id):
    item = _get_item(item_id)
    remove_item_files(item_id)
    db = get_db()
    db.execute("DELETE FROM items WHERE id = ?", (item_id,))
    db.commit()
    flash(f"Deleted {item['name']}.", "success")
    return redirect(url_for("inventory.index"))
