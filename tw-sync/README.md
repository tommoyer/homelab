# Taskchampion + Timewarrior Sync Servers

This deploys the Taskwarrior Taskchampion sync server and the Timewarrior sync
server on Docker with Caddy handling TLS and routing.

## Requirements

- A Docker host reachable by your clients.
- Public DNS names for both services.
- Ports 80 and 443 open to the Docker host (Caddy uses these for TLS).

## Configuration

1. Copy `env.example` to `.env` and edit values:

   - `TASKCHAMPION_SYNC_SERVER_HOSTNAME`: DNS name for Taskwarrior sync.
   - `TASKCHAMPION_SYNC_SERVER_CLIENT_ID`: Optional allowlist; omit or leave
     empty to accept any client ID.
   - `TIMEW_SYNC_SERVER_HOSTNAME`: DNS name for Timewarrior sync.

2. Ensure DNS points at your Docker host and ports 80/443 are reachable.

## Deploy

From this directory:

```sh
docker compose up -d --build
```

Or with Taskfile:

```sh
task deploy
```

## Taskwarrior client configuration

Add these to each client’s `~/.taskrc` (or set via `task config`):

```ini
sync.server.url=https://taskchampion.example.com
sync.server.client_id=your-client-id
sync.encryption_secret=your-encryption-secret
```

Notes:
- `sync.server.client_id` must match `TASKCHAMPION_SYNC_SERVER_CLIENT_ID` if you
  set it on the server.
- Keep the same `sync.encryption_secret` on all clients for the same task data.

## Timewarrior client configuration

The Timewarrior sync client is `timewsync`.

1. Generate keys on the client:

```sh
timewsync generate-key
```

2. Create a user on the server and note the returned user ID:

```sh
docker compose exec timew-sync server add-user --keys-location /data/authorized_keys
```

3. Upload the client public key and associate it with the user:

```sh
docker compose cp ~/.timewsync/public_key.pem timew-sync:/public_key.pem

docker compose exec timew-sync server add-key \
  --path /public_key.pem \
  --id <user-id> \
  --keys-location /data/authorized_keys
```

4. Configure the client in `~/.timewsync/timewsync.conf`:

```ini
[Server]
BaseURL = https://timew.example.com

[Client]
UserID = <user-id>
```

## Data storage

All data is stored in Docker volumes:

- `taskchampion_data`: Taskchampion sync SQLite data.
- `timew_sync_data`: Timewarrior sync SQLite DB and authorized keys.
- `caddy_data` and `caddy_config`: TLS certificates and Caddy config.
