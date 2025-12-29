Date : 2025-12-27 19h50

# Prompt 1

> **I am looking at using taskwarrior and timewarrior to track my tasks and time spent. I would like to also be able to access that data and use it from my phone (running iOS). I am fine with self-hosting a web application if that makes sense. Define a workflow and what needs installed and set up. Ask clarifying questions before proposing a workflow for task and time tracking**

## ChatGPT GPT-5-THINKING :

Awesome—happy to help! Before I sketch a workflow, a few quick choices will keep us from yak-shaving later. Pick whatever’s easiest to answer:

Platform & install

1. Where will you primarily use the CLI? (Ubuntu/Debian, Fedora, macOS, WSL, other)

2. Do you prefer native packages or containers (Docker/Podman/LXC) for servers and web UIs?

3. Are you starting fresh, or do you already have Taskwarrior/Timewarrior data to migrate?

Sync & mobile

1. For Taskwarrior sync, are you open to the modern Taskchampion sync server (officially documented and easy to self-host), or do you want the classic taskd server? [Taskwarrior](https://taskwarrior.org/docs/sync/?utm_source=chatgpt.com)

2. On iPhone, would you use a native app? There’s Taskchamp (iOS) with two-way sync via Taskchampion or iCloud—is that acceptable? [Apple](https://apps.apple.com/us/app/taskchamp-tasks-for-devs/id6633442700)

3. For Timewarrior on iPhone, do you want to (a) just view reports, (b) start/stop timers from the phone, or (c) both?

4. If you want start/stop from iPhone, are you okay using iOS Shortcuts that hit a tiny webhook/SSH on your server to run timew start/stop? (There’s also a community Timewarrior sync server; it’s not “official”—is community software OK for you?) [GitHub](https://github.com/timewarrior-synchronize/timew-sync-server)

Web access / self-host

1. Do you want a web UI for tasks, time, or both? (e.g., Taskwarrior web UIs exist and can be self-hosted with Docker; we can wire one up.) [GitHub](https://github.com/DCsunset/taskwarrior-webui?utm_source=chatgpt.com)

2. Hosting preference: homelab vs. VPS? Do you already have reverse proxy + TLS (Caddy/Traefik/Nginx) and a domain?

Task ↔ time integration

1. Do you want Timewarrior to auto-start/stop when you task start/stop a task (via the official on-modify.timewarrior hook)? [Timewarrior+1](https://timewarrior.net/docs/taskwarrior/?utm_source=chatgpt.com)

2. How do you want time tagged—mirror project/tags from Taskwarrior, or keep a separate tag taxonomy for Timewarrior?

Reporting & exports

1. What reports do you need? (Weekly timesheets, per-project totals, CSV/JSON exports, invoices, dashboards.)

2. Any calendar integration needs (e.g., export to ICS or view totals per day/week)?

Security & multi-user

1. Single user only, or will others use it too?

2. Any specific auth requirements (OIDC/SSO, 2FA) for the web bits?

Backups & ops

1. Okay to version the Taskwarrior/Timewarrior data dirs in git (periodic commits) plus off-box backups?

2. Any constraints around storing data on iCloud (if chosen) vs. only on self-hosted infrastructure?

Once I have these, I’ll propose a concrete, end-to-end setup (CLI, sync, mobile, web UI, reports, backups) with exact install steps and a day-one workflow tailored to your answers.


---

# Prompt 2

> **1. The primary CLI will be my Arch Linux install**
> **2. For servers and web UIs I prefer Docker as I deploy services to a Swarm cluster**
> **3. I have data in another task manager but will manually import that later**
> **4. I would prefer Taskchampion**
> **5. Taskchamp is fine but a web application would also work if there is missing functionality**
> **6. Both**
> **7. Yes**
> **8. Both**
> **9. I have a homelab already set up with Docker Swarm, a reverse proxy, and TLS**
> **10. Yes**
> **11. Use the same tags**
> **12. Weekly reports, per-project reports, and dashboards**
> **13. No**
> **14. Single user**
> **15. No, since this is single-user I will connect via my TailScale Tailnet**
> **16. Yes**
> **17. Only use self-hosted services since I cannot easily access iCloud from my laptop running Linux. I do have Syncthing set up if that helps**

## ChatGPT GPT-5-THINKING :

awesome — thanks for the details! here’s a concrete, self-hosted workflow that fits your stack (Arch + Docker Swarm + Tailscale), uses Taskchampion for sync, Taskchamp on iOS, and keeps Taskwarrior/Timewarrior as your CLI “source of truth.”

Overview (what you’ll run where)

- Arch laptop (primary CLI)

Taskwarrior 3.x (with Taskchampion sync enabled)

- Timewarrior

- Taskwarrior → Timewarrior integration via the on-modify.timewarrior hook (so task start/stop = time starts/stops) [Timewarrior](https://timewarrior.net/docs/taskwarrior/)

- A tiny webhook runner container to trigger timew start/stop remotely from iOS Shortcuts over your Tailscale tailnet (no cloud)

Swarm cluster (server-side)

- Taskchampion Sync Server (SQLite backend is fine for single-user) behind your existing reverse proxy/TLS (or reachable only on Tailnet) [Gothenburg Bit Factory](https://gothenburgbitfactory.org/taskchampion-sync-server/)

- (Optional) Taskwarrior Web UI container that reads your Taskwarrior data (v3) — handy for quick browsing on phone/desktop browser [GitHub](https://github.com/DCsunset/taskwarrior-webui)

iOS

- Taskchamp app (Taskwarrior-compatible, supports Taskchampion sync server) for full task capture/edits on the phone

- iOS Shortcuts that hit your webhook endpoints to start/stop timers or tag them

Step 1 — Arch install & wire-up

1. Install

```bash
sudo pacman -S task timew
```

1. Enable Taskchampion syncing in Taskwarrior

- Pick a client_id (UUID is fine) and a secret you’ll reuse on iOS.

```bash
task config sync.server.url http://tasksync.tailnet:8080
task config sync.server.client_id  <YOUR_CLIENT_ID>
task config sync.encryption_secret <YOUR_LONG_RANDOM_SECRET>
```

Those keys (sync.server.url, sync.server.client_id, sync.encryption_secret) are Taskwarrior 3’s Taskchampion settings. You can confirm they’re set with task show and the Arch task-sync(5) man page spells them out.

1. Make Taskwarrior start/stop Timewarrior automatically

- Copy the packaged hook into your Taskwarrior hooks dir and make it executable:

```bash
# Path on Arch:
cp /usr/share/doc/timew/ext/on-modify.timewarrior ~/.task/hooks/
chmod +x ~/.task/hooks/on-modify.timewarrior
task diagnostics   # should list on-modify.timewarrior as Active
```

This hook starts Timewarrior when a task is started and stops it when the task is stopped / done. It passes description, project, and tags through as Timewarrior tags, which matches your “reuse the same tags” requirement. [Timewarrior+1](https://timewarrior.net/docs/taskwarrior/)

Quick test:
task add "Spike: API gateway" +clientA project:infra → task start → task stop → timew summary :day

Step 2 — Deploy the Taskchampion Sync Server on Swarm

Use the official sync server (SQLite storage). Example stack file:

```yaml
# stack: taskchampion.yml
version: "3.9"
services:
  tc-sync:
    image: ghcr.io/gothenburgbitfactory/taskchampion-sync-server:sqlite-v0.7.0
    environment:
      - LISTEN=0.0.0.0:8080
      - DATA_DIR=/data
    volumes:
      - tc_data:/data
    networks:
      - proxy
    deploy:
      restart_policy:
        condition: on-failure
      labels:
        # If you want it via your reverse proxy (Traefik example):
        - traefik.enable=true
        - traefik.http.routers.tc.rule=Host(`tasksync.example.internal`)
        - traefik.http.services.tc.loadbalancer.server.port=8080
        - traefik.http.routers.tc.tls=true
volumes:
  tc_data:
networks:
  proxy:
    external: true
```

Deploy:

```bash
docker stack deploy -c taskchampion.yml taskchamp
```

The server exposes a simple HTTP endpoint and stores encrypted blobs; it does not know your tasks (the encryption secret never leaves your devices). The README and docs show docker run/env vars (LISTEN, DATA_DIR, optional CLIENT_ID) and overall behavior. [GitHub+2GitHub+2](https://github.com/GothenburgBitFactory/taskchampion-sync-server)

On your Arch laptop, set sync.server.url to the Tailnet URL or your reverse-proxied name (already done in Step 1).

Step 3 — iOS Task app (Taskchamp)

- Install Taskchamp from the App Store. In Settings → Sync, choose Taskchampion Sync Server, point it at your Tailnet/HTTPS URL, and enter the same client_id and encryption_secret you set on Arch. That makes iOS and Arch one logical “replica” of the same user’s data.

Step 4 — Remote start/stop of Timewarrior from iOS

You wanted to start/stop timers from the phone. Since Timewarrior has no built-in sync, the cleanest single-writer approach is to run the timers on the Arch box (your canonical CLI), and trigger those commands remotely over Tailnet.

1. Run a tiny webhook runner on Arch that executes local scripts:

```bash
docker run -d --name=tw-webhook \
  --network host \
  -v $HOME/webhooks:/etc/webhook \
  -v $HOME/webhooks/scripts:/scripts \
  almir/webhook -verbose -hooks=/etc/webhook/hooks.json -hotreload
```

The almir/webhook image runs shell scripts on HTTP hits; perfect for timew wrappers. [Docker Hub](https://hub.docker.com/r/almir/webhook/?utm_source=chatgpt.com)

1. Create ~/webhooks/hooks.json:

```json
[
  {
    "id": "timew-start",
    "execute-command": "/scripts/timew-start.sh",
    "command-working-directory": "/scripts",
    "pass-arguments-to-command": [
      { "source": "url", "name": "tags" }
    ],
    "incoming-payload-content-type": "application/json"
  },
  {
    "id": "timew-stop",
    "execute-command": "/scripts/timew-stop.sh",
    "command-working-directory": "/scripts"
  }
]
```

1. Create scripts in ~/webhooks/scripts/:

```bash
# timew-start.sh
#!/usr/bin/env bash
set -euo pipefail
# Basic sanitization: only allow alnum, dash, underscore, comma, colon, plus, space
TAGS=$(echo "${1:-}" | tr -cd '[:alnum:]-_,:+ ')
if [ -z "$TAGS" ]; then
  echo "No tags"; exit 1
fi
/usr/bin/timew start $TAGS

# timew-stop.sh
#!/usr/bin/env bash
set -euo pipefail
/usr/bin/timew stop
```

```bash
chmod +x ~/webhooks/scripts/timew-*.sh
```

1. iOS Shortcuts:

- Create “Start timer” → “Get Text” (e.g., project:infra +clientA +coding) → “Get Contents of URL” to:

```bash
https://arch-host.tailnet:9000/hooks/timew-start?tags=project:infra,+clientA,+coding
```

- Create “Stop timer” → “Get Contents of URL”:

```bash
https://arch-host.tailnet:9000/hooks/timew-stop
```

(Use your Tailnet hostname. Optionally protect webhook behind basic auth via your reverse proxy, but your Tailnet alone may be enough for single-user.)

Result: Taskwarrior and Timewarrior data remain on Arch as the single writer; you can still browse/report from anywhere.

Step 5 — Optional web UIs
A) Task web UI (Taskwarrior v3)

Run taskwarrior-webui (the v3 image) wherever you can mount your .task and .taskrc (e.g., on Arch or a node that receives those files via Syncthing/NFS):

```bash
docker run -d --name twui -p 8080:80 \
  -v $HOME/.taskrc:/.taskrc \
  -v $HOME/.task:/.task \
  dcsunset/taskwarrior-webui:3
```

It’s a self-hosted UI; you can put it behind your proxy/TLS or expose only on Tailnet. [GitHub](https://github.com/DCsunset/taskwarrior-webui)

B) Time dashboards / reports

Timewarrior has solid built-in reports (timew summary :week, timew summary project:infra :month). For dashboarding, you can export structured JSON and visualize it in whatever you like (Metabase, Grafana, etc.):

```bash
timew export :week > /var/timew/weekly.json
```

The timew export format is documented (IDs, start/end, tags, annotations), so it’s straightforward to ETL into SQLite/CSV for a dashboard. [Timewarrior](https://timewarrior.net/reference/timew-export.1/?utm_source=chatgpt.com)

Tip: You can also leave it purely CLI — timew summary, timew week, timew month — and it’ll cover weekly and per-project slices nicely. [Timewarrior](https://timewarrior.net/docs/?utm_source=chatgpt.com)

Migration notes (later)

- When you’re ready, you can bulk-import tasks with task import <export.json>. (Taskwarrior v3 still supports the export/import JSON flow; see task export docs.) [Taskwarrior](https://taskwarrior.org/docs/commands/export/?utm_source=chatgpt.com)

Why this fits your answers

- Primary CLI on Arch: all day-to-day task/timew lives local.

- Docker/Swarm: the only “server” is the Taskchampion sync server on Swarm; everything else can be containerized too.

- Taskchampion preferred: both Taskwarrior v3 and Taskchamp iOS sync to your Taskchampion server.

- Same tags: hook forwards Taskwarrior description/project/tags to Timewarrior. [Timewarrior](https://timewarrior.net/docs/taskwarrior/)

- iOS access: Taskchamp app for tasks, and Shortcuts + webhook for time start/stop.

- Self-host only: all components run on your gear; access via Tailnet.

Sanity checklist (do these in order)

1. sudo pacman -S task timew

2. Configure Taskwarrior sync (Step 1.2) and enable the Timewarrior hook (Step 1.3).

3. Deploy the Taskchampion Sync Server stack on Swarm (Step 2) and task sync from Arch to confirm. [GitHub](https://github.com/GothenburgBitFactory/taskchampion-sync-server)

4. Install Taskchamp on iOS and point it to the same server, client_id, secret.

5. Start the webhook container on Arch; test your iOS Shortcuts to start/stop timers.

6. (Optional) Run the Taskwarrior Web UI container and/or an ETL → dashboard for Timewarrior. [GitHub+1](https://github.com/DCsunset/taskwarrior-webui)

If you want, I can also drop in a ready-to-use Swarm stack file for the webhook runner and a couple of example iOS Shortcut JSON exports.


---

# Prompt 3

> **Create the stack file and example shortcuts**

## ChatGPT GPT-5-THINKING :

sweet — here are copy-pasteables for you.

Taskchampion sync server (Swarm stack)

Save as taskchampion-stack.yml and deploy with:

```bash
docker stack deploy -c taskchampion-stack.yml taskchamp
```

```yaml
# taskchampion-stack.yml
version: "3.9"
# This runs the official Taskchampion sync server (SQLite backend).
# Docs list image names, env vars (LISTEN, DATA_DIR, CLIENT_ID, CREATE_CLIENTS), and ports. :contentReference[oaicite:0]{index=0}
services:
  tc-sync:
    image: ghcr.io/gothenburgbitfactory/taskchampion-sync-server:latest
    environment:
      # Listen on all interfaces inside the overlay network
      - LISTEN=0.0.0.0:8080
      # Where to store encrypted sync data inside the container
      - DATA_DIR=/var/lib/taskchampion-sync-server/data
      # OPTIONAL: restrict to one client_id (use the SAME value on Arch + iOS)
      # - CLIENT_ID=${TASKCHAMP_CLIENT_ID}
      # OPTIONAL: disable auto-creating clients if you want to pre-provision
      # - CREATE_CLIENTS=true
      # OPTIONAL: RUST_LOG=info|debug for more logs
      - RUST_LOG=info
    volumes:
      - tc_data:/var/lib/taskchampion-sync-server/data
    networks:
      - proxy
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
      labels:
        # --- If you front this with Traefik (example) ---
        # - traefik.enable=true
        # - traefik.http.routers.tc-sync.rule=Host(`tasksync.example.internal`)
        # - traefik.http.routers.tc-sync.entrypoints=websecure
        # - traefik.http.routers.tc-sync.tls=true
        # - traefik.http.services.tc-sync.loadbalancer.server.port=8080
        # -----------------------------------------------
volumes:
  tc_data:
networks:
  proxy:
    external: true
```

Then on Arch (Taskwarrior 3.x):

```bash
task config sync.server.url https://tasksync.example.internal
task config sync.server.client_id  <YOUR_CLIENT_ID>      # same one you'll use on iOS
task config sync.encryption_secret <YOUR_LONG_RANDOM_SECRET>
```

In Taskchamp on iOS, set the same server URL, client_id, and encryption secret. (Those keys and image names/vars are straight from the upstream docs.) [gothenburgbitfactory.org](https://gothenburgbitfactory.org/taskchampion-sync-server/usage/docker-images.html)

iOS Shortcuts (SSH method – simplest & robust)

This avoids container quirks and runs timew directly on your Arch box via the built-in “Run Script over SSH” action in Shortcuts. (Keep the Timewarrior on-modify hook enabled so starting/stopping a Taskwarrior task from Arch also controls timers. Hook reference: it’s part of Timewarrior.) [timewarrior.net](https://timewarrior.net/docs/taskwarrior/?utm_source=chatgpt.com)

Prereqs (once)

- Ensure your Arch box is reachable on your Tailnet and has SSH enabled (public-key auth recommended).

- On iOS Shortcuts: Settings → Advanced → allow running scripts if prompted.

- In each SSH action below, fill Host, User, and Authentication (paste your private key, or use password if you must).

Shortcut 1 — “Timew Start”

What it does: asks you for tags, then runs timew start <tags> on Arch.

Build it like this in Shortcuts:

1. Action: Ask for Input → Prompt: Tags / project (e.g. project:infra +clientA +coding) → Input Type: Text

2. Action: Run Script Over SSH

Host: arch-host.tailnet (or your Tailnet DNS/IP)

3. User: tom (example)

4. Script:

```bash
#!/usr/bin/env bash
set -euo pipefail
# $SHORTCUT_INPUT contains the text from "Ask for Input"
TAGS="${SHORTCUT_INPUT:-}"
if [ -z "$TAGS" ]; then
  echo "No tags provided"; exit 1
fi
# Ensure Timewarrior is on PATH for non-interactive shells
export PATH="/usr/local/bin:/usr/bin:/bin"
timew start $TAGS
echo "Started: $TAGS"
```

5. (Optional) Action: Show Result → Result (so you see confirmation on the phone)

You can also hard-code favorite variants by duplicating this shortcut and replacing step 1 with a Text action:

```makefile
project:infra +clientA +coding
```

…and keep the same SSH action.

Shortcut 2 — “Timew Stop”

What it does: stops the active timer.

1. Action: Run Script Over SSH

Host/User as above

2. Script:

```bash
#!/usr/bin/env bash
set -euo pipefail
export PATH="/usr/local/bin:/usr/bin:/bin"
timew stop || true
echo "Stopped (if running)"
```

3. Action: Show Result → Result (optional)

(Optional) “Task-linked” habit

If you prefer drive-by timing from iPhone and want matching tags to your Taskwarrior taxonomy, just supply the same strings you’d use in Taskwarrior: project:<proj> +tag1 +tag2. Timewarrior will record those exactly as tags, which keeps your reporting aligned.

Optional: Taskwarrior Web UI container (reads your .task)

If you choose to mirror your .task dir (e.g., via Syncthing) to a Swarm node, you can run the v3 web UI container:

```yaml
# taskwarrior-webui-stack.yml (optional)
version: "3.9"
services:
  twui:
    image: dcsunset/taskwarrior-webui:3
    volumes:
      - /srv/tw/.taskrc:/.taskrc:ro      # point these at the mirrored paths
      - /srv/tw/.task:/.task:ro
    networks:
      - proxy
    deploy:
      labels:
        # Traefik example
        - traefik.enable=true
        - traefik.http.routers.twui.rule=Host(`tasks.example.internal`)
        - traefik.http.routers.twui.entrypoints=websecure
        - traefik.http.routers.twui.tls=true
        - traefik.http.services.twui.loadbalancer.server.port=80
networks:
  proxy:
    external: true
```

(That image/tag and run arguments are from the project’s README; the :3 tag is specifically for Taskwarrior v3 data.) [GitHub](https://github.com/DCsunset/taskwarrior-webui?utm_source=chatgpt.com)

Quick test checklist

- docker stack ls shows taskchamp.

- curl -sS https://tasksync.example.internal/health (or just hit the base URL) returns a 200 from the sync server (or check container logs). Image/env names as documented. [gothenburgbitfactory.org](https://gothenburgbitfactory.org/taskchampion-sync-server/usage/docker-images.html)

- On Arch:

task sync (should succeed)

- task add "Spike: API gateway" project:infra +clientA

- task start → confirm Timewarrior hook runs (see timew summary :day). [timewarrior.net](https://timewarrior.net/docs/taskwarrior/?utm_source=chatgpt.com)

On iPhone:

- Open Taskchamp, run Sync; tasks appear.

- Run Timew Start shortcut with something like project:infra +clientA +coding, do work, then Timew Stop.

- Back on Arch, timew summary :week shows the phone-triggered interval.

If you want the webhook flavor later, I can also give you a tiny Go/Flask Dockerfile that includes timew and binds your ~/.timewarrior into the container so HTTP hits start/stop timers safely.


---

# Prompt 4

> **Create the necessary files to support the webhook flavor**

## ChatGPT GPT-5-THINKING :

awesome — here’s a tiny, self-hosted webhook → Timewarrior service you can run on your Arch box. it exposes /start?tags=…, /stop, /status, and /health, and writes directly to your existing ~/.timewarrior so your CLI reports stay in one place.

folder layout

```graphql
timew-webhook/
  ├─ Dockerfile
  ├─ app.py
  ├─ requirements.txt
  ├─ entrypoint.sh
  ├─ .env.example
  ├─ compose.yaml          # run on your Arch box (recommended)
  └─ stack.swarm.yml       # optional: if you really want it on Swarm
```

1) files
Dockerfile
```dockerfile
# timew-webhook/Dockerfile
FROM python:3.12-slim
# Install Timewarrior (from Debian repos) + basics
RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  timewarrior ca-certificates tzdata bash \
  && rm -rf /var/lib/apt/lists/*
# App deps
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# App
COPY app.py entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh
# Timewarrior data home inside the container
RUN mkdir -p /var/lib/timew
ENV HOME=/var/lib/timew
EXPOSE 8000
CMD ["/app/entrypoint.sh"]
```

requirements.txt
```text
flask==3.0.3
gunicorn==22.0.0
```

entrypoint.sh
```bash
#!/usr/bin/env bash
set -euo pipefail
# Gunicorn binds to 0.0.0.0:8000 and serves app:app
exec gunicorn --workers=2 --threads=4 --timeout=30 \
  --bind 0.0.0.0:8000 app:app
```

app.py
```python
# timew-webhook/app.py
import os, re, shlex, subprocess
from flask import Flask, request, jsonify, abort
app = Flask(__name__)
TOKEN = os.environ.get("TOKEN", "")  # set in .env / compose
TIMEW_BIN = os.environ.get("TIMEW_BIN", "timew")
# we run with HOME=/var/lib/timew in Dockerfile; .timewarrior lives there
ALLOWED = re.compile(r"^[A-Za-z0-9:_+\-, ]{1,200}$")
def _auth_or_401():
    if not TOKEN:
        return  # no token set = open (not recommended)
    h = request.headers.get("Authorization", "")
    if h.startswith("Bearer "):
        if h.split(" ", 1)[1] == TOKEN:
            return
    # fallback: token query param (handy for iOS Shortcuts)
    if request.args.get("token") == TOKEN:
        return
    abort(401)
def _run(cmd):
    """Run a command and return (rc, out)."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()
def _tags_list_from_request():
    # accept JSON {"tags":"project:infra +clientA +coding"} or query ?tags=...
    tags = ""
    if request.is_json:
        tags = (request.get_json(silent=True) or {}).get("tags", "") or ""
    tags = request.args.get("tags", tags)
    tags = (tags or "").strip()
    if not tags:
        abort(400, description="missing 'tags'")
    # sanitize (allow only safe characters)
    if not ALLOWED.fullmatch(tags):
        abort(400, description="invalid characters in tags")
    # support comma- or space-separated; shlex for spacing
    tags = tags.replace(",", " ")
    parts = [p for p in shlex.split(tags) if p]
    if not parts:
        abort(400, description="no valid tags after parsing")
    return parts
@app.route("/start", methods=["GET", "POST"])
def start():
    _auth_or_401()
    tags = _tags_list_from_request()
    rc, out = _run([TIMEW_BIN, "start", *tags])
    return jsonify({"ok": rc == 0, "cmd": ["timew","start",*tags], "out": out}), (200 if rc == 0 else 500)
@app.route("/stop", methods=["GET", "POST"])
def stop():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, "stop"])
    return jsonify({"ok": True, "cmd": ["timew","stop"], "out": out}), 200
@app.route("/status", methods=["GET"])
def status():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, ""])
    # Fallback to `timew summary :day` for brevity if plain call fails
    if rc != 0:
        rc, out = _run([TIMEW_BIN, "summary", ":day"])
    return jsonify({"ok": rc == 0, "out": out}), 200
@app.route("/health", methods=["GET"])
def health():
    return "ok", 200
```

.env.example
```dotenv
# copy to .env and edit
TOKEN=change-me-to-a-long-random-string
# Where your host Timewarrior data lives (no trailing slash)
TIMEW_HOME=/home/tom
# Run container with same UID/GID so it doesn’t chown your files
PUID=1000
PGID=1000
# Port to expose on host
PORT=9000
```

compose.yaml  (recommended: run this on your Arch box)
```yaml
# timew-webhook/compose.yaml
version: "3.9"
services:
  timew-webhook:
    build:
      context: .
      dockerfile: Dockerfile
    image: local/timew-webhook:latest
    env_file: .env
    environment:
      # ensure HOME points to /var/lib/timew (already set in Dockerfile)
      - TOKEN=${TOKEN}
    ports:
      - "${PORT:-9000}:8000"
    user: "${PUID:-1000}:${PGID:-1000}"
    volumes:
      # mount host Timewarrior data so CLI and webhook share the SAME dataset
      - "${TIMEW_HOME}/.timewarrior:/var/lib/timew/.timewarrior"
    restart: unless-stopped
```

stack.swarm.yml  (optional: only if you truly want it on Swarm)

Use this only if you have your ~/.timewarrior mirrored to a Swarm node (e.g., via Syncthing to /srv/timew) and you’ve built/pushed the image to a registry (update image:).

```yaml
# timew-webhook/stack.swarm.yml
version: "3.9"
services:
  timew-webhook:
    image: registry.example.com/you/timew-webhook:latest
    environment:
      - TOKEN=${TOKEN}
    volumes:
      - /srv/timew/.timewarrior:/var/lib/timew/.timewarrior
    ports:
      - target: 8000
        published: 9000
        protocol: tcp
        mode: host
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
      # Optional Traefik labels if you want TLS on LAN/Tailnet
      # labels:
      #   - traefik.enable=true
      #   - traefik.http.routers.timew.rule=Host(`timew.example.internal`)
      #   - traefik.http.routers.timew.entrypoints=websecure
      #   - traefik.http.routers.timew.tls=true
      #   - traefik.http.services.timew.loadbalancer.server.port=8000
```

2) build & run (compose on Arch)
```bash
cd timew-webhook
cp .env.example .env
# edit .env: TOKEN, TIMEW_HOME, PUID, PGID, PORT
docker compose build
docker compose up -d
docker compose logs -f
```

First run will create /var/lib/timew/.timewarrior inside the container (backed by your host ~/.timewarrior).
From your iPhone (on Tailnet or over your reverse proxy), try:

```bash
# Start a timer with mirrored Taskwarrior-style taxonomy
curl -sS "https://arch-host.tailnet:9000/start?tags=project:infra,+clientA,+coding&token=YOURTOKEN"
# Stop it
curl -sS "https://arch-host.tailnet:9000/stop?token=YOURTOKEN"
# Health
curl -sS "https://arch-host.tailnet:9000/health"
```

3) iOS Shortcuts (webhook flavor)
No files needed—just two shortcuts that hit your endpoints:

Start timer (webhook)

- Action: “Text” → project:infra +clientA +coding (or use “Ask for Input” if you prefer)

- Action: “Get Contents of URL”

URL: https://arch-host.tailnet:9000/start

- Method: GET (or POST)

- Query: tags = (Provided Input or Text), token = YOURTOKEN

(Optional) Action: “Show Result” → Result

Stop timer (webhook)

- Action: “Get Contents of URL”

URL: https://arch-host.tailnet:9000/stop?token=YOURTOKEN

(Optional) “Show Result”

notes & tips

- Security: It’s already gated by your Tailnet; the extra TOKEN is just defense-in-depth. Prefer the Authorization: Bearer <token> header in production (Shortcuts supports headers).

- Same tags: pass the same strings you’d use in Taskwarrior (project:foo +tag1 +tag2)—the service doesn’t mutate them.

- One dataset: Because we bind-mount ~/.timewarrior, your CLI (timew ...) and webhook writes are in lockstep. Keep concurrent starts/stops sensible to avoid interleaving.

- Taskwarrior hook: leave your on-modify.timewarrior hook enabled; this webhook is just an extra remote control for Timewarrior.

If you want, I can also add a /start-task?uuid=<task-uuid> endpoint that looks up a Taskwarrior task (via a mirrored .task export on the cluster) and auto-applies its project/+tags to the timer—handy when you drive everything from tasks.


---

# Prompt 5

> **Yes and make sure the deployment instructions host everything on the Swarm cluster where I will also have Syncthing running to sync data if necessary**


---

# Prompt 6

> **Yes and make sure the deployment instructions host everything on the Swarm cluster where I will also have Syncthing running to sync data if necessary**


---

# Prompt 7

> **Yes and move the webhook related things to the swarm cluster. My Arch install will not always be available since it is a laptop but the Swarm cluster will always be available. The cluster also has Syncthing deployed if that can help with syncing between phone and laptop**

## ChatGPT GPT-5-THINKING :

Perfect—let’s run everything on the Swarm cluster and use Syncthing to mirror your Timewarrior data to your laptop so you can report locally even when the laptop is offline.

Below is a ready-to-use setup:

- A Taskchampion sync server service (for Taskwarrior/Taskchamp).

- A timew-webhook service (containerized Timewarrior + HTTP endpoints /start, /stop, etc.).

- Mounts Timewarrior’s data at a Syncthing folder on one Swarm node; your laptop’s Syncthing maps that to ~/.timewarrior.

0) One-time Swarm prep

1. Pick a data node (the one that already runs Syncthing) and label it so the timew service pins there:

```bash
docker node update --label-add timew.data=true <NODE_NAME>
```

1. Create the Syncthing-backed folder on that node (adjust the path if you already have one):

```bash
sudo mkdir -p /srv/sync/timewarrior/.timewarrior
sudo chown 0:0 /srv/sync/timewarrior/.timewarrior
sudo chmod 700 /srv/sync/timewarrior/.timewarrior
```

Add /srv/sync/timewarrior as a Syncthing folder on that node and share it to your Arch laptop, mapping it on the laptop to ~/.timewarrior. (On the laptop, ensure ~/.timewarrior is owned by your user after the first sync.)

1. Create a secret for the webhook token (defense-in-depth; you’ll also be on Tailnet or behind your proxy):

```bash
openssl rand -hex 32 | docker secret create timew_webhook_token -
```

1. (Optional) Reserve a DNS name for each service via your reverse proxy/TLS (e.g., tasksync.example.internal, timew.example.internal). Otherwise, hit them via Tailnet IP:port.

1) Build & push the timew-webhook image

On any machine with Docker:

```bash
git init timew-webhook && cd timew-webhook
```

Dockerfile
```dockerfile
FROM python:3.12-slim
RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  timewarrior ca-certificates tzdata bash \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh
# Timewarrior data home inside the container
RUN mkdir -p /var/lib/timew
ENV HOME=/var/lib/timew
EXPOSE 8000
CMD ["/app/entrypoint.sh"]
```

requirements.txt
```text
flask==3.0.3
gunicorn==22.0.0
```

entrypoint.sh
```bash
#!/usr/bin/env bash
set -euo pipefail
# Gunicorn binds to 0.0.0.0:8000 and serves app:app
exec gunicorn --workers=2 --threads=4 --timeout=30 \
  --bind 0.0.0.0:8000 app:app
```

app.py
```python
# timew-webhook/app.py
import os, re, shlex, subprocess
from flask import Flask, request, jsonify, abort
app = Flask(__name__)
TOKEN = os.environ.get("TOKEN", "")  # set in .env / compose
TIMEW_BIN = os.environ.get("TIMEW_BIN", "timew")
# we run with HOME=/var/lib/timew in Dockerfile; .timewarrior lives there
ALLOWED = re.compile(r"^[A-Za-z0-9:_+\-, ]{1,200}$")
def _auth_or_401():
    if not TOKEN:
        return  # no token set = open (not recommended)
    h = request.headers.get("Authorization", "")
    if h.startswith("Bearer "):
        if h.split(" ", 1)[1] == TOKEN:
            return
    # fallback: token query param (handy for iOS Shortcuts)
    if request.args.get("token") == TOKEN:
        return
    abort(401)
def _run(cmd):
    """Run a command and return (rc, out)."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()
def _tags_list_from_request():
    # accept JSON {"tags":"project:infra +clientA +coding"} or query ?tags=...
    tags = ""
    if request.is_json:
        tags = (request.get_json(silent=True) or {}).get("tags", "") or ""
    tags = request.args.get("tags", tags)
    tags = (tags or "").strip()
    if not tags:
        abort(400, description="missing 'tags'")
    # sanitize (allow only safe characters)
    if not ALLOWED.fullmatch(tags):
        abort(400, description="invalid characters in tags")
    # support comma- or space-separated; shlex for spacing
    tags = tags.replace(",", " ")
    parts = [p for p in shlex.split(tags) if p]
    if not parts:
        abort(400, description="no valid tags after parsing")
    return parts
@app.route("/start", methods=["GET", "POST"])
def start():
    _auth_or_401()
    tags = _tags_list_from_request()
    rc, out = _run([TIMEW_BIN, "start", *tags])
    return jsonify({"ok": rc == 0, "cmd": ["timew","start",*tags], "out": out}), (200 if rc == 0 else 500)
@app.route("/stop", methods=["GET", "POST"])
def stop():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, "stop"])
    return jsonify({"ok": True, "cmd": ["timew","stop"], "out": out}), 200
@app.route("/status", methods=["GET"])
def status():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, ""])
    # Fallback to `timew summary :day` for brevity if plain call fails
    if rc != 0:
        rc, out = _run([TIMEW_BIN, "summary", ":day"])
    return jsonify({"ok": rc == 0, "out": out}), 200
@app.route("/health", methods=["GET"])
def health():
    return "ok", 200
```

.env.example
```dotenv
# copy to .env and edit
TOKEN=change-me-to-a-long-random-string
# Where your host Timewarrior data lives (no trailing slash)
TIMEW_HOME=/home/tom
# Run container with same UID/GID so it doesn’t chown your files
PUID=1000
PGID=1000
# Port to expose on host
PORT=9000
```

compose.yaml  (recommended: run this on your Arch box)
```yaml
# timew-webhook/compose.yaml
version: "3.9"
services:
  timew-webhook:
    build:
      context: .
      dockerfile: Dockerfile
    image: local/timew-webhook:latest
    env_file: .env
    environment:
      # ensure HOME points to /var/lib/timew (already set in Dockerfile)
      - TOKEN=${TOKEN}
    ports:
      - "${PORT:-9000}:8000"
    user: "${PUID:-1000}:${PGID:-1000}"
    volumes:
      # mount host Timewarrior data so CLI and webhook share the SAME dataset
      - "${TIMEW_HOME}/.timewarrior:/var/lib/timew/.timewarrior"
    restart: unless-stopped
```

stack.swarm.yml  (optional: only if you truly want it on Swarm)

Use this only if you have your ~/.timewarrior mirrored to a Swarm node (e.g., via Syncthing to /srv/timew) and you’ve built/pushed the image to a registry (update image:).

```yaml
# timew-webhook/stack.swarm.yml
version: "3.9"
services:
  timew-webhook:
    image: registry.example.com/you/timew-webhook:latest
    environment:
      - TOKEN=${TOKEN}
    volumes:
      - /srv/timew/.timewarrior:/var/lib/timew/.timewarrior
    ports:
      - target: 8000
        published: 9000
        protocol: tcp
        mode: host
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
      # Optional Traefik labels if you want TLS on LAN/Tailnet
      # labels:
      #   - traefik.enable=true
      #   - traefik.http.routers.timew.rule=Host(`timew.example.internal`)
      #   - traefik.http.routers.timew.entrypoints=websecure
      #   - traefik.http.routers.timew.tls=true
      #   - traefik.http.services.timew.loadbalancer.server.port=8000
```

2) build & run (compose on Arch)
```bash
cd timew-webhook
cp .env.example .env
# edit .env: TOKEN, TIMEW_HOME, PUID, PGID, PORT
docker compose build
docker compose up -d
docker compose logs -f
```

First run will create /var/lib/timew/.timewarrior inside the container (backed by your host ~/.timewarrior).
From your iPhone (on Tailnet or over your reverse proxy), try:

```bash
# Start a timer with mirrored Taskwarrior-style taxonomy
curl -sS "https://arch-host.tailnet:9000/start?tags=project:infra,+clientA,+coding&token=YOURTOKEN"
# Stop it
curl -sS "https://arch-host.tailnet:9000/stop?token=YOURTOKEN"
# Health
curl -sS "https://arch-host.tailnet:9000/health"
```

3) iOS Shortcuts (webhook flavor)
No files needed—just two shortcuts that hit your endpoints:

Start timer (webhook)

- Action: “Text” → project:infra +clientA +coding (or use “Ask for Input” if you prefer)

- Action: “Get Contents of URL”

URL: https://arch-host.tailnet:9000/start

- Method: GET (or POST)

- Query: tags = (Provided Input or Text), token = YOURTOKEN

(Optional) Action: “Show Result” → Result

Stop timer (webhook)

- Action: “Get Contents of URL”

URL: https://arch-host.tailnet:9000/stop?token=YOURTOKEN

(Optional) “Show Result”

notes & tips

- Security: It’s already gated by your Tailnet; the extra TOKEN is just defense-in-depth. Prefer the Authorization: Bearer <token> header in production (Shortcuts supports headers).

- Same tags: pass the same strings you’d use in Taskwarrior (project:foo +tag1 +tag2)—the service doesn’t mutate them.

- One dataset: Because we bind-mount ~/.timewarrior, your CLI (timew ...) and webhook writes are in lockstep. Keep concurrent starts/stops sensible to avoid interleaving.

- Taskwarrior hook: leave your on-modify.timewarrior hook enabled; this webhook is just an extra remote control for Timewarrior.

If you want, I can also add a /start-task?uuid=<task-uuid> endpoint that looks up a Taskwarrior task (via a mirrored .task export on the cluster) and auto-applies its project/+tags to the timer—handy when you drive everything from tasks.


---

# Prompt 5

> **Yes and make sure the deployment instructions host everything on the Swarm cluster where I will also have Syncthing running to sync data if necessary**


---

# Prompt 6

> **Yes and make sure the deployment instructions host everything on the Swarm cluster where I will also have Syncthing running to sync data if necessary**


---

# Prompt 7

> **Yes and move the webhook related things to the swarm cluster. My Arch install will not always be available since it is a laptop but the Swarm cluster will always be available. The cluster also has Syncthing deployed if that can help with syncing between phone and laptop**

## ChatGPT GPT-5-THINKING :

Perfect—let’s run everything on the Swarm cluster and use Syncthing to mirror your Timewarrior data to your laptop so you can report locally even when the laptop is offline.

Below is a ready-to-use setup:

- A Taskchampion sync server service (for Taskwarrior/Taskchamp).

- A timew-webhook service (containerized Timewarrior + HTTP endpoints /start, /stop, etc.).

- Mounts Timewarrior’s data at a Syncthing folder on one Swarm node; your laptop’s Syncthing maps that to ~/.timewarrior.

0) One-time Swarm prep

1. Pick a data node (the one that already runs Syncthing) and label it so the timew service pins there:

```bash
docker node update --label-add timew.data=true <NODE_NAME>
```

1. Create the Syncthing-backed folder on that node (adjust the path if you already have one):

```bash
sudo mkdir -p /srv/sync/timewarrior/.timewarrior
sudo chown 0:0 /srv/sync/timewarrior/.timewarrior
sudo chmod 700 /srv/sync/timewarrior/.timewarrior
```

Add /srv/sync/timewarrior as a Syncthing folder on that node and share it to your Arch laptop, mapping it on the laptop to ~/.timewarrior. (On the laptop, ensure ~/.timewarrior is owned by your user after the first sync.)

1. Create a secret for the webhook token (defense-in-depth; you’ll also be on Tailnet or behind your proxy):

```bash
openssl rand -hex 32 | docker secret create timew_webhook_token -
```

1. (Optional) Reserve a DNS name for each service via your reverse proxy/TLS (e.g., tasksync.example.internal, timew.example.internal). Otherwise, hit them via Tailnet IP:port.

1) Build & push the timew-webhook image

On any machine with Docker:

```bash
git init timew-webhook && cd timew-webhook
```

Dockerfile
```dockerfile
FROM python:3.12-slim
RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  timewarrior ca-certificates tzdata bash \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh
# Timewarrior data home inside the container
RUN mkdir -p /var/lib/timew
ENV HOME=/var/lib/timew
EXPOSE 8000
CMD ["/app/entrypoint.sh"]
```

requirements.txt
```text
flask==3.0.3
gunicorn==22.0.0
```

entrypoint.sh
```bash
#!/usr/bin/env bash
set -euo pipefail
# Gunicorn binds to 0.0.0.0:8000 and serves app:app
exec gunicorn --workers=2 --threads=4 --timeout=30 \
  --bind 0.0.0.0:8000 app:app
```

app.py
```python
# timew-webhook/app.py
import os, re, shlex, subprocess
from flask import Flask, request, jsonify, abort
app = Flask(__name__)
TOKEN = os.environ.get("TOKEN", "")  # set in .env / compose
TIMEW_BIN = os.environ.get("TIMEW_BIN", "timew")
# we run with HOME=/var/lib/timew in Dockerfile; .timewarrior lives there
ALLOWED = re.compile(r"^[A-Za-z0-9:_+\-, ]{1,200}$")
def _auth_or_401():
    if not TOKEN:
        return  # no token set = open (not recommended)
    h = request.headers.get("Authorization", "")
    if h.startswith("Bearer "):
        if h.split(" ", 1)[1] == TOKEN:
            return
    # fallback: token query param (handy for iOS Shortcuts)
    if request.args.get("token") == TOKEN:
        return
    abort(401)
def _run(cmd):
    """Run a command and return (rc, out)."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()
def _tags_list_from_request():
    # accept JSON {"tags":"project:infra +clientA +coding"} or query ?tags=...
    tags = ""
    if request.is_json:
        tags = (request.get_json(silent=True) or {}).get("tags", "") or ""
    tags = request.args.get("tags", tags)
    tags = (tags or "").strip()
    if not tags:
        abort(400, description="missing 'tags'")
    # sanitize (allow only safe characters)
    if not ALLOWED.fullmatch(tags):
        abort(400, description="invalid characters in tags")
    # support comma- or space-separated; shlex for spacing
    tags = tags.replace(",", " ")
    parts = [p for p in shlex.split(tags) if p]
    if not parts:
        abort(400, description="no valid tags after parsing")
    return parts
@app.route("/start", methods=["GET", "POST"])
def start():
    _auth_or_401()
    tags = _tags_list_from_request()
    rc, out = _run([TIMEW_BIN, "start", *tags])
    return jsonify({"ok": rc == 0, "cmd": ["timew","start",*tags], "out": out}), (200 if rc == 0 else 500)
@app.route("/stop", methods=["GET", "POST"])
def stop():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, "stop"])
    return jsonify({"ok": True, "cmd": ["timew","stop"], "out": out}), 200
@app.route("/status", methods=["GET"])
def status():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, ""])
    # Fallback to `timew summary :day` for brevity if plain call fails
    if rc != 0:
        rc, out = _run([TIMEW_BIN, "summary", ":day"])
    return jsonify({"ok": rc == 0, "out": out}), 200
@app.route("/health", methods=["GET"])
def health():
    return "ok", 200
```

.env.example
```dotenv
# copy to .env and edit
TOKEN=change-me-to-a-long-random-string
# Where your host Timewarrior data lives (no trailing slash)
TIMEW_HOME=/home/tom
# Run container with same UID/GID so it doesn’t chown your files
PUID=1000
PGID=1000
# Port to expose on host
PORT=9000
```

compose.yaml  (recommended: run this on your Arch box)
```yaml
# timew-webhook/compose.yaml
version: "3.9"
services:
  timew-webhook:
    build:
      context: .
      dockerfile: Dockerfile
    image: local/timew-webhook:latest
    env_file: .env
    environment:
      # ensure HOME points to /var/lib/timew (already set in Dockerfile)
      - TOKEN=${TOKEN}
    ports:
      - "${PORT:-9000}:8000"
    user: "${PUID:-1000}:${PGID:-1000}"
    volumes:
      # mount host Timewarrior data so CLI and webhook share the SAME dataset
      - "${TIMEW_HOME}/.timewarrior:/var/lib/timew/.timewarrior"
    restart: unless-stopped
```

stack.swarm.yml  (optional: only if you truly want it on Swarm)

Use this only if you have your ~/.timewarrior mirrored to a Swarm node (e.g., via Syncthing to /srv/timew) and you’ve built/pushed the image to a registry (update image:).

```yaml
# timew-webhook/stack.swarm.yml
version: "3.9"
services:
  timew-webhook:
    image: registry.example.com/you/timew-webhook:latest
    environment:
      - TOKEN=${TOKEN}
    volumes:
      - /srv/timew/.timewarrior:/var/lib/timew/.timewarrior
    ports:
      - target: 8000
        published: 9000
        protocol: tcp
        mode: host
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
      # Optional Traefik labels if you want TLS on LAN/Tailnet
      # labels:
      #   - traefik.enable=true
      #   - traefik.http.routers.timew.rule=Host(`timew.example.internal`)
      #   - traefik.http.routers.timew.entrypoints=websecure
      #   - traefik.http.routers.timew.tls=true
      #   - traefik.http.services.timew.loadbalancer.server.port=8000
```

2) build & run (compose on Arch)
```bash
cd timew-webhook
cp .env.example .env
# edit .env: TOKEN, TIMEW_HOME, PUID, PGID, PORT
docker compose build
docker compose up -d
docker compose logs -f
```

First run will create /var/lib/timew/.timewarrior inside the container (backed by your host ~/.timewarrior).
From your iPhone (on Tailnet or over your reverse proxy), try:

```bash
# Start a timer with mirrored Taskwarrior-style taxonomy
curl -sS "https://arch-host.tailnet:9000/start?tags=project:infra,+clientA,+coding&token=YOURTOKEN"
# Stop it
curl -sS "https://arch-host.tailnet:9000/stop?token=YOURTOKEN"
# Health
curl -sS "https://arch-host.tailnet:9000/health"
```

3) iOS Shortcuts (webhook flavor)
No files needed—just two shortcuts that hit your endpoints:

Start timer (webhook)

- Action: “Text” → project:infra +clientA +coding (or use “Ask for Input” if you prefer)

- Action: “Get Contents of URL”

URL: https://arch-host.tailnet:9000/start

- Method: GET (or POST)

- Query: tags = (Provided Input or Text), token = YOURTOKEN

(Optional) Action: “Show Result” → Result

Stop timer (webhook)

- Action: “Get Contents of URL”

URL: https://arch-host.tailnet:9000/stop?token=YOURTOKEN

(Optional) “Show Result”

notes & tips

- Security: It’s already gated by your Tailnet; the extra TOKEN is just defense-in-depth. Prefer the Authorization: Bearer <token> header in production (Shortcuts supports headers).

- Same tags: pass the same strings you’d use in Taskwarrior (project:foo +tag1 +tag2)—the service doesn’t mutate them.

- One dataset: Because we bind-mount ~/.timewarrior, your CLI (timew ...) and webhook writes are in lockstep. Keep concurrent starts/stops sensible to avoid interleaving.

- Taskwarrior hook: leave your on-modify.timewarrior hook enabled; this webhook is just an extra remote control for Timewarrior.

If you want, I can also add a /start-task?uuid=<task-uuid> endpoint that looks up a Taskwarrior task (via a mirrored .task export on the cluster) and auto-applies its project/+tags to the timer—handy when you drive everything from tasks.


---

# Prompt 5

> **Yes and make sure the deployment instructions host everything on the Swarm cluster where I will also have Syncthing running to sync data if necessary**


---

# Prompt 6

> **Yes and make sure the deployment instructions host everything on the Swarm cluster where I will also have Syncthing running to sync data if necessary**


---

# Prompt 7

> **Yes and move the webhook related things to the swarm cluster. My Arch install will not always be available since it is a laptop but the Swarm cluster will always be available. The cluster also has Syncthing deployed if that can help with syncing between phone and laptop**

## ChatGPT GPT-5-THINKING :

Perfect—let’s run everything on the Swarm cluster and use Syncthing to mirror your Timewarrior data to your laptop so you can report locally even when the laptop is offline.

Below is a ready-to-use setup:

- A Taskchampion sync server service (for Taskwarrior/Taskchamp).

- A timew-webhook service (containerized Timewarrior + HTTP endpoints /start, /stop, etc.).

- Mounts Timewarrior’s data at a Syncthing folder on one Swarm node; your laptop’s Syncthing maps that to ~/.timewarrior.

0) One-time Swarm prep

1. Pick a data node (the one that already runs Syncthing) and label it so the timew service pins there:

```bash
docker node update --label-add timew.data=true <NODE_NAME>
```

1. Create the Syncthing-backed folder on that node (adjust the path if you already have one):

```bash
sudo mkdir -p /srv/sync/timewarrior/.timewarrior
sudo chown 0:0 /srv/sync/timewarrior/.timewarrior
sudo chmod 700 /srv/sync/timewarrior/.timewarrior
```

Add /srv/sync/timewarrior as a Syncthing folder on that node and share it to your Arch laptop, mapping it on the laptop to ~/.timewarrior. (On the laptop, ensure ~/.timewarrior is owned by your user after the first sync.)

1. Create a secret for the webhook token (defense-in-depth; you’ll also be on Tailnet or behind your proxy):

```bash
openssl rand -hex 32 | docker secret create timew_webhook_token -
```

1. (Optional) Reserve a DNS name for each service via your reverse proxy/TLS (e.g., tasksync.example.internal, timew.example.internal). Otherwise, hit them via Tailnet IP:port.

1) Build & push the timew-webhook image

On any machine with Docker:

```bash
git init timew-webhook && cd timew-webhook
```

Dockerfile
```dockerfile
FROM python:3.12-slim
RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  timewarrior ca-certificates tzdata bash \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh
# Timewarrior data home inside the container
RUN mkdir -p /var/lib/timew
ENV HOME=/var/lib/timew
EXPOSE 8000
CMD ["/app/entrypoint.sh"]
```

requirements.txt
```text
flask==3.0.3
gunicorn==22.0.0
```

entrypoint.sh
```bash
#!/usr/bin/env bash
set -euo pipefail
# Gunicorn binds to 0.0.0.0:8000 and serves app:app
exec gunicorn --workers=2 --threads=4 --timeout=30 \
  --bind 0.0.0.0:8000 app:app
```

app.py
```python
# timew-webhook/app.py
import os, re, shlex, subprocess
from flask import Flask, request, jsonify, abort
app = Flask(__name__)
TOKEN = os.environ.get("TOKEN", "")  # set in .env / compose
TIMEW_BIN = os.environ.get("TIMEW_BIN", "timew")
# we run with HOME=/var/lib/timew in Dockerfile; .timewarrior lives there
ALLOWED = re.compile(r"^[A-Za-z0-9:_+\-, ]{1,200}$")
def _auth_or_401():
    if not TOKEN:
        return  # no token set = open (not recommended)
    h = request.headers.get("Authorization", "")
    if h.startswith("Bearer "):
        if h.split(" ", 1)[1] == TOKEN:
            return
    # fallback: token query param (handy for iOS Shortcuts)
    if request.args.get("token") == TOKEN:
        return
    abort(401)
def _run(cmd):
    """Run a command and return (rc, out)."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()
def _tags_list_from_request():
    # accept JSON {"tags":"project:infra +clientA +coding"} or query ?tags=...
    tags = ""
    if request.is_json:
        tags = (request.get_json(silent=True) or {}).get("tags", "") or ""
    tags = request.args.get("tags", tags)
    tags = (tags or "").strip()
    if not tags:
        abort(400, description="missing 'tags'")
    # sanitize (allow only safe characters)
    if not ALLOWED.fullmatch(tags):
        abort(400, description="invalid characters in tags")
    # support comma- or space-separated; shlex for spacing
    tags = tags.replace(",", " ")
    parts = [p for p in shlex.split(tags) if p]
    if not parts:
        abort(400, description="no valid tags after parsing")
    return parts
@app.route("/start", methods=["GET", "POST"])
def start():
    _auth_or_401()
    tags = _tags_list_from_request()
    rc, out = _run([TIMEW_BIN, "start", *tags])
    return jsonify({"ok": rc == 0, "cmd": ["timew","start",*tags], "out": out}), (200 if rc == 0 else 500)
@app.route("/stop", methods=["GET", "POST"])
def stop():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, "stop"])
    return jsonify({"ok": True, "cmd": ["timew","stop"], "out": out}), 200
@app.route("/status", methods=["GET"])
def status():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, ""])
    # Fallback to `timew summary :day` for brevity if plain call fails
    if rc != 0:
        rc, out = _run([TIMEW_BIN, "summary", ":day"])
    return jsonify({"ok": rc == 0, "out": out}), 200
@app.route("/health", methods=["GET"])
def health():
    return "ok", 200
```

.env.example
```dotenv
# copy to .env and edit
TOKEN=change-me-to-a-long-random-string
# Where your host Timewarrior data lives (no trailing slash)
TIMEW_HOME=/home/tom
# Run container with same UID/GID so it doesn’t chown your files
PUID=1000
PGID=1000
# Port to expose on host
PORT=9000
```

compose.yaml  (recommended: run this on your Arch box)
```yaml
# timew-webhook/compose.yaml
version: "3.9"
services:
  timew-webhook:
    build:
      context: .
      dockerfile: Dockerfile
    image: local/timew-webhook:latest
    env_file: .env
    environment:
      # ensure HOME points to /var/lib/timew (already set in Dockerfile)
      - TOKEN=${TOKEN}
    ports:
      - "${PORT:-9000}:8000"
    user: "${PUID:-1000}:${PGID:-1000}"
    volumes:
      # mount host Timewarrior data so CLI and webhook share the SAME dataset
      - "${TIMEW_HOME}/.timewarrior:/var/lib/timew/.timewarrior"
    restart: unless-stopped
```

stack.swarm.yml  (optional: only if you truly want it on Swarm)

Use this only if you have your ~/.timewarrior mirrored to a Swarm node (e.g., via Syncthing to /srv/timew) and you’ve built/pushed the image to a registry (update image:).

```yaml
# timew-webhook/stack.swarm.yml
version: "3.9"
services:
  timew-webhook:
    image: registry.example.com/you/timew-webhook:latest
    environment:
      - TOKEN=${TOKEN}
    volumes:
      - /srv/timew/.timewarrior:/var/lib/timew/.timewarrior
    ports:
      - target: 8000
        published: 9000
        protocol: tcp
        mode: host
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
      # Optional Traefik labels if you want TLS on LAN/Tailnet
      # labels:
      #   - traefik.enable=true
      #   - traefik.http.routers.timew.rule=Host(`timew.example.internal`)
      #   - traefik.http.routers.timew.entrypoints=websecure
      #   - traefik.http.routers.timew.tls=true
      #   - traefik.http.services.timew.loadbalancer.server.port=8000
```

2) build & run (compose on Arch)
```bash
cd timew-webhook
cp .env.example .env
# edit .env: TOKEN, TIMEW_HOME, PUID, PGID, PORT
docker compose build
docker compose up -d
docker compose logs -f
```

First run will create /var/lib/timew/.timewarrior inside the container (backed by your host ~/.timewarrior).
From your iPhone (on Tailnet or over your reverse proxy), try:

```bash
# Start a timer with mirrored Taskwarrior-style taxonomy
curl -sS "https://arch-host.tailnet:9000/start?tags=project:infra,+clientA,+coding&token=YOURTOKEN"
# Stop it
curl -sS "https://arch-host.tailnet:9000/stop?token=YOURTOKEN"
# Health
curl -sS "https://arch-host.tailnet:9000/health"
```

3) iOS Shortcuts (webhook flavor)
No files needed—just two shortcuts that hit your endpoints:

Start timer (webhook)

- Action: “Text” → project:infra +clientA +coding (or use “Ask for Input” if you prefer)

- Action: “Get Contents of URL”

URL: https://arch-host.tailnet:9000/start

- Method: GET (or POST)

- Query: tags = (Provided Input or Text), token = YOURTOKEN

(Optional) Action: “Show Result” → Result

Stop timer (webhook)

- Action: “Get Contents of URL”

URL: https://arch-host.tailnet:9000/stop?token=YOURTOKEN

(Optional) “Show Result”

notes & tips

- Security: It’s already gated by your Tailnet; the extra TOKEN is just defense-in-depth. Prefer the Authorization: Bearer <token> header in production (Shortcuts supports headers).

- Same tags: pass the same strings you’d use in Taskwarrior (project:foo +tag1 +tag2)—the service doesn’t mutate them.

- One dataset: Because we bind-mount ~/.timewarrior, your CLI (timew ...) and webhook writes are in lockstep. Keep concurrent starts/stops sensible to avoid interleaving.

- Taskwarrior hook: leave your on-modify.timewarrior hook enabled; this webhook is just an extra remote control for Timewarrior.

If you want, I can also add a /start-task?uuid=<task-uuid> endpoint that looks up a Taskwarrior task (via a mirrored .task export on the cluster) and auto-applies its project/+tags to the timer—handy when you drive everything from tasks.


---

# Prompt 5

> **Yes and make sure the deployment instructions host everything on the Swarm cluster where I will also have Syncthing running to sync data if necessary**


---

# Prompt 6

> **Yes and make sure the deployment instructions host everything on the Swarm cluster where I will also have Syncthing running to sync data if necessary**


---

# Prompt 7

> **Yes and move the webhook related things to the swarm cluster. My Arch install will not always be available since it is a laptop but the Swarm cluster will always be available. The cluster also has Syncthing deployed if that can help with syncing between phone and laptop**

## ChatGPT GPT-5-THINKING :

Perfect—let’s run everything on the Swarm cluster and use Syncthing to mirror your Timewarrior data to your laptop so you can report locally even when the laptop is offline.

Below is a ready-to-use setup:

- A Taskchampion sync server service (for Taskwarrior/Taskchamp).

- A timew-webhook service (containerized Timewarrior + HTTP endpoints /start, /stop, etc.).

- Mounts Timewarrior’s data at a Syncthing folder on one Swarm node; your laptop’s Syncthing maps that to ~/.timewarrior.

0) One-time Swarm prep

1. Pick a data node (the one that already runs Syncthing) and label it so the timew service pins there:

```bash
docker node update --label-add timew.data=true <NODE_NAME>
```

1. Create the Syncthing-backed folder on that node (adjust the path if you already have one):

```bash
sudo mkdir -p /srv/sync/timewarrior/.timewarrior
sudo chown 0:0 /srv/sync/timewarrior/.timewarrior
sudo chmod 700 /srv/sync/timewarrior/.timewarrior
```

Add /srv/sync/timewarrior as a Syncthing folder on that node and share it to your Arch laptop, mapping it on the laptop to ~/.timewarrior. (On the laptop, ensure ~/.timewarrior is owned by your user after the first sync.)

1. Create a secret for the webhook token (defense-in-depth; you’ll also be on Tailnet or behind your proxy):

```bash
openssl rand -hex 32 | docker secret create timew_webhook_token -
```

1. (Optional) Reserve a DNS name for each service via your reverse proxy/TLS (e.g., tasksync.example.internal, timew.example.internal). Otherwise, hit them via Tailnet IP:port.

1) Build & push the timew-webhook image

On any machine with Docker:

```bash
git init timew-webhook && cd timew-webhook
```

Dockerfile
```dockerfile
FROM python:3.12-slim
RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  timewarrior ca-certificates tzdata bash \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh
# Timewarrior data home inside the container
RUN mkdir -p /var/lib/timew
ENV HOME=/var/lib/timew
EXPOSE 8000
CMD ["/app/entrypoint.sh"]
```

requirements.txt
```text
flask==3.0.3
gunicorn==22.0.0
```

entrypoint.sh
```bash
#!/usr/bin/env bash
set -euo pipefail
# Gunicorn binds to 0.0.0.0:8000 and serves app:app
exec gunicorn --workers=2 --threads=4 --timeout=30 \
  --bind 0.0.0.0:8000 app:app
```

app.py
```python
# timew-webhook/app.py
import os, re, shlex, subprocess
from flask import Flask, request, jsonify, abort
app = Flask(__name__)
TOKEN = os.environ.get("TOKEN", "")  # set in .env / compose
TIMEW_BIN = os.environ.get("TIMEW_BIN", "timew")
# we run with HOME=/var/lib/timew in Dockerfile; .timewarrior lives there
ALLOWED = re.compile(r"^[A-Za-z0-9:_+\-, ]{1,200}$")
def _auth_or_401():
    if not TOKEN:
        return  # no token set = open (not recommended)
    h = request.headers.get("Authorization", "")
    if h.startswith("Bearer "):
        if h.split(" ", 1)[1] == TOKEN:
            return
    # fallback: token query param (handy for iOS Shortcuts)
    if request.args.get("token") == TOKEN:
        return
    abort(401)
def _run(cmd):
    """Run a command and return (rc, out)."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()
def _tags_list_from_request():
    # accept JSON {"tags":"project:infra +clientA +coding"} or query ?tags=...
    tags = ""
    if request.is_json:
        tags = (request.get_json(silent=True) or {}).get("tags", "") or ""
    tags = request.args.get("tags", tags)
    tags = (tags or "").strip()
    if not tags:
        abort(400, description="missing 'tags'")
    # sanitize (allow only safe characters)
    if not ALLOWED.fullmatch(tags):
        abort(400, description="invalid characters in tags")
    # support comma- or space-separated; shlex for spacing
    tags = tags.replace(",", " ")
    parts = [p for p in shlex.split(tags) if p]
    if not parts:
        abort(400, description="no valid tags after parsing")
    return parts
@app.route("/start", methods=["GET", "POST"])
def start():
    _auth_or_401()
    tags = _tags_list_from_request()
    rc, out = _run([TIMEW_BIN, "start", *tags])
    return jsonify({"ok": rc == 0, "cmd": ["timew","start",*tags], "out": out}), (200 if rc == 0 else 500)
@app.route("/stop", methods=["GET", "POST"])
def stop():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, "stop"])
    return jsonify({"ok": True, "cmd": ["timew","stop"], "out": out}), 200
@app.route("/status", methods=["GET"])
def status():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, ""])
    # Fallback to `timew summary :day` for brevity if plain call fails
    if rc != 0:
        rc, out = _run([TIMEW_BIN, "summary", ":day"])
    return jsonify({"ok": rc == 0, "out": out}), 200
@app.route("/health", methods=["GET"])
def health():
    return "ok", 200
```

.env.example
```dotenv
# copy to .env and edit
TOKEN=change-me-to-a-long-random-string
# Where your host Timewarrior data lives (no trailing slash)
TIMEW_HOME=/home/tom
# Run container with same UID/GID so it doesn’t chown your files
PUID=1000
PGID=1000
# Port to expose on host
PORT=9000
```

compose.yaml  (recommended: run this on your Arch box)
```yaml
# timew-webhook/compose.yaml
version: "3.9"
services:
  timew-webhook:
    build:
      context: .
      dockerfile: Dockerfile
    image: local/timew-webhook:latest
    env_file: .env
    environment:
      # ensure HOME points to /var/lib/timew (already set in Dockerfile)
      - TOKEN=${TOKEN}
    ports:
      - "${PORT:-9000}:8000"
    user: "${PUID:-1000}:${PGID:-1000}"
    volumes:
      # mount host Timewarrior data so CLI and webhook share the SAME dataset
      - "${TIMEW_HOME}/.timewarrior:/var/lib/timew/.timewarrior"
    restart: unless-stopped
```

stack.swarm.yml  (optional: only if you truly want it on Swarm)

Use this only if you have your ~/.timewarrior mirrored to a Swarm node (e.g., via Syncthing to /srv/timew) and you’ve built/pushed the image to a registry (update image:).

```yaml
# timew-webhook/stack.swarm.yml
version: "3.9"
services:
  timew-webhook:
    image: registry.example.com/you/timew-webhook:latest
    environment:
      - TOKEN=${TOKEN}
    volumes:
      - /srv/timew/.timewarrior:/var/lib/timew/.timewarrior
    ports:
      - target: 8000
        published: 9000
        protocol: tcp
        mode: host
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
      # Optional Traefik labels if you want TLS on LAN/Tailnet
      # labels:
      #   - traefik.enable=true
      #   - traefik.http.routers.timew.rule=Host(`timew.example.internal`)
      #   - traefik.http.routers.timew.entrypoints=websecure
      #   - traefik.http.routers.timew.tls=true
      #   - traefik.http.services.timew.loadbalancer.server.port=8000
```

2) build & run (compose on Arch)
```bash
cd timew-webhook
cp .env.example .env
# edit .env: TOKEN, TIMEW_HOME, PUID, PGID, PORT
docker compose build
docker compose up -d
docker compose logs -f
```

First run will create /var/lib/timew/.timewarrior inside the container (backed by your host ~/.timewarrior).
From your iPhone (on Tailnet or over your reverse proxy), try:

```bash
# Start a timer with mirrored Taskwarrior-style taxonomy
curl -sS "https://arch-host.tailnet:9000/start?tags=project:infra,+clientA,+coding&token=YOURTOKEN"
# Stop it
curl -sS "https://arch-host.tailnet:9000/stop?token=YOURTOKEN"
# Health
curl -sS "https://arch-host.tailnet:9000/health"
```

3) iOS Shortcuts (webhook flavor)
No files needed—just two shortcuts that hit your endpoints:

Start timer (webhook)

- Action: “Text” → project:infra +clientA +coding (or use “Ask for Input” if you prefer)

- Action: “Get Contents of URL”

URL: https://arch-host.tailnet:9000/start

- Method: GET (or POST)

- Query: tags = (Provided Input or Text), token = YOURTOKEN

(Optional) Action: “Show Result” → Result

Stop timer (webhook)

- Action: “Get Contents of URL”

URL: https://arch-host.tailnet:9000/stop?token=YOURTOKEN

(Optional) “Show Result”

notes & tips

- Security: It’s already gated by your Tailnet; the extra TOKEN is just defense-in-depth. Prefer the Authorization: Bearer <token> header in production (Shortcuts supports headers).

- Same tags: pass the same strings you’d use in Taskwarrior (project:foo +tag1 +tag2)—the service doesn’t mutate them.

- One dataset: Because we bind-mount ~/.timewarrior, your CLI (timew ...) and webhook writes are in lockstep. Keep concurrent starts/stops sensible to avoid interleaving.

- Taskwarrior hook: leave your on-modify.timewarrior hook enabled; this webhook is just an extra remote control for Timewarrior.

If you want, I can also add a /start-task?uuid=<task-uuid> endpoint that looks up a Taskwarrior task (via a mirrored .task export on the cluster) and auto-applies its project/+tags to the timer—handy when you drive everything from tasks.


---

# Prompt 5

> **Yes and make sure the deployment instructions host everything on the Swarm cluster where I will also have Syncthing running to sync data if necessary**


---

# Prompt 6

> **Yes and make sure the deployment instructions host everything on the Swarm cluster where I will also have Syncthing running to sync data if necessary**


---

# Prompt 7

> **Yes and move the webhook related things to the swarm cluster. My Arch install will not always be available since it is a laptop but the Swarm cluster will always be available. The cluster also has Syncthing deployed if that can help with syncing between phone and laptop**

## ChatGPT GPT-5-THINKING :

Perfect—let’s run everything on the Swarm cluster and use Syncthing to mirror your Timewarrior data to your laptop so you can report locally even when the laptop is offline.

Below is a ready-to-use setup:

- A Taskchampion sync server service (for Taskwarrior/Taskchamp).

- A timew-webhook service (containerized Timewarrior + HTTP endpoints /start, /stop, etc.).

- Mounts Timewarrior’s data at a Syncthing folder on one Swarm node; your laptop’s Syncthing maps that to ~/.timewarrior.

0) One-time Swarm prep

