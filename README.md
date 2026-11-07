# Print Manager

A small web app for tracking 3D printing jobs. Keep an inventory of the things you print (with photos, notes and a link to the model), add them to a print queue, and mark them done when they come off the printer. Filament is intentionally out of scope; use Spoolman for that.

- **Inventory:** name, description, optional model link, search
- **Files:** attach any number of STL and 3MF files and photos to an item. Drag and drop onto the add or edit page (on the edit page files upload straight away and are added to the existing list). Every file can be downloaded under its original name, and an item's models can be downloaded together as a zip. The first photo is the cover shown on the inventory card, and you can reorder or change it
- **3D viewer:** the item page previews STL and 3MF models in the browser (rotate, zoom, pan, with the size in mm). three.js is bundled in `printmanager/static/vendor`, so it works without internet access
- **Local file path:** note where each item's STL files live on your PC (e.g. `C:\Models\Benchy` or `\\nas\prints\Benchy`), shown on the item page with a copy button. It's just a text note; the app never reads your files
- **Folders:** the inventory is grouped into collapsible sections by folder: items that share the same path are grouped under that folder, and an item alone in its own folder is filed under its parent (so `C:\Models\Household\Hooks\Wall hook` goes under Household / Hooks). Folders shared by every item are trimmed from the headings, and a toggle switches to a flat list
- **Queue:** add any item with a quantity and note, then move it Queued → Printing → Completed
- **History:** completed prints, with "print again" to requeue
- **Logins:** username/password for a couple of users sharing one inventory and queue (no public signup)

Built with Flask and SQLite. No build step, and everything lives in one data folder.

## Run it locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# create a login for each person (prompts for a password)
flask --app printmanager create-user alice
flask --app printmanager create-user bob

flask --app printmanager run --debug
```

Open http://127.0.0.1:5000. Data is stored in `instance/` (database, uploaded photos and a generated secret key).

## Run it with Docker

```bash
cp .env.example .env     # set SECRET_KEY, and optionally SEED_USERS
docker compose up -d --build
```

Open http://your-server:8000. Data is stored in `./data`, so back that folder up.

Create or reset logins in the running container:

```bash
docker compose exec printmanager flask --app printmanager create-user alice
docker compose exec printmanager flask --app printmanager set-password alice
```

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `SECRET_KEY` | Signs login sessions | generated and saved in `instance/secret_key` |
| `SEED_USERS` | `user:pass,user:pass`, created on startup if missing | none |
| `APP_TIMEZONE` | Timezone for displayed times | `America/New_York` |
| `DATABASE` | SQLite file path | `instance/printmanager.db` |
| `UPLOAD_FOLDER` | Where uploaded files are stored | `instance/uploads` |
| `MAX_UPLOAD_MB` | Largest upload (one save or one dropped file), in MB | `200` |

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Notes

- There's no login rate limiting. It's meant for a home network; if you expose it to the internet, put it behind HTTPS and a reverse proxy (and consider extra protection such as a VPN).
- Uploads are STL, 3MF, PNG, JPG, GIF or WebP, checked by content as well as extension. Uploaded files live in the data folder next to the database, so include it in backups (it grows with your models).
- Behind a reverse proxy, allow large request bodies (nginx: `client_max_body_size 200m;`), or uploads of big STL files will be refused.
- Very detailed models (hundreds of thousands of triangles) can be slow to preview on a phone. Files over 30 MB aren't opened automatically; use "View in 3D".
- The viewer needs WebGL. Without it you still get downloads.
- Photos from before this version were converted automatically on first start.
- All times are stored in UTC and shown in `APP_TIMEZONE`.
