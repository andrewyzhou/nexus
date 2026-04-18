# Deploying Nexus to `ipick.ai/nexus`

This is the playbook for putting Nexus behind the existing iPick nginx on their
EC2 box. It assumes you have **SSH access** to the box, **sudo**, and the
right to modify `/etc/nginx/sites-available/iseefin`.

**Nothing here lives in the iPick repo.** The client's Flask app at
`stock.ipick.ai` is untouched — we run as a sibling process behind the same
nginx, mounted at `/nexus/*`.

---

## Target architecture

```
ipick.ai EC2
├── nginx (existing, TLS via certbot)
│    ├── stock.ipick.ai ─────────► their existing gunicorn (webapp:app :5000)
│    └── ipick.ai/nexus/* ───────► our new gunicorn (wsgi:app :5001)
│         └── ipick.ai/nexus/api/  → proxied to Flask
│         └── ipick.ai/nexus/      → served from /home/ubuntu/nexus/frontend/
│
├── docker: postgres:16 on :5433 (our DB, separate from their SQLite)
└── systemd: nexus.service → gunicorn
```

---

## Prerequisites on the box (once per host)

```bash
# Docker (for our Postgres)
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin

# Python 3.9+ and venv tools (probably already there)
sudo apt-get install -y python3-venv python3-pip

# Log + runtime directories referenced by nexus.service
sudo mkdir -p /var/log/nexus /run/nexus
sudo chown ubuntu:ubuntu /var/log/nexus /run/nexus
```

---

## First deploy

```bash
# 1. clone
sudo -u ubuntu git clone https://github.com/andrewyzhou/nexus.git /home/ubuntu/nexus
cd /home/ubuntu/nexus

# 2. virtualenv
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt -r scraper/requirements.txt gunicorn

# 3. drop in the env file and fill it in
cp deploy/.env.example .env
nano .env     # set DATABASE_URL, NEXUS_CORS_ORIGINS=https://ipick.ai

# 4. drop in the ticker_track.json (client-private, gitignored)
#    either download manually from S3 or let seed_prod.py fetch it if
#    AWS creds are configured in .env
scp ticker_track.json ubuntu@ipick.ai:/home/ubuntu/nexus/

# 5. Postgres in Docker
docker compose -f backend/docker-compose.yml up -d
# wait ~5s for the container to be ready

# 6. schema + seed
.venv/bin/python backend/db/init.py
.venv/bin/python backend/db/seed_prod.py
# (takes ~60s for the full 4300-ticker universe)

# 7. systemd
sudo cp deploy/nexus.service /etc/systemd/system/nexus.service
sudo systemctl daemon-reload
sudo systemctl enable --now nexus
sudo systemctl status nexus     # should be 'active (running)'
journalctl -u nexus -f          # tail the logs

# 8. nightly reseed cron (optional but recommended)
sudo cp deploy/nexus-seed.cron /etc/cron.d/nexus-seed

# 9. nginx
# Edit /etc/nginx/sites-available/iseefin and paste the contents of
# deploy/nginx-nexus.conf INSIDE the existing server { } block that serves
# ipick.ai (usually the one with listen 443 + server_name ipick.ai).
sudo nano /etc/nginx/sites-available/iseefin
sudo nginx -t
sudo systemctl reload nginx
```

---

## Smoke test

```bash
# Backend directly (should hit gunicorn on 127.0.0.1)
curl -s http://127.0.0.1:5001/nexus/api/graph | head -c 200

# Through nginx
curl -s https://ipick.ai/nexus/api/graph | python3 -m json.tool | head -20
curl -s https://ipick.ai/nexus/api/tracks | python3 -m json.tool | head -10

# Frontend
open https://ipick.ai/nexus/
```

You should see the graph load with `Source: live` in the source badge (if
still present) and the sidebar populated from the real DB.

---

## Updating after new commits land

```bash
cd /home/ubuntu/nexus
git pull origin main
source .venv/bin/activate
pip install -r backend/requirements.txt      # only if requirements changed
sudo systemctl restart nexus                  # ~1s downtime
```

For schema changes, run `python backend/db/init.py` first (it's idempotent).

---

## Rolling back

Everything is a systemd service + an nginx location block:

```bash
# stop serving /nexus traffic without touching the iPick app
sudo systemctl stop nexus
# OR remove the nginx location block and reload nginx
```

The iPick app at `stock.ipick.ai` is unaffected by either action.

---

## Upgrade paths (do these later, not on day 1)

| When | Do |
|---|---|
| Team grows or prod traffic matters | Move Postgres off Docker → AWS RDS (db.t4g.micro ~$15/mo) |
| Multiple Nexus instances needed | Replace systemd with ECS Fargate task, put ALB in front |
| Frontend latency matters | Move `frontend/` to S3 + CloudFront, drop the nginx `location /nexus/` alias |
| Secrets management gets messy | Move `.env` → AWS Secrets Manager, fetch in `ExecStartPre` |
| Want zero-downtime deploys | Run two `nexus@1.service` / `nexus@2.service` behind nginx upstream with health checks |

---

## Related config files in this directory

| File | What it is |
|---|---|
| [nginx-nexus.conf](./nginx-nexus.conf) | location blocks to paste into `/etc/nginx/sites-available/iseefin` |
| [nexus.service](./nexus.service) | systemd unit for the gunicorn process |
| [nexus-seed.cron](./nexus-seed.cron) | `/etc/cron.d/nexus-seed` for nightly re-seed |
| [.env.example](./.env.example) | template for `/home/ubuntu/nexus/.env` |
