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
    completed_at TEXT,
    -- A job is for the whole item, or for one STL/3MF of it (file_id). The file
    -- name is copied so history still reads right if the file is removed later.
    file_id INTEGER REFERENCES item_files(id) ON DELETE SET NULL,
    file_name TEXT NOT NULL DEFAULT '',
    -- The color and material chosen from Spoolman, copied at queue time so
    -- history survives spools being used up or deleted. filament_color is one
    -- hex value, or several separated by commas for multi-color filament.
    filament_name TEXT NOT NULL DEFAULT '',
    filament_material TEXT NOT NULL DEFAULT '',
    filament_color TEXT NOT NULL DEFAULT '',
    -- How many of quantity are finished. Equals quantity once the job is completed.
    done_qty INTEGER NOT NULL DEFAULT 0,
    -- A finished job (status 'completed') waits in "Ready for pickup" until
    -- someone picks it up, which sets picked_up_at and moves it to History.
    -- completed_at is when the print finished.
    picked_up_at TEXT
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
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    -- Overall size of a model in mm, measured once (see modelsize.py). dims_done
    -- is 1 once measuring was tried, so an unreadable file isn't retried forever.
    dim_x REAL,
    dim_y REAL,
    dim_z REAL,
    dims_done INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_files_item ON item_files(item_id);

-- Free-form tags on items. Tags match regardless of upper/lower case.
CREATE TABLE IF NOT EXISTS item_tags (
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    tag TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (item_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_tags_tag ON item_tags(tag);

-- Settings changed on the Settings page. They override the environment
-- variables of the same purpose (see settings.py).
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
