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

Uploaded images are user media, not static files. WhiteNoise serves static assets; it does not serve uploads. When local filesystem media is selected, Django serves its `/media/` URLs in both debug and production mode so uploaded images can load. Render Free's filesystem is still ephemeral, so these local uploads can disappear after a redeploy or restart. The UI shows placeholders when a file is missing, but placeholders cannot recover uploaded files.

For persistent uploads on Render Free, configure an S3 bucket or S3-compatible object store. This project switches media uploads to `django-storages` S3 storage only when the bucket name, `AWS_ACCESS_KEY_ID`, and `AWS_SECRET_ACCESS_KEY` are all set. If those credentials are absent, local media storage remains active. Add these Render environment variables and provide an existing bucket plus an IAM/API identity with the required object permissions:

- `AWS_STORAGE_BUCKET_NAME`: bucket name.
- `AWS_S3_REGION_NAME`: bucket region.
- `AWS_S3_ENDPOINT_URL`: optional endpoint for an S3-compatible provider.
- `AWS_S3_CUSTOM_DOMAIN`: optional CDN or bucket domain used for media URLs.
- `AWS_S3_ADDRESSING_STYLE`: optional provider setting, commonly `path` when required.
- `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`: set privately in Render, never in source control.

The bucket can remain private; Django generates signed media URLs by default. `AWS_S3_REGION_NAME` is recommended and `AWS_S3_ENDPOINT_URL` is used for compatible providers. Without all three required storage variables, media stays on local disk and is not durable or served in production. Existing local uploads must be copied to the bucket using their stored relative paths before enabling the bucket, or those database references will point to objects that are not present yet.

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
