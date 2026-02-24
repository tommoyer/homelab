#!/usr/bin/env bash
set -euo pipefail

# Builds and installs a Caddy binary that includes the Cloudflare DNS module.
# Intended to be run inside the LXC container.
#
# The Proxmox VE Helper Script docs mention for external modules:
#   xcaddy build --with github.com/caddy-dns/cloudflare

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "error: run as root (use sudo)" >&2
  exit 1
fi

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "error: missing required command: $1" >&2
    exit 1
  fi
}

ensure_xcaddy() {
  if command -v xcaddy >/dev/null 2>&1; then
    return 0
  fi

  echo "xcaddy not found; attempting to install it" >&2

  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y --no-install-recommends ca-certificates curl golang-go git
  elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache ca-certificates curl go git
  else
    echo "error: unsupported distro/package manager; install xcaddy manually" >&2
    exit 1
  fi

  need_cmd go
  need_cmd git

  # Install into a predictable location.
  GOBIN=/usr/local/bin go install github.com/caddyserver/xcaddy/cmd/xcaddy@latest
  need_cmd xcaddy
}

plugin="github.com/caddy-dns/cloudflare"

ensure_xcaddy

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

caddy_out="${workdir}/caddy"

echo "Building Caddy with module: ${plugin}" >&2
xcaddy build --with "${plugin}" --output "${caddy_out}"

install_path="$(command -v caddy || true)"
if [[ -z "${install_path}" ]]; then
  install_path="/usr/bin/caddy"
fi

if [[ -f "${install_path}" ]]; then
  backup="${install_path}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
  cp -a "${install_path}" "${backup}"
  echo "Backed up existing caddy to: ${backup}" >&2
fi

install -m 0755 "${caddy_out}" "${install_path}"

# Allow binding to 80/443 without running as root (best-effort).
if command -v setcap >/dev/null 2>&1; then
  setcap cap_net_bind_service=+ep "${install_path}" || true
fi

# Restart to pick up the new binary.
if command -v systemctl >/dev/null 2>&1; then
  systemctl restart caddy
else
  echo "warn: systemctl not found; restart caddy manually" >&2
fi

# Quick sanity check: ensure the module is present.
if command -v caddy >/dev/null 2>&1; then
  if caddy list-modules 2>/dev/null | grep -q '^dns\.providers\.cloudflare$'; then
    echo "Cloudflare DNS module is present (dns.providers.cloudflare)." >&2
  else
    echo "warn: could not confirm module via 'caddy list-modules'" >&2
  fi
fi

echo "Done." >&2