1. Pick a data node (the one that already runs Syncthing) and label it so the timew service pins there:

```bash
docker node update --label-add timew.data=true <NODE_NAME>
```

1. Create the Syncthing-backed folder on that node (adjust the path if you already have one):

```bash
sudo mkdir -p /srv/sync/timewarrior/.timewarrior
sudo chown 0:0 /srv/sync/timewarrior/.timewarrior
sudo chmod 700 /srv/sync/timewarrior/.timewarrior
```

Add /srv/sync/timewarrior as a Syncthing folder on that node and share it to your Arch laptop, mapping it on the laptop to ~/.timewarrior. (On the laptop, ensure ~/.timewarrior is owned by your user after the first sync.)

1. Create a secret for the webhook token (defense-in-depth; you’ll also be on Tailnet or behind your proxy):

```bash
openssl rand -hex 32 | docker secret create timew_webhook_token -
```

1. (Optional) Reserve a DNS name for each service via your reverse proxy/TLS (e.g., tasksync.example.internal, timew.example.internal). Otherwise, hit them via Tailnet IP:port.

1) Build & push the timew-webhook image

On any machine with Docker:

```bash
git init timew-webhook && cd timew-webhook
```

Dockerfile
```dockerfile
FROM python:3.12-slim
RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  timewarrior ca-certificates tzdata bash \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh
# Timewarrior data home inside the container
RUN mkdir -p /var/lib/timew
ENV HOME=/var/lib/timew
EXPOSE 8000
CMD ["/app/entrypoint.sh"]
```

