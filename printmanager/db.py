import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import click
from flask import current_app, g
from werkzeug.security import generate_password_hash


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(Path(__file__).with_name("schema.sql").read_text())
    # Migrations for databases created by older versions.
    columns = {row["name"] for row in db.execute("PRAGMA table_info(items)")}
    for name, definition in (
        ("path", "TEXT NOT NULL DEFAULT ''"),
        ("preview_name", "TEXT"),
        ("preview_file_id", "INTEGER"),
    ):
        if name not in columns:
            db.execute(f"ALTER TABLE items ADD COLUMN {name} {definition}")

    job_columns = {row["name"] for row in db.execute("PRAGMA table_info(print_jobs)")}
    for name, definition in (
        ("file_id", "INTEGER REFERENCES item_files(id) ON DELETE SET NULL"),
        ("file_name", "TEXT NOT NULL DEFAULT ''"),
        ("filament_name", "TEXT NOT NULL DEFAULT ''"),
        ("filament_material", "TEXT NOT NULL DEFAULT ''"),
        ("filament_color", "TEXT NOT NULL DEFAULT ''"),
    ):
        if name not in job_columns:
            db.execute(f"ALTER TABLE print_jobs ADD COLUMN {name} {definition}")

    if "done_qty" not in job_columns:
        db.execute("ALTER TABLE print_jobs ADD COLUMN done_qty INTEGER NOT NULL DEFAULT 0")
        # Jobs finished before this existed were finished in full.
        db.execute("UPDATE print_jobs SET done_qty = quantity WHERE status = 'completed'")

    # Single photos (items.image_filename) became rows in item_files.
    old_photos = db.execute(
        "SELECT id, image_filename FROM items WHERE image_filename IS NOT NULL"
    ).fetchall()
    for row in old_photos:
        name = row["image_filename"]
        try:
            size = os.path.getsize(os.path.join(current_app.config["UPLOAD_FOLDER"], name))
        except OSError:
            size = 0
        db.execute(
            "INSERT INTO item_files (item_id, kind, original_name, stored_name, size, sort_order)"
            " VALUES (?, 'image', ?, ?, ?, 0)",
            (row["id"], name, name, size),
        )
    if old_photos:
        db.execute("UPDATE items SET image_filename = NULL WHERE image_filename IS NOT NULL")
    db.commit()


def add_user(username, password):
    """Create a user. Returns False if the username already exists."""
    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username.strip().lower(), generate_password_hash(password)),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return False
    return True


def seed_users_from_env():
    """Create missing users from SEED_USERS="alice:pw1,bob:pw2".

    Existing users are left untouched, so changing the variable later never
    overwrites a password that was changed some other way.
    """
    raw = current_app.config.get("SEED_USERS") or os.environ.get("SEED_USERS", "")
    for entry in raw.split(","):
        username, sep, password = entry.strip().partition(":")
        if sep and username.strip() and password:
            add_user(username, password)


@click.command("init-db")
def init_db_command():
    """Create the database tables (safe to run repeatedly)."""
    init_db()
    click.echo("Database ready.")


@click.command("create-user")
@click.argument("username")
@click.password_option()
def create_user_command(username, password):
    """Create a login, e.g. flask --app printmanager create-user alice."""
    if add_user(username, password):
        click.echo(f"Created user '{username.strip().lower()}'.")
    else:
        raise click.ClickException(f"User '{username}' already exists.")


@click.command("set-password")
@click.argument("username")
@click.password_option()
def set_password_command(username, password):
    """Change an existing user's password."""
    db = get_db()
    cur = db.execute(
        "UPDATE users SET password_hash = ? WHERE username = ?",
        (generate_password_hash(password), username.strip().lower()),
    )
    db.commit()
    if cur.rowcount == 0:
        raise click.ClickException(f"No such user '{username}'.")
    click.echo("Password updated.")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(create_user_command)
    app.cli.add_command(set_password_command)
    with app.app_context():
        init_db()
        seed_users_from_env()
