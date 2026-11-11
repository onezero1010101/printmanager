# Print Manager

A small web app for tracking 3D printing jobs. Keep an inventory of the things you print (with photos, notes and a link to the model), add them to a print queue, and mark them done when they come off the printer. Filament stock is intentionally out of scope; Spoolman handles that, and this app only reads colors from it.

- **Inventory:** name, description, optional model link, search
- **Files:** attach any number of STL and 3MF files and photos to an item. Drag and drop onto the add or edit page, or drop a zip: every STL, 3MF and image inside is added (folders are flattened, other files are skipped) (on the edit page files upload straight away and are added to the existing list). Every file can be downloaded under its original name, and an item's models can be downloaded together as a zip. The first photo is the cover shown on the inventory card, and you can reorder or change it
- **3D viewer:** the item page previews STL and 3MF models in the browser (rotate, zoom, pan, with the size in mm). three.js is bundled in `printmanager/static/vendor`, so it works without internet access
- **Local file path:** note where each item's STL files live on your PC (e.g. `C:\Models\Benchy` or `\\nas\prints\Benchy`), shown on the item page with a copy button. It's just a text note; the app never reads your files
- **Folder tree:** a sidebar tree built from the local paths. Items that share the same path are filed under that folder, and an item alone at its path is filed under its parent (so `C:\Models\Household\Hooks\Wall hook` goes under Household / Hooks). Folders start collapsed and the app remembers which ones you opened; "Expand all" and "Collapse all" are there too. Clicking a folder shows everything inside it, sub-folders included. On a phone the tree folds up under a "Folders" heading. Folders shared by every item are trimmed from the top of the tree, and an orange dot marks folders containing items without a 3D model
- **Cards or list:** switch between photo cards and a compact list. The choice is remembered
- **Missing info:** filter chips for "No local path", "No 3D model" and "No photo", each with a count. They combine with each other, with a selected folder and with search. Cards and rows are also marked with what they lack. Search covers the name, notes and local path
- **Thumbnails and previews:** photos are shown as small thumbnails (made automatically, including for photos uploaded before this version), so large phone pictures don't slow the page down. An item with a 3D model but no photo gets a picture of its first model instead. Your browser draws it and the app keeps it, so it appears on its own the first time the item or inventory page is opened, only for pictures near the screen, and is redrawn if the first model changes. A real photo always takes priority
- **Queue:** add any item with a quantity, an optional filament color and a note (from the inventory page or the item page), then move it Queued → Printing → Completed. An item with several STL/3MF files can be queued as a whole (one job) or one file at a time using the "Add to queue" button on each file; the queue shows which part a job is for and has a download button for it
- **Filament color (Spoolman):** when a Spoolman address is set, the queue forms have a color and material dropdown with swatches, one color per job, and a queued job's color can be changed in the queue. Archived and empty spools are skipped, and spools of the same material, name and color appear once. The color is copied onto the job, so history stays correct when a spool is used up. If Spoolman is unreachable you can still queue without a color
- **Partial completion:** a job for several copies shows "2 of 5 done" with a progress bar. Enter how many came off the printer and press "Mark done" (there's an Undo, and "Finish all" for the rest). The job moves to History when the last one is done, and the "printed" chips on inventory cards count finished copies straight away
- **Tags:** give items free-form tags (comma separated, e.g. `gift, functional`; matching ignores upper/lower case). Tags show on cards, rows and the item page, and the add/edit form suggests tags you've used before. The inventory sidebar lists tags with counts; click several to show only items that have **all** of them. Tag filters combine with folders, the missing-info chips and search (search also matches tags)
- **Bed fit check:** enter your printer's build volume and a margin (default 5 mm on each side) on the Settings page. Each STL/3MF is measured once when it's uploaded (files from before this were measured on first start) and the size is stored, so changing the bed size re-checks instantly. Every model shows its size and a mark: fits, fits turned flat or on its side, or too big by some mm. Queue rows show the same mark. STL has no units, so millimeters are assumed (3MF files declare theirs). Only the overall bounding box is checked, not brims, supports or tilted placement
- **Spools page:** shows the active (non-archived) spools from Spoolman with vendor, color, grams and metres left and a bar, sortable by material, color or least left. It follows the location setting. Spools under the low-stock level (default 100 g) are marked "low"
- **Settings:** the Settings page holds the Spoolman address and an optional spool location filter (e.g. only spools in `Tim`, or any location) the low-stock level in grams and the printer bed size. Values saved there override the environment variables
- **History:** completed prints stay in the history. "Print again" adds a new job to the queue (same part and color, quantity box starting at 1) and leaves the original entry alone
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
| `SPOOLMAN_URL` | Spoolman address, e.g. `http://192.168.1.20:7912` (empty = no color dropdown) | none |
| `SPOOLMAN_LOCATION` | Only offer spools in this Spoolman location (empty = any) | none |
| `BED_X`, `BED_Y`, `BED_Z` | Printer build volume in mm (empty = no fit check) | none |
| `BED_MARGIN` | Space kept free on each side of the bed, in mm | `5` |
| `LOW_SPOOL_GRAMS` | Spools with less than this many grams left are marked low | `100` |
| `ZIP_MAX_UNCOMPRESSED_MB` | Most data a single zip upload may unpack to | `1000` |
| `MAX_UPLOAD_MB` | Largest upload (one save or one dropped file), in MB | `200` |

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Notes

- There's no login rate limiting. It's meant for a home network; if you expose it to the internet, put it behind HTTPS and a reverse proxy (and consider extra protection such as a VPN).
- Uploads are STL, 3MF, PNG, JPG, GIF, WebP or ZIP (zips are unpacked and each file inside is checked), checked by content as well as extension. Uploaded files live in the data folder next to the database, so include it in backups (it grows with your models).
- Behind a reverse proxy, allow large request bodies (nginx: `client_max_body_size 200m;`), or uploads of big STL files will be refused.
- Very detailed models (hundreds of thousands of triangles) can be slow to preview on a phone. Files over 30 MB aren't opened automatically; use "View in 3D".
- The viewer and the 3D preview pictures need WebGL. Without it you still get downloads, and items without a photo show a plain placeholder. Models over 30 MB don't get an automatic preview picture.
- The first folder-tree view of a large inventory is only as heavy as its thumbnails, which are loaded lazily as you scroll.
- Photos from before this version were converted automatically on first start.
- All times are stored in UTC and shown in `APP_TIMEZONE`.
