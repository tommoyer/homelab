# timew-webhook

A minimal Flask service that exposes `/start`, `/stop`, `/status`, and `/health` endpoints to control Timewarrior. It runs inside a container that has the Timewarrior CLI installed and writes directly to the mounted `.timewarrior` directory so reports stay in sync across your devices.

## Endpoints
- `POST|GET /start?tags=<tags>` – starts a timer with sanitized tags (space- or comma-separated; same syntax as Taskwarrior/Timewarrior).
- `POST|GET /stop` – stops the active timer.
- `GET /status` – shows the current Timewarrior status (falls back to `timew summary :day` if plain `timew` fails).
- `GET /health` – liveness probe.

Auth: supply `Authorization: Bearer <TOKEN>` (preferred) or `?token=<TOKEN>` when `TOKEN` is set. If `TOKEN` is empty, the service is open (not recommended).

## Local build & test (Docker Compose)
```bash
cd tw-sync/timew-webhook
cp .env.example .env
# Edit TOKEN, TIMEW_HOME, PUID, PGID, PORT as needed
docker compose build
docker compose up -d
```

The compose file maps `${PORT:-9000}` on the host to `8000` in the container and bind-mounts `${TIMEW_HOME}/.timewarrior` to `/var/lib/timew/.timewarrior`.

## Swarm deployment
- Ensure a node holds the Syncthing-backed folder, e.g. `/srv/sync/timewarrior/.timewarrior`, and label it `timew.data=true`.
- Copy `.env.example` to `.env` and set `TOKEN`.
- Build/push the image (see GitHub Actions below) or `docker build -t ghcr.io/<owner>/tw-sync-timew-webhook:latest .`.
- Deploy:
```bash
docker stack deploy -c stack.swarm.yml timew
```

Notes:
- Port `9000` is published in host mode; TLS/ingress is expected to be handled by your Caddy proxy (add labels if desired).
- The service runs as `${PUID:-0}:${PGID:-0}`; adjust ownership of `/srv/sync/timewarrior/.timewarrior` accordingly.

## GitHub Actions build (GHCR)
`.github/workflows/timew-webhook.yml` builds and pushes `ghcr.io/<owner>/tw-sync-timew-webhook` when changes land on the default branch (and can be run via workflow_dispatch). It uses buildx with caching and tags `latest` on the default branch plus ref/sha tags for traceability.