requirements.txt
```text
flask==3.0.3
gunicorn==22.0.0
```

entrypoint.sh
```bash
#!/usr/bin/env bash
set -euo pipefail
# Gunicorn binds to 0.0.0.0:8000 and serves app:app
exec gunicorn --workers=2 --threads=4 --timeout=30 \
  --bind 0.0.0.0:8000 app:app
```

app.py
```python
# timew-webhook/app.py
import os, re, shlex, subprocess
from flask import Flask, request, jsonify, abort
app = Flask(__name__)
TOKEN = os.environ.get("TOKEN", "")  # set in .env / compose
TIMEW_BIN = os.environ.get("TIMEW_BIN", "timew")
# we run with HOME=/var/lib/timew in Dockerfile; .timewarrior lives there
ALLOWED = re.compile(r"^[A-Za-z0-9:_+\-, ]{1,200}$")
def _auth_or_401():
    if not TOKEN:
        return  # no token set = open (not recommended)
    h = request.headers.get("Authorization", "")
    if h.startswith("Bearer "):
        if h.split(" ", 1)[1] == TOKEN:
            return
    # fallback: token query param (handy for iOS Shortcuts)
    if request.args.get("token") == TOKEN:
        return
    abort(401)
def _run(cmd):
    """Run a command and return (rc, out)."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()
def _tags_list_from_request():
    # accept JSON {"tags":"project:infra +clientA +coding"} or query ?tags=...
    tags = ""
    if request.is_json:
        tags = (request.get_json(silent=True) or {}).get("tags", "") or ""
    tags = request.args.get("tags", tags)
    tags = (tags or "").strip()
    if not tags:
        abort(400, description="missing 'tags'")
    # sanitize (allow only safe characters)
    if not ALLOWED.fullmatch(tags):
        abort(400, description="invalid characters in tags")
    # support comma- or space-separated; shlex for spacing
    tags = tags.replace(",", " ")
    parts = [p for p in shlex.split(tags) if p]
    if not parts:
        abort(400, description="no valid tags after parsing")
    return parts
@app.route("/start", methods=["GET", "POST"])
def start():
    _auth_or_401()
    tags = _tags_list_from_request()
    rc, out = _run([TIMEW_BIN, "start", *tags])
    return jsonify({"ok": rc == 0, "cmd": ["timew","start",*tags], "out": out}), (200 if rc == 0 else 500)
@app.route("/stop", methods=["GET", "POST"])
def stop():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, "stop"])
    return jsonify({"ok": True, "cmd": ["timew","stop"], "out": out}), 200
@app.route("/status", methods=["GET"])
def status():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, ""])
    # Fallback to `timew summary :day` for brevity if plain call fails
    if rc != 0:
        rc, out = _run([TIMEW_BIN, "summary", ":day"])
    return jsonify({"ok": rc == 0, "out": out}), 200
@app.route("/health", methods=["GET"])
def health():
    return "ok", 200
```

