CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    model_url TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    image_filename TEXT,
    -- Static picture of the first 3D model, rendered in the browser. Only used
    -- while preview_file_id is still the item's first model.
    preview_name TEXT,
    preview_file_id INTEGER,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Timestamps are stored in UTC as 'YYYY-MM-DD HH:MM:SS'.
CREATE TABLE IF NOT EXISTS print_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'printing', 'completed')),
    notes TEXT NOT NULL DEFAULT '',
    queued_by INTEGER REFERENCES users(id),
    queued_at TEXT NOT NULL DEFAULT (datetime('now')),
    started_at TEXT,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON print_jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_item ON print_jobs(item_id);

-- Photos (kind 'image') and 3D models (kind 'model') attached to an item.
-- The first image by sort_order is the item's cover. Files live in the upload
-- folder under stored_name; original_name is what people see and download.
CREATE TABLE IF NOT EXISTS item_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('image', 'model')),
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    uploaded_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_files_item ON item_files(item_id);
