# Shop Coin

Shop Coin is a Django loyalty and local shopping application with public landing and authentication pages, shopkeeper and customer areas, product catalogues, bills, wallets, coin rules, and redemption history.

## Run locally

From the project directory, use the project virtual environment:

```powershell
venv\Scripts\python.exe manage.py migrate
venv\Scripts\python.exe manage.py runserver
```

Install dependencies in that environment with `venv\Scripts\python.exe -m pip install -r requirements.txt` when setting up a new machine.

Optional environment settings are `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, and `DJANGO_ALLOWED_HOSTS`. Before deployment, set a strong secret key, disable debug, and configure allowed hosts and the persistent SQLite location.

## Deploy on Render

This project keeps SQLite. In Render, create a persistent disk mounted at `/var/data`; without a persistent disk, SQLite data and uploaded media are lost when the service is redeployed. Set these environment variables in the Render service:

- `DJANGO_SECRET_KEY`: generate a private, strong value in Render.
- `DJANGO_DEBUG`: `false`.
- `DJANGO_DB_PATH`: `/var/data/db.sqlite3`.
- `DJANGO_MEDIA_ROOT`: `/var/data/media`.
- `DJANGO_ALLOWED_HOSTS`: optional when using the Render-provided hostname; set your hostnames if using a custom domain.
- `DJANGO_CSRF_TRUSTED_ORIGINS`: optional comma-separated HTTPS origins for custom domains.

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

The command refuses to run when debug is disabled and is safe to rerun. Demo images are generated locally and saved under `media/`.