.env.example
```dotenv
# copy to .env and edit
TOKEN=change-me-to-a-long-random-string
# Where your host Timewarrior data lives (no trailing slash)
TIMEW_HOME=/home/tom
# Run container with same UID/GID so it doesn’t chown your files
PUID=1000
PGID=1000
# Port to expose on host
PORT=9000
```

compose.yaml  (recommended: run this on your Arch box)
```yaml
# timew-webhook/compose.yaml
version: "3.9"
services:
  timew-webhook:
    build:
      context: .
      dockerfile: Dockerfile
    image: local/timew-webhook:latest
    env_file: .env
    environment:
      # ensure HOME points to /var/lib/timew (already set in Dockerfile)
      - TOKEN=${TOKEN}
    ports:
      - "${PORT:-9000}:8000"
    user: "${PUID:-1000}:${PGID:-1000}"
    volumes:
      # mount host Timewarrior data so CLI and webhook share the SAME dataset
      - "${TIMEW_HOME}/.timewarrior:/var/lib/timew/.timewarrior"
    restart: unless-stopped
```

stack.swarm.yml  (optional: only if you truly want it on Swarm)

Use this only if you have your ~/.timewarrior mirrored to a Swarm node (e.g., via Syncthing to /srv/timew) and you’ve built/pushed the image to a registry (update image:).

