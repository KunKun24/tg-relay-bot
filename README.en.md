# tg-relay-bot · Modular Edition 2.0.0

**English** · [中文](README.md)

Telegram main platform and clone support workbench. It keeps the existing SQLite data and uses the official Bot API to run the main bot and every clone tenant in a single supervised process; no web service is required.

## Docs

- [Main bot guide](docs/主机器人使用说明.md): creation, hosting, ownership, tokens, billing, and platform administration.
- [Clone guide](docs/克隆使用说明.md): customer routing, multiple support agents, welcome messages, auto-replies, keyboards, filters, groups, and broadcasts.
- [Features and fixes](docs/功能与修复说明.md): module layout and the behavior changes in this release.
- [Deployment and maintenance](docs/部署与维护.md): environment, service, health checks, backups, migration, and rollback boundaries.
- [Upgrade acceptance report](docs/升级验收报告.md): data retention, 232 regression checks, real Telegram receipts, and the areas left untested.

## Running

Python 3.12 and a project-local virtual environment. Install `requirements.txt`, then create a private `.env` from `.env.example`, read by the service account.

```bash
.venv/bin/python -m relayapp.runtime
```

The compatibility entry point `relay_bot.py` only calls that module; importing it does not start the bot. Production deployments use `tg-relay.service`; do not start a second polling process by hand.

```bash
systemctl status tg-relay.service
runuser -u www -- .venv/bin/python scripts/health.py
runuser -u www -- .venv/bin/python scripts/backup.py
```

## Docker

```bash
cp .env.example .env      # set MAIN_BOT_TOKEN, MAIN_ADMIN_ID, etc.
docker compose up -d --build
```

- The session database lives in the `data` volume (`/data/relay_bot.db`), so recreating the container keeps it
- The bot uses long polling, so no ports need publishing
- Multi-arch image (`linux/amd64`, `linux/arm64`): `ghcr.io/kunkun24/tg-relay-bot`


## Testing

```bash
runuser -u www -- env PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 \
  MAIN_BOT_TOKEN=OFFLINE_TEST MAIN_ADMIN_ID=123456789 \
  RELAY_DB_PATH=/tmp/relay-tests-unused.sqlite3 \
  .venv/bin/python -m pytest -p no:cacheprovider -q
```

Tests use a temporary SQLite database and a fake network; they do not read the production token and do not message customers. For real admin DM diagnostics, see the deployment guide; the target must be specified explicitly and confirmed.

## Delivery scope

The source delivery does not include `.env`, bot tokens, the customer database, backups of old code, the virtual environment, logs, or DM acceptance receipts. Historical data and private backups kept by an actual upgrade stay on the server only. Any clone whose token Telegram rejects must be given a valid token for the same bot by its owner; a software upgrade cannot replace invalid credentials.

---

## About AIGC

> This project contains AIGC (AI-generated) content. AI shortened development time; every line of code was carefully reviewed.
