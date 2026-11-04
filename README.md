# Shop Coin

Shop Coin is a Django loyalty and local shopping application with public landing and authentication pages, shopkeeper and customer areas, product catalogues, bills, wallets, coin rules, and redemption history.

## Run locally

From the project directory, use the project virtual environment:

```powershell
venv\Scripts\python.exe manage.py migrate
venv\Scripts\python.exe manage.py runserver
```

Install dependencies in that environment with `venv\Scripts\python.exe -m pip install -r requirements.txt` when setting up a new machine.

Optional environment settings are `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_DB_PATH`, and `DJANGO_MEDIA_ROOT`. Local development uses SQLite and filesystem uploads by default. When `DEBUG=true`, Django serves local uploaded media from `MEDIA_URL` (`/media/` by default).

## Deploy on Render

This project keeps SQLite. In Render, create a persistent disk mounted at `/var/data` for the database; without it, database changes are lost when the service is redeployed. Render Free does not provide a persistent disk, so SQLite data on the free filesystem is temporary. Set these environment variables in the Render service:

- `DJANGO_SECRET_KEY`: generate a private, strong value in Render.
- `DJANGO_DEBUG`: `false`.
- `DJANGO_DB_PATH`: `/var/data/db.sqlite3`.
- `DJANGO_ALLOWED_HOSTS`: optional when using the Render-provided hostname; set your hostnames if using a custom domain.
- `DJANGO_CSRF_TRUSTED_ORIGINS`: optional comma-separated HTTPS origins for custom domains.

Uploaded images are user media, not static files. WhiteNoise serves static assets; it does not serve uploads. Production with `DEBUG=false` does not expose the local `/media/` directory. Render Free's filesystem is ephemeral, so locally stored shop logos, product images, banners, and profile photos can disappear after a redeploy or restart. The UI shows local placeholder images when a file is missing, but placeholders cannot recover uploaded files.

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

Bills retain their issue-time coin-value snapshot. Shopkeepers can redeem a customer's full active balance after recording the reward provided; the wallet ledger and redemption history are retained. Catalog stock is reduced atomically when catalog products are included in bills.

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
