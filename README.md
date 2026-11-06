# Print Manager

A small web app for tracking 3D printing jobs. Keep an inventory of the things you print (with photos, notes and a link to the model), add them to a print queue, and mark them done when they come off the printer. Filament is intentionally out of scope; use Spoolman for that.

- **Inventory:** name, description, photo, optional model link, search
- **Folders:** give each item a path like `Household/Hooks`, then browse by folder (breadcrumbs and subfolder chips). Use the same layout as the model files on your disk if you like; the path is only a label, the app never reads your filesystem
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
| `UPLOAD_FOLDER` | Where photos are stored | `instance/uploads` |

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Notes

- There's no login rate limiting. It's meant for a home network; if you expose it to the internet, put it behind HTTPS and a reverse proxy (and consider extra protection such as a VPN).
- Photos must be PNG, JPG, GIF or WebP, up to 16 MB.
- All times are stored in UTC and shown in `APP_TIMEZONE`.