```yaml
# timew-webhook/stack.swarm.yml
version: "3.9"
services:
  timew-webhook:
    image: registry.example.com/you/timew-webhook:latest
    environment:
      - TOKEN=${TOKEN}
    volumes:
      - /srv/timew/.timewarrior:/var/lib/timew/.timewarrior
    ports:
      - target: 8000
        published: 9000
        protocol: tcp
        mode: host
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
      # Optional Traefik labels if you want TLS on LAN/Tailnet
      # labels:
      #   - traefik.enable=true
      #   - traefik.http.routers.timew.rule=Host(`timew.example.internal`)
      #   - traefik.http.routers.timew.entrypoints=websecure
      #   - traefik.http.routers.timew.tls=true
      #   - traefik.http.services.timew.loadbalancer.server.port=8000
```

2) build & run (compose on Arch)
```bash
cd timew-webhook
cp .env.example .env
# edit .env: TOKEN, TIMEW_HOME, PUID, PGID, PORT
docker compose build
docker compose up -d
docker compose logs -f
```

First run will create /var/lib/timew/.timewarrior inside the container (backed by your host ~/.timewarrior).
From your iPhone (on Tailnet or over your reverse proxy), try:

```bash
# Start a timer with mirrored Taskwarrior-style taxonomy
curl -sS "https://arch-host.tailnet:9000/start?tags=project:infra,+clientA,+coding&token=YOURTOKEN"
# Stop it
curl -sS "https://arch-host.tailnet:9000/stop?token=YOURTOKEN"
# Health
curl -sS "https://arch-host.tailnet:9000/health"
```

