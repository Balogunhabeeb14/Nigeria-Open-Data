# Putting Naija Open Data on the internet

This is the small set-up: one server, two commands. It is enough for a pilot
and for a catalogue of a few thousand datasets.

## What you need

- **A server** with Docker: any Linux virtual machine with 2 GB of memory and
  20 GB of disk. Providers charge roughly £5 to £10 a month for this size.
- **A domain name** (or a subdomain) whose DNS `A` record points at the
  server's address.
- Ports **80** and **443** open on the server.

## Start it

```bash
git clone https://github.com/Balogunhabeeb14/Nigeria-Open-Data.git
cd Nigeria-Open-Data

cat > .env <<'ENV'
SITE_ADDRESS=data.example.org        # your domain
APP_PUBLISH=127.0.0.1:3000                   # the site is reached only through HTTPS
PIPELINE_DB_PASSWORD=<a long random password>
CONTACT_EMAIL=<an address you read>
ENV

docker compose -f docker-compose.lite.yml -f docker-compose.prod.yml up --build -d
```

Open `https://data.example.org`. The certificate is obtained automatically on
the first request; allow a minute.

The catalogue fills itself: featured indicators within a minute, listings from
other portals straight after, then the rest of the World Bank catalogue. The
**Data status** page (`/status`) shows progress.

## Keep it healthy

| Task | Command |
|---|---|
| See what the loader is doing | `docker compose -f docker-compose.lite.yml logs -f app` |
| Update to the latest code | `git pull && docker compose -f docker-compose.lite.yml -f docker-compose.prod.yml up --build -d` |
| Back up the database | `docker compose -f docker-compose.lite.yml exec -T db pg_dump -U pipeline pipeline \| gzip > backup-$(date +%F).sql.gz` |
| Restore a backup | `gunzip -c backup.sql.gz \| docker compose -f docker-compose.lite.yml exec -T db psql -U pipeline pipeline` |
| Check the sources still answer | `python scripts/verify_live.py` (or the *Live check* workflow on GitHub) |

Back up at least weekly and copy the file off the server. Everything on the
site can be rebuilt from the sources, but a backup is quicker and keeps
anything you loaded by hand.

## What is and is not exposed

- Only the website is reachable from outside. It serves the read-only data
  API (`/api/3/action/...`) and CSV downloads itself.
- The pipeline API with its admin endpoints is **not** reachable from outside,
  and its admin endpoints stay switched off unless you set `ADMIN_API_TOKEN`.
- The database is not published on any port.

## When this set-up stops being enough

Move to the full stack (`docker-compose.yml`, with CKAN) when you need
organisations to sign in and publish their own data, or CKAN's extensions.
The website and pipeline do not change; see "Two ways to run the catalogue"
in the README.
