# Shop Coin

Shop Coin is a Django loyalty and local shopping application with public landing and authentication pages, shopkeeper and customer areas, product catalogues, bills, wallets, coin rules, and redemption history.

## Run locally

From the project directory, use the project virtual environment:

```powershell
venv\Scripts\python.exe manage.py migrate
venv\Scripts\python.exe manage.py runserver
```

Install dependencies in that environment with `venv\Scripts\python.exe -m pip install -r requirements.txt` when setting up a new machine.

Optional environment settings are `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_DB_PATH`, `DATABASE_URL`, `DB_CONN_MAX_AGE`, and `DJANGO_MEDIA_ROOT`. Copy `.env.example` to `.env` for local configuration. If `DATABASE_URL` is set to a PostgreSQL URL, Django connects to PostgreSQL; otherwise local development keeps using SQLite. Do not commit `.env` or expose its database credentials. When `DEBUG=true`, Django serves local uploaded media from `MEDIA_URL` (`/media/` by default).

## Deploy on Render

The app uses SQLite by default, or PostgreSQL when `DATABASE_URL` is configured. For Neon, set `DATABASE_URL` in the Render service to the pooled connection string from the correct Neon project/branch. Keep the direct/unpooled URL in `DATABASE_URL_UNPOOLED` only if an administrative script needs it; Django uses the pooled URL for normal app traffic. The database URL is a password-bearing secret: set it in Render's private environment settings, not in source control. The PostgreSQL driver is installed from `requirements.txt`, and production PostgreSQL connections require SSL. Without `DATABASE_URL`, Render continues to use SQLite; a persistent disk is needed for that fallback, and Render Free does not provide one.

- `DJANGO_SECRET_KEY`: generate a private, strong value in Render.
- `DJANGO_DEBUG`: `false`.
- `DATABASE_URL`: pooled Neon PostgreSQL connection URL (recommended for the live service).
- `DATABASE_URL_UNPOOLED`: optional direct Neon URL for one-off administration; not read by Django's default database setting.
- `DJANGO_DB_PATH`: `/var/data/db.sqlite3` only if you intentionally keep the SQLite fallback.
- `DJANGO_ALLOWED_HOSTS`: optional when using the Render-provided hostname; set your hostnames if using a custom domain.
- `DJANGO_CSRF_TRUSTED_ORIGINS`: optional comma-separated HTTPS origins for custom domains.

Uploaded images are user media, not static files. WhiteNoise serves static assets; it does not store uploads. Local development uses `MEDIA_ROOT` and `/media/`. Render Free storage is ephemeral, so without R2 the app logs a clear warning and uses temporary local media; uploaded images may disappear after a restart or redeploy. This fallback is not permanent storage.

Cloudflare R2 is the configured provider target. Create an R2 bucket, an S3 API token with object read/write access, and attach a public custom domain to the bucket. On Render, add these variables privately (never put secret values in source control):

- `AWS_STORAGE_BUCKET_NAME`: R2 bucket name.
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`: R2 S3 token credentials.
- `AWS_S3_ENDPOINT_URL`: `https://<account-id>.r2.cloudflarestorage.com`.
- `AWS_S3_CUSTOM_DOMAIN`: custom-domain hostname only, without `https://`.
- `AWS_S3_REGION_NAME`: defaults to `auto`.
- `AWS_QUERYSTRING_AUTH`: defaults to `false` so image URLs do not expire.

When the complete R2 configuration is present, production uses R2. When it is absent or incomplete, Django starts with filesystem media and logs that uploads are temporary, along with missing setting names for partial configuration. Local development continues using SQLite (unless `DATABASE_URL` is set) and local filesystem media when `DJANGO_DEBUG=true` and no R2 values are supplied. Database settings and existing media paths are unchanged. Before switching an environment with local files, configure the target storage and run `python manage.py sync_media_to_object_storage`; the command skips existing objects, copies matching paths, and keeps local copies. Files already lost from an ephemeral Render instance cannot be recovered by this command and must be restored from a local/backup copy.

Use `bash build.sh` as the build command and `bash start.sh` as the start command. The build script installs requirements and collects static files. It skips migrations on Render because the persistent disk is unavailable during the build; the start script applies migrations after the service disk is mounted, then starts `config.wsgi:application` with Gunicorn. Run a single web-service instance because a disk-backed SQLite database cannot be shared across multiple instances. The local default remains `db.sqlite3` in the project directory.

## Main routes

- `/` public Shop Coin landing page
- `/login/` shopkeeper login
- `/customer/login/` customer mobile-number login
- `/register/shopkeeper/` shopkeeper registration
- `/customer/` customer dashboard
- `/customer/shop/`, `/customer/wallet/`, `/customer/coin-rules/`, and `/customer/history/`
- `/shopkeeper/` shopkeeper dashboard
- `/shopkeeper/products/`, `/shopkeeper/customers/`, `/shopkeeper/bills/`, and `/shopkeeper/coin-rules/`
- `/admin/` Django administration

Customer accounts are created by shopkeepers and are connected to that shop. Shopkeeper pages and customer records are scoped to the authenticated shop. Django administrators manage shops and application records.

## Coin and bill behavior

Each ₹100 of a bill's final amount after discount earns one coin; fractional coins are rounded down. The current value of all active coins is selected by the customer's current coin balance:

- 0–99 coins: ₹10 per coin
- 100–499 coins: ₹12 per coin
- 500 or more coins: ₹15 per coin

Bills retain their issue-time coin-value snapshot. Shopkeepers can redeem a customer's full active balance after recording the reward provided; the wallet ledger and redemption history are retained. Product stock no longer gates or changes billing. The legacy database stock column remains in place to preserve existing records, but it is hidden from product forms and unused by bill creation.

## Checks and tests

```powershell
venv\Scripts\python.exe manage.py check
venv\Scripts\python.exe manage.py makemigrations --check --dry-run
venv\Scripts\python.exe manage.py test
```

## Fictional demo data

In local development (`DJANGO_DEBUG=true`), create the fictional demo store, products, ad/offer, demo shopkeeper, and connected demo customers with:

```powershell
venv\Scripts\python.exe manage.py seed_demo_data --password "DemoOnly!ChangeMe2026"
```

The command refuses to run when debug is disabled and is safe to rerun. Demo images are generated locally and saved through the configured media storage backend.