3) iOS Shortcuts (webhook flavor)
No files needed—just two shortcuts that hit your endpoints:

Start timer (webhook)

- Action: “Text” → project:infra +clientA +coding (or use “Ask for Input” if you prefer)

- Action: “Get Contents of URL”

URL: https://arch-host.tailnet:9000/start

- Method: GET (or POST)

- Query: tags = (Provided Input or Text), token = YOURTOKEN

(Optional) Action: “Show Result” → Result

Stop timer (webhook)

- Action: “Get Contents of URL”

URL: https://arch-host.tailnet:9000/stop?token=YOURTOKEN

(Optional) “Show Result”

notes & tips

- Security: It’s already gated by your Tailnet; the extra TOKEN is just defense-in-depth. Prefer the Authorization: Bearer <token> header in production (Shortcuts supports headers).

- Same tags: pass the same strings you’d use in Taskwarrior (project:foo +tag1 +tag2)—the service doesn’t mutate them.

- One dataset: Because we bind-mount ~/.timewarrior, your CLI (timew ...) and webhook writes are in lockstep. Keep concurrent starts/stops sensible to avoid interleaving.

- Taskwarrior hook: leave your on-modify.timewarrior hook enabled; this webhook is just an extra remote control for Timewarrior.

If you want, I can also add a /start-task?uuid=<task-uuid> endpoint that looks up a Taskwarrior task (via a mirrored .task export on the cluster) and auto-applies its project/+tags to the timer—handy when you drive everything from tasks.


---

# Prompt 5

> **Yes and make sure the deployment instructions host everything on the Swarm cluster where I will also have Syncthing running to sync data if necessary**


---

# Prompt 6

> **Yes and make sure the deployment instructions host everything on the Swarm cluster where I will also have Syncthing running to sync data if necessary**


---

# Prompt 7

> **Yes and move the webhook related things to the swarm cluster. My Arch install will not always be available since it is a laptop but the Swarm cluster will always be available. The cluster also has Syncthing deployed if that can help with syncing between phone and laptop**

## ChatGPT GPT-5-THINKING :

Perfect—let’s run everything on the Swarm cluster and use Syncthing to mirror your Timewarrior data to your laptop so you can report locally even when the laptop is offline.

Below is a ready-to-use setup:

- A Taskchampion sync server service (for Taskwarrior/Taskchamp).

- A timew-webhook service (containerized Timewarrior + HTTP endpoints /start, /stop, etc.).

- Mounts Timewarrior’s data at a Syncthing folder on one Swarm node; your laptop’s Syncthing maps that to ~/.timewarrior.

0) One-time Swarm prep

1. Pick a data node (the one that already runs Syncthing) and label it so the timew service pins there:

```bash
docker node update --label-add timew.data=true <NODE_NAME>
```

1. Create the Syncthing-backed folder on that node (adjust the path if you already have one):

```bash
sudo mkdir -p /srv/sync/timewarrior/.timewarrior
sudo chown 0:0 /srv/sync/timewarrior/.timewarrior
sudo chmod 700 /srv/sync/timewarrior/.timewarrior
```

Add /srv/sync/timewarrior as a Syncthing folder on that node and share it to your Arch laptop, mapping it on the laptop to ~/.timewarrior. (On the laptop, ensure ~/.timewarrior is owned by your user after the first sync.)

1. Create a secret for the webhook token (defense-in-depth; you’ll also be on Tailnet or behind your proxy):

```bash
openssl rand -hex 32 | docker secret create timew_webhook_token -
```

1. (Optional) Reserve a DNS name for each service via your reverse proxy/TLS (e.g., tasksync.example.internal, timew.example.internal). Otherwise, hit them via Tailnet IP:port.

1) Build & push the timew-webhook image

On any machine with Docker:

```bash
git init timew-webhook && cd timew-webhook
```

Dockerfile
```dockerfile
FROM python:3.12-slim
RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  timewarrior ca-certificates tzdata bash \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh
# Timewarrior data home inside the container
RUN mkdir -p /var/lib/timew
ENV HOME=/var/lib/timew
EXPOSE 8000
CMD ["/app/entrypoint.sh"]
```

requirements.txt
```text
flask==3.0.3
gunicorn==22.0.0
```

entrypoint.sh
```bash
#!/usr/bin/env bash
set -euo pipefail
# Gunicorn binds to 0.0.0.0:8000 and serves app:app
exec gunicorn --workers=2 --threads=4 --timeout=30 \
  --bind 0.0.0.0:8000 app:app
```

app.py
```python
# timew-webhook/app.py
import os, re, shlex, subprocess
from flask import Flask, request, jsonify, abort
app = Flask(__name__)
TOKEN = os.environ.get("TOKEN", "")  # set in .env / compose
TIMEW_BIN = os.environ.get("TIMEW_BIN", "timew")
# we run with HOME=/var/lib/timew in Dockerfile; .timewarrior lives there
ALLOWED = re.compile(r"^[A-Za-z0-9:_+\-, ]{1,200}$")
def _auth_or_401():
    if not TOKEN:
        return  # no token set = open (not recommended)
    h = request.headers.get("Authorization", "")
    if h.startswith("Bearer "):
        if h.split(" ", 1)[1] == TOKEN:
            return
    # fallback: token query param (handy for iOS Shortcuts)
    if request.args.get("token") == TOKEN:
        return
    abort(401)
def _run(cmd):
    """Run a command and return (rc, out)."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()
def _tags_list_from_request():
    # accept JSON {"tags":"project:infra +clientA +coding"} or query ?tags=...
    tags = ""
    if request.is_json:
        tags = (request.get_json(silent=True) or {}).get("tags", "") or ""
    tags = request.args.get("tags", tags)
    tags = (tags or "").strip()
    if not tags:
        abort(400, description="missing 'tags'")
    # sanitize (allow only safe characters)
    if not ALLOWED.fullmatch(tags):
        abort(400, description="invalid characters in tags")
    # support comma- or space-separated; shlex for spacing
    tags = tags.replace(",", " ")
    parts = [p for p in shlex.split(tags) if p]
    if not parts:
        abort(400, description="no valid tags after parsing")
    return parts
@app.route("/start", methods=["GET", "POST"])
def start():
    _auth_or_401()
    tags = _tags_list_from_request()
    rc, out = _run([TIMEW_BIN, "start", *tags])
    return jsonify({"ok": rc == 0, "cmd": ["timew","start",*tags], "out": out}), (200 if rc == 0 else 500)
@app.route("/stop", methods=["GET", "POST"])
def stop():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, "stop"])
    return jsonify({"ok": True, "cmd": ["timew","stop"], "out": out}), 200
@app.route("/status", methods=["GET"])
def status():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, ""])
    # Fallback to `timew summary :day` for brevity if plain call fails
    if rc != 0:
        rc, out = _run([TIMEW_BIN, "summary", ":day"])
    return jsonify({"ok": rc == 0, "out": out}), 200
@app.route("/health", methods=["GET"])
def health():
    return "ok", 200
```

.env.example
```dotenv
# copy to .env and edit
TOKEN=change-me-to-a-long-random-string
# Where your host Timewarrior data lives (no trailing slash)
TIMEW_HOME=/home/tom
# Run container with same UID/GID so it doesn’t chown your files
PUID=1000
PGID=1000
# Port to expose on host
PORT=9000
```

compose.yaml  (recommended: run this on your Arch box)
```yaml
# timew-webhook/compose.yaml
version: "3.9"
services:
  timew-webhook:
    build:
      context: .
      dockerfile: Dockerfile
    image: local/timew-webhook:latest
    env_file: .env
    environment:
      # ensure HOME points to /var/lib/timew (already set in Dockerfile)
      - TOKEN=${TOKEN}
    ports:
      - "${PORT:-9000}:8000"
    user: "${PUID:-1000}:${PGID:-1000}"
    volumes:
      # mount host Timewarrior data so CLI and webhook share the SAME dataset
      - "${TIMEW_HOME}/.timewarrior:/var/lib/timew/.timewarrior"
    restart: unless-stopped
```

stack.swarm.yml  (optional: only if you truly want it on Swarm)

Use this only if you have your ~/.timewarrior mirrored to a Swarm node (e.g., via Syncthing to /srv/timew) and you’ve built/pushed the image to a registry (update image:).

```yaml
# timew-webhook/stack.swarm.yml
version: "3.9"
services:
  timew-webhook:
    image: registry.example.com/you/timew-webhook:latest
    environment:
      - TOKEN=${TOKEN}
    volumes:
      - /srv/timew/.timewarrior:/var/lib/timew/.timewarrior
    ports:
      - target: 8000
        published: 9000
        protocol: tcp
        mode: host
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
      # Optional Traefik labels if you want TLS on LAN/Tailnet
      # labels:
      #   - traefik.enable=true
      #   - traefik.http.routers.timew.rule=Host(`timew.example.internal`)
      #   - traefik.http.routers.timew.entrypoints=websecure
      #   - traefik.http.routers.timew.tls=true
      #   - traefik.http.services.timew.loadbalancer.server.port=8000
```

2) build & run (compose on Arch)
```bash
cd timew-webhook
cp .env.example .env
# edit .env: TOKEN, TIMEW_HOME, PUID, PGID, PORT
docker compose build
docker compose up -d
docker compose logs -f
```

First run will create /var/lib/timew/.timewarrior inside the container (backed by your host ~/.timewarrior).
From your iPhone (on Tailnet or over your reverse proxy), try:

```bash
# Start a timer with mirrored Taskwarrior-style taxonomy
curl -sS "https://arch-host.tailnet:9000/start?tags=project:infra,+clientA,+coding&token=YOURTOKEN"
# Stop it
curl -sS "https://arch-host.tailnet:9000/stop?token=YOURTOKEN"
# Health
curl -sS "https://arch-host.tailnet:9000/health"
```

3) iOS Shortcuts (webhook flavor)
No files needed—just two shortcuts that hit your endpoints:

Start timer (webhook)

- Action: “Text” → project:infra +clientA +coding (or use “Ask for Input” if you prefer)

- Action: “Get Contents of URL”

URL: https://arch-host.tailnet:9000/start

- Method: GET (or POST)

- Query: tags = (Provided Input or Text), token = YOURTOKEN

(Optional) Action: “Show Result” → Result

Stop timer (webhook)

- Action: “Get Contents of URL”

URL: https://arch-host.tailnet:9000/stop?token=YOURTOKEN

(Optional) “Show Result”

notes & tips

- Security: It’s already gated by your Tailnet; the extra TOKEN is just defense-in-depth. Prefer the Authorization: Bearer <token> header in production (Shortcuts supports headers).

- Same tags: pass the same strings you’d use in Taskwarrior (project:foo +tag1 +tag2)—the service doesn’t mutate them.

- One dataset: Because we bind-mount ~/.timewarrior, your CLI (timew ...) and webhook writes are in lockstep. Keep concurrent starts/stops sensible to avoid interleaving.

- Taskwarrior hook: leave your on-modify.timewarrior hook enabled; this webhook is just an extra remote control for Timewarrior.

If you want, I can also add a /start-task?uuid=<task-uuid> endpoint that looks up a Taskwarrior task (via a mirrored .task export on the cluster) and auto-applies its project/+tags to the timer—handy when you drive everything from tasks.


---

# Prompt 5

> **Yes and make sure the deployment instructions host everything on the Swarm cluster where I will also have Syncthing running to sync data if necessary**


---

# Prompt 6

> **Yes and make sure the deployment instructions host everything on the Swarm cluster where I will also have Syncthing running to sync data if necessary**


---

# Prompt 7

> **Yes and move the webhook related things to the swarm cluster. My Arch install will not always be available since it is a laptop but the Swarm cluster will always be available. The cluster also has Syncthing deployed if that can help with syncing between phone and laptop**

## ChatGPT GPT-5-THINKING :

Perfect—let’s run everything on the Swarm cluster and use Syncthing to mirror your Timewarrior data to your laptop so you can report locally even when the laptop is offline.

Below is a ready-to-use setup:

- A Taskchampion sync server service (for Taskwarrior/Taskchamp).

- A timew-webhook service (containerized Timewarrior + HTTP endpoints /start, /stop, etc.).

- Mounts Timewarrior’s data at a Syncthing folder on one Swarm node; your laptop’s Syncthing maps that to ~/.timewarrior.

0) One-time Swarm prep

1. Pick a data node (the one that already runs Syncthing) and label it so the timew service pins there:

```bash
docker node update --label-add timew.data=true <NODE_NAME>
```

1. Create the Syncthing-backed folder on that node (adjust the path if you already have one):

```bash
sudo mkdir -p /srv/sync/timewarrior/.timewarrior
sudo chown 0:0 /srv/sync/timewarrior/.timewarrior
sudo chmod 700 /srv/sync/timewarrior/.timewarrior
```

Add /srv/sync/timewarrior as a Syncthing folder on that node and share it to your Arch laptop, mapping it on the laptop to ~/.timewarrior. (On the laptop, ensure ~/.timewarrior is owned by your user after the first sync.)

1. Create a secret for the webhook token (defense-in-depth; you’ll also be on Tailnet or behind your proxy):

```bash
openssl rand -hex 32 | docker secret create timew_webhook_token -
```

1. (Optional) Reserve a DNS name for each service via your reverse proxy/TLS (e.g., tasksync.example.internal, timew.example.internal). Otherwise, hit them via Tailnet IP:port.

1) Build & push the timew-webhook image

On any machine with Docker:

```bash
git init timew-webhook && cd timew-webhook
```

Dockerfile
```dockerfile
FROM python:3.12-slim
RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  timewarrior ca-certificates tzdata bash \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh
# Timewarrior data home inside the container
RUN mkdir -p /var/lib/timew
ENV HOME=/var/lib/timew
EXPOSE 8000
CMD ["/app/entrypoint.sh"]
```

