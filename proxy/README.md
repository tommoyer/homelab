## Custom Caddy with Cloudflare DNS

Builds a Caddy image with the Cloudflare DNS plugin so DNS-01 challenges work inside the LXC/Docker setup.

### Setup
- Set required env vars (export or `.env` in `proxy/`): `CLOUDFLARE_API_TOKEN`, `ACME_EMAIL`.
- Update `proxy/Caddyfile` with your domain and upstream (`reverse_proxy` target).

### Build and run
```bash
cd proxy
docker compose up --build -d
```

### Files
- `proxy/Dockerfile` – builds Caddy via `xcaddy` with `caddy-dns/cloudflare`.
- `proxy/docker-compose.yml` – runs Caddy, mounts config/data, forwards 80/443.
- `proxy/Caddyfile` – site and TLS config using Cloudflare DNS solver.
