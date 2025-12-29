# syntax=docker/dockerfile:1
# Build Caddy with the Cloudflare DNS plugin so DNS-01 challenges work.
FROM caddy:builder-alpine AS builder

RUN xcaddy build \
  --with github.com/caddy-dns/cloudflare

FROM caddy:alpine

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