requirements.txt
```text
flask==3.0.3
gunicorn==22.0.0
```

entrypoint.sh
```bash
#!/usr/bin/env bash
set -euo pipefail
# Gunicorn binds to 0.0.0.0:8000 and serves app:app
exec gunicorn --workers=2 --threads=4 --timeout=30 \
  --bind 0.0.0.0:8000 app:app
```

app.py
```python
# timew-webhook/app.py
import os, re, shlex, subprocess
from flask import Flask, request, jsonify, abort
app = Flask(__name__)
TOKEN = os.environ.get("TOKEN", "")  # set in .env / compose
TIMEW_BIN = os.environ.get("TIMEW_BIN", "timew")
# we run with HOME=/var/lib/timew in Dockerfile; .timewarrior lives there
ALLOWED = re.compile(r"^[A-Za-z0-9:_+\-, ]{1,200}$")
def _auth_or_401():
    if not TOKEN:
        return  # no token set = open (not recommended)
    h = request.headers.get("Authorization", "")
    if h.startswith("Bearer "):
        if h.split(" ", 1)[1] == TOKEN:
            return
    # fallback: token query param (handy for iOS Shortcuts)
    if request.args.get("token") == TOKEN:
        return
    abort(401)
def _run(cmd):
    """Run a command and return (rc, out)."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()
def _tags_list_from_request():
    # accept JSON {"tags":"project:infra +clientA +coding"} or query ?tags=...
    tags = ""
    if request.is_json:
        tags = (request.get_json(silent=True) or {}).get("tags", "") or ""
    tags = request.args.get("tags", tags)
    tags = (tags or "").strip()
    if not tags:
        abort(400, description="missing 'tags'")
    # sanitize (allow only safe characters)
    if not ALLOWED.fullmatch(tags):
        abort(400, description="invalid characters in tags")
    # support comma- or space-separated; shlex for spacing
    tags = tags.replace(",", " ")
    parts = [p for p in shlex.split(tags) if p]
    if not parts:
        abort(400, description="no valid tags after parsing")
    return parts
@app.route("/start", methods=["GET", "POST"])
def start():
    _auth_or_401()
    tags = _tags_list_from_request()
    rc, out = _run([TIMEW_BIN, "start", *tags])
    return jsonify({"ok": rc == 0, "cmd": ["timew","start",*tags], "out": out}), (200 if rc == 0 else 500)
@app.route("/stop", methods=["GET", "POST"])
def stop():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, "stop"])
    return jsonify({"ok": True, "cmd": ["timew","stop"], "out": out}), 200
@app.route("/status", methods=["GET"])
def status():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, ""])
    # Fallback to `timew summary :day` for brevity if plain call fails
    if rc != 0:
        rc, out = _run([TIMEW_BIN, "summary", ":day"])
    return jsonify({"ok": rc == 0, "out": out}), 200
@app.route("/health", methods=["GET"])
def health():
    return "ok", 200
```

.env.example
```dotenv
# copy to .env and edit
TOKEN=change-me-to-a-long-random-string
# Where your host Timewarrior data lives (no trailing slash)
TIMEW_HOME=/home/tom
# Run container with same UID/GID so it doesn’t chown your files
PUID=1000
PGID=1000
# Port to expose on host
PORT=9000
```

compose.yaml  (recommended: run this on your Arch box)
```yaml
# timew-webhook/compose.yaml
version: "3.9"
services:
  timew-webhook:
    build:
      context: .
      dockerfile: Dockerfile
    image: local/timew-webhook:latest
    env_file: .env
    environment:
      # ensure HOME points to /var/lib/timew (already set in Dockerfile)
      - TOKEN=${TOKEN}
    ports:
      - "${PORT:-9000}:8000"
    user: "${PUID:-1000}:${PGID:-1000}"
    volumes:
      # mount host Timewarrior data so CLI and webhook share the SAME dataset
      - "${TIMEW_HOME}/.timewarrior:/var/lib/timew/.timewarrior"
    restart: unless-stopped
```

stack.swarm.yml  (optional: only if you truly want it on Swarm)

Use this only if you have your ~/.timewarrior mirrored to a Swarm node (e.g., via Syncthing to /srv/timew) and you’ve built/pushed the image to a registry (update image:).

```yaml
# timew-webhook/stack.swarm.yml
version: "3.9"
services:
  timew-webhook:
    image: registry.example.com/you/timew-webhook:latest
    environment:
      - TOKEN=${TOKEN}
    volumes:
      - /srv/timew/.timewarrior:/var/lib/timew/.timewarrior
    ports:
      - target: 8000
        published: 9000
        protocol: tcp
        mode: host
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
      # Optional Traefik labels if you want TLS on LAN/Tailnet
      # labels:
      #   - traefik.enable=true
      #   - traefik.http.routers.timew.rule=Host(`timew.example.internal`)
      #   - traefik.http.routers.timew.entrypoints=websecure
      #   - traefik.http.routers.timew.tls=true
      #   - traefik.http.services.timew.loadbalancer.server.port=8000
```

2) build & run (compose on Arch)
```bash
cd timew-webhook
cp .env.example .env
# edit .env: TOKEN, TIMEW_HOME, PUID, PGID, PORT
docker compose build
docker compose up -d
docker compose logs -f
```

First run will create /var/lib/timew/.timewarrior inside the container (backed by your host ~/.timewarrior).
From your iPhone (on Tailnet or over your reverse proxy), try:

```bash
# Start a timer with mirrored Taskwarrior-style taxonomy
curl -sS "https://arch-host.tailnet:9000/start?tags=project:infra,+clientA,+coding&token=YOURTOKEN"
# Stop it
curl -sS "https://arch-host.tailnet:9000/stop?token=YOURTOKEN"
# Health
curl -sS "https://arch-host.tailnet:9000/health"
```

3) iOS Shortcuts (webhook flavor)
No files needed—just two shortcuts that hit your endpoints:

Start timer (webhook)

- Action: “Text” → project:infra +clientA +coding (or use “Ask for Input” if you prefer)

- Action: “Get Contents of URL”

URL: https://arch-host.tailnet:9000/start

- Method: GET (or POST)

- Query: tags = (Provided Input or Text), token = YOURTOKEN

(Optional) Action: “Show Result” → Result

Stop timer (webhook)

- Action: “Get Contents of URL”

URL: https://arch-host.tailnet:9000/stop?token=YOURTOKEN

(Optional) “Show Result”

notes & tips

- Security: It’s already gated by your Tailnet; the extra TOKEN is just defense-in-depth. Prefer the Authorization: Bearer <token> header in production (Shortcuts supports headers).

- Same tags: pass the same strings you’d use in Taskwarrior (project:foo +tag1 +tag2)—the service doesn’t mutate them.

- One dataset: Because we bind-mount ~/.timewarrior, your CLI (timew ...) and webhook writes are in lockstep. Keep concurrent starts/stops sensible to avoid interleaving.

- Taskwarrior hook: leave your on-modify.timewarrior hook enabled; this webhook is just an extra remote control for Timewarrior.

If you want, I can also add a /start-task?uuid=<task-uuid> endpoint that looks up a Taskwarrior task (via a mirrored .task export on the cluster) and auto-applies its project/+tags to the timer—handy when you drive everything from tasks.


---

# Prompt 5

> **Yes and make sure the deployment instructions host everything on the Swarm cluster where I will also have Syncthing running to sync data if necessary**


---

# Prompt 6

> **Yes and make sure the deployment instructions host everything on the Swarm cluster where I will also have Syncthing running to sync data if necessary**


---

# Prompt 7

> **Yes and move the webhook related things to the swarm cluster. My Arch install will not always be available since it is a laptop but the Swarm cluster will always be available. The cluster also has Syncthing deployed if that can help with syncing between phone and laptop**

## ChatGPT GPT-5-THINKING :

Perfect—let’s run everything on the Swarm cluster and use Syncthing to mirror your Timewarrior data to your laptop so you can report locally even when the laptop is offline.

Below is a ready-to-use setup:

- A Taskchampion sync server service (for Taskwarrior/Taskchamp).

- A timew-webhook service (containerized Timewarrior + HTTP endpoints /start, /stop, etc.).

- Mounts Timewarrior’s data at a Syncthing folder on one Swarm node; your laptop’s Syncthing maps that to ~/.timewarrior.

0) One-time Swarm prep

1. Pick a data node (the one that already runs Syncthing) and label it so the timew service pins there:

```bash
docker node update --label-add timew.data=true <NODE_NAME>
```

1. Create the Syncthing-backed folder on that node (adjust the path if you already have one):

```bash
sudo mkdir -p /srv/sync/timewarrior/.timewarrior
sudo chown 0:0 /srv/sync/timewarrior/.timewarrior
sudo chmod 700 /srv/sync/timewarrior/.timewarrior
```

Add /srv/sync/timewarrior as a Syncthing folder on that node and share it to your Arch laptop, mapping it on the laptop to ~/.timewarrior. (On the laptop, ensure ~/.timewarrior is owned by your user after the first sync.)

1. Create a secret for the webhook token (defense-in-depth; you’ll also be on Tailnet or behind your proxy):

```bash
openssl rand -hex 32 | docker secret create timew_webhook_token -
```

1. (Optional) Reserve a DNS name for each service via your reverse proxy/TLS (e.g., tasksync.example.internal, timew.example.internal). Otherwise, hit them via Tailnet IP:port.

1) Build & push the timew-webhook image

On any machine with Docker:

```bash
git init timew-webhook && cd timew-webhook
```

Dockerfile
```dockerfile
FROM python:3.12-slim
RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  timewarrior ca-certificates tzdata bash \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh
# Timewarrior data home inside the container
RUN mkdir -p /var/lib/timew
ENV HOME=/var/lib/timew
EXPOSE 8000
CMD ["/app/entrypoint.sh"]
```

requirements.txt
```text
flask==3.0.3
gunicorn==22.0.0
```

entrypoint.sh
```bash
#!/usr/bin/env bash
set -euo pipefail
# Gunicorn binds to 0.0.0.0:8000 and serves app:app
exec gunicorn --workers=2 --threads=4 --timeout=30 \
  --bind 0.0.0.0:8000 app:app
```

app.py
```python
# timew-webhook/app.py
import os, re, shlex, subprocess
from flask import Flask, request, jsonify, abort
app = Flask(__name__)
TOKEN = os.environ.get("TOKEN", "")  # set in .env / compose
TIMEW_BIN = os.environ.get("TIMEW_BIN", "timew")
# we run with HOME=/var/lib/timew in Dockerfile; .timewarrior lives there
ALLOWED = re.compile(r"^[A-Za-z0-9:_+\-, ]{1,200}$")
def _auth_or_401():
    if not TOKEN:
        return  # no token set = open (not recommended)
    h = request.headers.get("Authorization", "")
    if h.startswith("Bearer "):
        if h.split(" ", 1)[1] == TOKEN:
            return
    # fallback: token query param (handy for iOS Shortcuts)
    if request.args.get("token") == TOKEN:
        return
    abort(401)
def _run(cmd):
    """Run a command and return (rc, out)."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()
def _tags_list_from_request():
    # accept JSON {"tags":"project:infra +clientA +coding"} or query ?tags=...
    tags = ""
    if request.is_json:
        tags = (request.get_json(silent=True) or {}).get("tags", "") or ""
    tags = request.args.get("tags", tags)
    tags = (tags or "").strip()
    if not tags:
        abort(400, description="missing 'tags'")
    # sanitize (allow only safe characters)
    if not ALLOWED.fullmatch(tags):
        abort(400, description="invalid characters in tags")
    # support comma- or space-separated; shlex for spacing
    tags = tags.replace(",", " ")
    parts = [p for p in shlex.split(tags) if p]
    if not parts:
        abort(400, description="no valid tags after parsing")
    return parts
@app.route("/start", methods=["GET", "POST"])
def start():
    _auth_or_401()
    tags = _tags_list_from_request()
    rc, out = _run([TIMEW_BIN, "start", *tags])
    return jsonify({"ok": rc == 0, "cmd": ["timew","start",*tags], "out": out}), (200 if rc == 0 else 500)
@app.route("/stop", methods=["GET", "POST"])
def stop():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, "stop"])
    return jsonify({"ok": True, "cmd": ["timew","stop"], "out": out}), 200
@app.route("/status", methods=["GET"])
def status():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, ""])
    # Fallback to `timew summary :day` for brevity if plain call fails
    if rc != 0:
        rc, out = _run([TIMEW_BIN, "summary", ":day"])
    return jsonify({"ok": rc == 0, "out": out}), 200
@app.route("/health", methods=["GET"])
def health():
    return "ok", 200
```

.env.example
```dotenv
# copy to .env and edit
TOKEN=change-me-to-a-long-random-string
# Where your host Timewarrior data lives (no trailing slash)
TIMEW_HOME=/home/tom
# Run container with same UID/GID so it doesn’t chown your files
PUID=1000
PGID=1000
# Port to expose on host
PORT=9000
```

compose.yaml  (recommended: run this on your Arch box)
```yaml
# timew-webhook/compose.yaml
version: "3.9"
services:
  timew-webhook:
    build:
      context: .
      dockerfile: Dockerfile
    image: local/timew-webhook:latest
    env_file: .env
    environment:
      # ensure HOME points to /var/lib/timew (already set in Dockerfile)
      - TOKEN=${TOKEN}
    ports:
      - "${PORT:-9000}:8000"
    user: "${PUID:-1000}:${PGID:-1000}"
    volumes:
      # mount host Timewarrior data so CLI and webhook share the SAME dataset
      - "${TIMEW_HOME}/.timewarrior:/var/lib/timew/.timewarrior"
    restart: unless-stopped
```

stack.swarm.yml  (optional: only if you truly want it on Swarm)

Use this only if you have your ~/.timewarrior mirrored to a Swarm node (e.g., via Syncthing to /srv/timew) and you’ve built/pushed the image to a registry (update image:).

```yaml
# timew-webhook/stack.swarm.yml
version: "3.9"
services:
  timew-webhook:
    image: registry.example.com/you/timew-webhook:latest
    environment:
      - TOKEN=${TOKEN}
    volumes:
      - /srv/timew/.timewarrior:/var/lib/timew/.timewarrior
    ports:
      - target: 8000
        published: 9000
        protocol: tcp
        mode: host
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
      # Optional Traefik labels if you want TLS on LAN/Tailnet
      # labels:
      #   - traefik.enable=true
      #   - traefik.http.routers.timew.rule=Host(`timew.example.internal`)
      #   - traefik.http.routers.timew.entrypoints=websecure
      #   - traefik.http.routers.timew.tls=true
      #   - traefik.http.services.timew.loadbalancer.server.port=8000
```

2) build & run (compose on Arch)
```bash
cd timew-webhook
cp .env.example .env
# edit .env: TOKEN, TIMEW_HOME, PUID, PGID, PORT
docker compose build
docker compose up -d
docker compose logs -f
```

First run will create /var/lib/timew/.timewarrior inside the container (backed by your host ~/.timewarrior).
From your iPhone (on Tailnet or over your reverse proxy), try:

```bash
# Start a timer with mirrored Taskwarrior-style taxonomy
curl -sS "https://arch-host.tailnet:9000/start?tags=project:infra,+clientA,+coding&token=YOURTOKEN"
# Stop it
curl -sS "https://arch-host.tailnet:9000/stop?token=YOURTOKEN"
# Health
curl -sS "https://arch-host.tailnet:9000/health"
```

3) iOS Shortcuts (webhook flavor)
No files needed—just two shortcuts that hit your endpoints:

Start timer (webhook)

- Action: “Text” → project:infra +clientA +coding (or use “Ask for Input” if you prefer)

- Action: “Get Contents of URL”

URL: https://arch-host.tailnet:9000/start

- Method: GET (or POST)

- Query: tags = (Provided Input or Text), token = YOURTOKEN

(Optional) Action: “Show Result” → Result

Stop timer (webhook)

- Action: “Get Contents of URL”

URL: https://arch-host.tailnet:9000/stop?token=YOURTOKEN

(Optional) “Show Result”

notes & tips

- Security: It’s already gated by your Tailnet; the extra TOKEN is just defense-in-depth. Prefer the Authorization: Bearer <token> header in production (Shortcuts supports headers).

- Same tags: pass the same strings you’d use in Taskwarrior (project:foo +tag1 +tag2)—the service doesn’t mutate them.

- One dataset: Because we bind-mount ~/.timewarrior, your CLI (timew ...) and webhook writes are in lockstep. Keep concurrent starts/stops sensible to avoid interleaving.

- Taskwarrior hook: leave your on-modify.timewarrior hook enabled; this webhook is just an extra remote control for Timewarrior.

If you want, I can also add a /start-task?uuid=<task-uuid> endpoint that looks up a Taskwarrior task (via a mirrored .task export on the cluster) and auto-applies its project/+tags to the timer—handy when you drive everything from tasks.


---

# Prompt 5

> **Yes and make sure the deployment instructions host everything on the Swarm cluster where I will also have Syncthing running to sync data if necessary**


---

# Prompt 6

> **Yes and make sure the deployment instructions host everything on the Swarm cluster where I will also have Syncthing running to sync data if necessary**


---

# Prompt 7

> **Yes and move the webhook related things to the swarm cluster. My Arch install will not always be available since it is a laptop but the Swarm cluster will always be available. The cluster also has Syncthing deployed if that can help with syncing between phone and laptop**

## ChatGPT GPT-5-THINKING :

Perfect—let’s run everything on the Swarm cluster and use Syncthing to mirror your Timewarrior data to your laptop so you can report locally even when the laptop is offline.

Below is a ready-to-use setup:

- A Taskchampion sync server service (for Taskwarrior/Taskchamp).

- A timew-webhook service (containerized Timewarrior + HTTP endpoints /start, /stop, etc.).

- Mounts Timewarrior’s data at a Syncthing folder on one Swarm node; your laptop’s Syncthing maps that to ~/.timewarrior.

0) One-time Swarm prep

1. Pick a data node (the one that already runs Syncthing) and label it so the timew service pins there:

```bash
docker node update --label-add timew.data=true <NODE_NAME>
```

1. Create the Syncthing-backed folder on that node (adjust the path if you already have one):

```bash
sudo mkdir -p /srv/sync/timewarrior/.timewarrior
sudo chown 0:0 /srv/sync/timewarrior/.timewarrior
sudo chmod 700 /srv/sync/timewarrior/.timewarrior
```

Add /srv/sync/timewarrior as a Syncthing folder on that node and share it to your Arch laptop, mapping it on the laptop to ~/.timewarrior. (On the laptop, ensure ~/.timewarrior is owned by your user after the first sync.)

1. Create a secret for the webhook token (defense-in-depth; you’ll also be on Tailnet or behind your proxy):

```bash
openssl rand -hex 32 | docker secret create timew_webhook_token -
```

1. (Optional) Reserve a DNS name for each service via your reverse proxy/TLS (e.g., tasksync.example.internal, timew.example.internal). Otherwise, hit them via Tailnet IP:port.

1) Build & push the timew-webhook image

On any machine with Docker:

```bash
git init timew-webhook && cd timew-webhook
```

Dockerfile
```dockerfile
FROM python:3.12-slim
RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  timewarrior ca-certificates tzdata bash \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh
# Timewarrior data home inside the container
RUN mkdir -p /var/lib/timew
ENV HOME=/var/lib/timew
EXPOSE 8000
CMD ["/app/entrypoint.sh"]
```

requirements.txt
```text
flask==3.0.3
gunicorn==22.0.0
```

entrypoint.sh
```bash
#!/usr/bin/env bash
set -euo pipefail
# Gunicorn binds to 0.0.0.0:8000 and serves app:app
exec gunicorn --workers=2 --threads=4 --timeout=30 \
  --bind 0.0.0.0:8000 app:app
```

app.py
```python
# timew-webhook/app.py
import os, re, shlex, subprocess
from flask import Flask, request, jsonify, abort
app = Flask(__name__)
TOKEN = os.environ.get("TOKEN", "")  # set in .env / compose
TIMEW_BIN = os.environ.get("TIMEW_BIN", "timew")
# we run with HOME=/var/lib/timew in Dockerfile; .timewarrior lives there
ALLOWED = re.compile(r"^[A-Za-z0-9:_+\-, ]{1,200}$")
def _auth_or_401():
    if not TOKEN:
        return  # no token set = open (not recommended)
    h = request.headers.get("Authorization", "")
    if h.startswith("Bearer "):
        if h.split(" ", 1)[1] == TOKEN:
            return
    # fallback: token query param (handy for iOS Shortcuts)
    if request.args.get("token") == TOKEN:
        return
    abort(401)
def _run(cmd):
    """Run a command and return (rc, out)."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()
def _tags_list_from_request():
    # accept JSON {"tags":"project:infra +clientA +coding"} or query ?tags=...
    tags = ""
    if request.is_json:
        tags = (request.get_json(silent=True) or {}).get("tags", "") or ""
    tags = request.args.get("tags", tags)
    tags = (tags or "").strip()
    if not tags:
        abort(400, description="missing 'tags'")
    # sanitize (allow only safe characters)
    if not ALLOWED.fullmatch(tags):
        abort(400, description="invalid characters in tags")
    # support comma- or space-separated; shlex for spacing
    tags = tags.replace(",", " ")
    parts = [p for p in shlex.split(tags) if p]
    if not parts:
        abort(400, description="no valid tags after parsing")
    return parts
@app.route("/start", methods=["GET", "POST"])
def start():
    _auth_or_401()
    tags = _tags_list_from_request()
    rc, out = _run([TIMEW_BIN, "start", *tags])
    return jsonify({"ok": rc == 0, "cmd": ["timew","start",*tags], "out": out}), (200 if rc == 0 else 500)
@app.route("/stop", methods=["GET", "POST"])
def stop():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, "stop"])
    return jsonify({"ok": True, "cmd": ["timew","stop"], "out": out}), 200
@app.route("/status", methods=["GET"])
def status():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, ""])
    # Fallback to `timew summary :day` for brevity if plain call fails
    if rc != 0:
        rc, out = _run([TIMEW_BIN, "summary", ":day"])
    return jsonify({"ok": rc == 0, "out": out}), 200
@app.route("/health", methods=["GET"])
def health():
    return "ok", 200
```

.env.example
```dotenv
# copy to .env and edit
TOKEN=change-me-to-a-long-random-string
# Where your host Timewarrior data lives (no trailing slash)
TIMEW_HOME=/home/tom
# Run container with same UID/GID so it doesn’t chown your files
PUID=1000
PGID=1000
# Port to expose on host
PORT=9000
```

compose.yaml  (recommended: run this on your Arch box)
```yaml
# timew-webhook/compose.yaml
version: "3.9"
services:
  timew-webhook:
    build:
      context: .
      dockerfile: Dockerfile
    image: local/timew-webhook:latest
    env_file: .env
    environment:
      # ensure HOME points to /var/lib/timew (already set in Dockerfile)
      - TOKEN=${TOKEN}
    ports:
      - "${PORT:-9000}:8000"
    user: "${PUID:-1000}:${PGID:-1000}"
    volumes:
      # mount host Timewarrior data so CLI and webhook share the SAME dataset
      - "${TIMEW_HOME}/.timewarrior:/var/lib/timew/.timewarrior"
    restart: unless-stopped
```

stack.swarm.yml  (optional: only if you truly want it on Swarm)

Use this only if you have your ~/.timewarrior mirrored to a Swarm node (e.g., via Syncthing to /srv/timew) and you’ve built/pushed the image to a registry (update image:).

```yaml
# timew-webhook/stack.swarm.yml
version: "3.9"
services:
  timew-webhook:
    image: registry.example.com/you/timew-webhook:latest
    environment:
      - TOKEN=${TOKEN}
    volumes:
      - /srv/timew/.timewarrior:/var/lib/timew/.timewarrior
    ports:
      - target: 8000
        published: 9000
        protocol: tcp
        mode: host
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
      # Optional Traefik labels if you want TLS on LAN/Tailnet
      # labels:
      #   - traefik.enable=true
      #   - traefik.http.routers.timew.rule=Host(`timew.example.internal`)
      #   - traefik.http.routers.timew.entrypoints=websecure
      #   - traefik.http.routers.timew.tls=true
      #   - traefik.http.services.timew.loadbalancer.server.port=8000
```

2) build & run (compose on Arch)
```bash
cd timew-webhook
cp .env.example .env
# edit .env: TOKEN, TIMEW_HOME, PUID, PGID, PORT
docker compose build
docker compose up -d
docker compose logs -f
```

First run will create /var/lib/timew/.timewarrior inside the container (backed by your host ~/.timewarrior).
From your iPhone (on Tailnet or over your reverse proxy), try:

```bash
# Start a timer with mirrored Taskwarrior-style taxonomy
curl -sS "https://arch-host.tailnet:9000/start?tags=project:infra,+clientA,+coding&token=YOURTOKEN"
# Stop it
curl -sS "https://arch-host.tailnet:9000/stop?token=YOURTOKEN"
# Health
curl -sS "https://arch-host.tailnet:9000/health"
```

3) iOS Shortcuts (webhook flavor)
No files needed—just two shortcuts that hit your endpoints:

Start timer (webhook)

- Action: “Text” → project:infra +clientA +coding (or use “Ask for Input” if you prefer)

- Action: “Get Contents of URL”

URL: https://arch-host.tailnet:9000/start

- Method: GET (or POST)

- Query: tags = (Provided Input or Text), token = YOURTOKEN

(Optional) Action: “Show Result” → Result

Stop timer (webhook)

- Action: “Get Contents of URL”

URL: https://arch-host.tailnet:9000/stop?token=YOURTOKEN

(Optional) “Show Result”

notes & tips

- Security: It’s already gated by your Tailnet; the extra TOKEN is just defense-in-depth. Prefer the Authorization: Bearer <token> header in production (Shortcuts supports headers).

- Same tags: pass the same strings you’d use in Taskwarrior (project:foo +tag1 +tag2)—the service doesn’t mutate them.

- One dataset: Because we bind-mount ~/.timewarrior, your CLI (timew ...) and webhook writes are in lockstep. Keep concurrent starts/stops sensible to avoid interleaving.

- Taskwarrior hook: leave your on-modify.timewarrior hook enabled; this webhook is just an extra remote control for Timewarrior.

If you want, I can also add a /start-task?uuid=<task-uuid> endpoint that looks up a Taskwarrior task (via a mirrored .task export on the cluster) and auto-applies its project/+tags to the timer—handy when you drive everything from tasks.


---

# Prompt 5

> **Yes and make sure the deployment instructions host everything on the Swarm cluster where I will also have Syncthing running to sync data if necessary**


---

# Prompt 6

> **Yes and make sure the deployment instructions host everything on the Swarm cluster where I will also have Syncthing running to sync data if necessary**


---

# Prompt 7

> **Yes and move the webhook related things to the swarm cluster. My Arch install will not always be available since it is a laptop but the Swarm cluster will always be available. The cluster also has Syncthing deployed if that can help with syncing between phone and laptop**

## ChatGPT GPT-5-THINKING :

Perfect—let’s run everything on the Swarm cluster and use Syncthing to mirror your Timewarrior data to your laptop so you can report locally even when the laptop is offline.

Below is a ready-to-use setup:

- A Taskchampion sync server service (for Taskwarrior/Taskchamp).

- A timew-webhook service (containerized Timewarrior + HTTP endpoints /start, /stop, etc.).

- Mounts Timewarrior’s data at a Syncthing folder on one Swarm node; your laptop’s Syncthing maps that to ~/.timewarrior.

0) One-time Swarm prep

1. Pick a data node (the one that already runs Syncthing) and label it so the timew service pins there:

```bash
docker node update --label-add timew.data=true <NODE_NAME>
```

1. Create the Syncthing-backed folder on that node (adjust the path if you already have one):

```bash
sudo mkdir -p /srv/sync/timewarrior/.timewarrior
sudo chown 0:0 /srv/sync/timewarrior/.timewarrior
sudo chmod 700 /srv/sync/timewarrior/.timewarrior
```

Add /srv/sync/timewarrior as a Syncthing folder on that node and share it to your Arch laptop, mapping it on the laptop to ~/.timewarrior. (On the laptop, ensure ~/.timewarrior is owned by your user after the first sync.)

1. Create a secret for the webhook token (defense-in-depth; you’ll also be on Tailnet or behind your proxy):

```bash
openssl rand -hex 32 | docker secret create timew_webhook_token -
```

1. (Optional) Reserve a DNS name for each service via your reverse proxy/TLS (e.g., tasksync.example.internal, timew.example.internal). Otherwise, hit them via Tailnet IP:port.

1) Build & push the timew-webhook image

On any machine with Docker:

```bash
git init timew-webhook && cd timew-webhook
```

Dockerfile
```dockerfile
FROM python:3.12-slim
RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  timewarrior ca-certificates tzdata bash \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh
# Timewarrior data home inside the container
RUN mkdir -p /var/lib/timew
ENV HOME=/var/lib/timew
EXPOSE 8000
CMD ["/app/entrypoint.sh"]
```

requirements.txt
```text
flask==3.0.3
gunicorn==22.0.0
```

entrypoint.sh
```bash
#!/usr/bin/env bash
set -euo pipefail
# Gunicorn binds to 0.0.0.0:8000 and serves app:app
exec gunicorn --workers=2 --threads=4 --timeout=30 \
  --bind 0.0.0.0:8000 app:app
```

app.py
```python
# timew-webhook/app.py
import os, re, shlex, subprocess
from flask import Flask, request, jsonify, abort
app = Flask(__name__)
TOKEN = os.environ.get("TOKEN", "")  # set in .env / compose
TIMEW_BIN = os.environ.get("TIMEW_BIN", "timew")
# we run with HOME=/var/lib/timew in Dockerfile; .timewarrior lives there
ALLOWED = re.compile(r"^[A-Za-z0-9:_+\-, ]{1,200}$")
def _auth