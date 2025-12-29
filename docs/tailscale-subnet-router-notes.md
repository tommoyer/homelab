# Project Documentation: Proxmox + Tailscale + Caddy (DMZ) + MikroTik

## Network Topology & Definitions

This configuration assumes the following network layout based on your specifications:

* **VLAN 10 (Homelab / Trusted):** `192.168.10.0/24`
* **Proxmox VIP:** `192.168.10.29`
* **Tailscale Subnet Router:** `192.168.10.20`
* **Pi-hole:** `192.168.10.27`


* **VLAN 20 (DMZ / Untrusted):** `192.168.20.0/24`
* **Caddy Reverse Proxy:** `192.168.20.3`


* **Domain:** `moyer.wtf` (Public Wildcard via Cloudflare)

---

## Part 1: Architecture Strategy (Subnet Router vs. Direct Install)

**User Prompt:**

> I have a proxmox cluster. On that cluster, I have a Tailscale subnet router. Does it make sense to not directly add the nodes in the cluster to Tailscale and instead access them through the subnet router?

**Response:**
Yes, using a **Subnet Router** (at `192.168.10.20`) is the cleanest architectural choice for your Proxmox cluster (`192.168.10.29`).

**Why this approach is superior:**

1. **Hypervisor Purity:** You do not install third-party agents directly on the Proxmox host, keeping the hypervisor "clean" and upgradable.
2. **Cluster Stability:** Proxmox HA relies on Corosync (latency-sensitive). Keeping Tailscale off the host prevents VPN interfaces from interfering with cluster heartbeats.
3. **Security Segmentation:** By placing the router in a separate container (`192.168.10.20`), you can apply firewall rules to it specifically, rather than exposing the management interface of the host directly.

**The Trade-off:**
Proxmox logs will see traffic coming from `192.168.10.20` (the router) rather than the actual remote user IP. This is usually acceptable for home labs.

---

## Part 2: Split DNS & Pi-hole Configuration

**User Prompt:**

> With a subnet router and a Pihole instance, is there a way to rely on that Pihole instance to access my nodes via hostnames instead of having to remember IP addresses?

**Response:**
Yes. You use **Split DNS**. You will configure Tailscale to send DNS queries for `*.moyer.wtf` specifically to your internal Pi-hole.

**Crucial Configuration for VLAN Topology:**
Because Caddy lives in the DMZ (`192.168.20.3`), your internal DNS records must point to **Caddy**, not the destination server.

**1. Pi-hole Records (at `192.168.10.27`):**
Go to **Local DNS** -> **DNS Records**.

| Domain | Target IP | Description |
| --- | --- | --- |
| `proxmox.moyer.wtf` | `192.168.20.3` | Points to Caddy (DMZ) |
| `grafana.moyer.wtf` | `192.168.20.3` | Points to Caddy (DMZ) |

**2. Tailscale Admin Console:**

* **Nameservers:** Add `192.168.10.27` (Pi-hole).
* **Split DNS:** Restrict this nameserver to the domain `moyer.wtf`.
* **Override Local DNS:** **OFF**.

**3. The Traffic Flow:**
Remote User -> Request `proxmox.moyer.wtf` -> Tailscale DNS (Pi-hole) returns `192.168.20.3` -> Traffic routes through Subnet Router -> Caddy -> Proxmox.

---

## Part 3: Public Domain & Wildcard Certificates

**User Prompt:**

> How would this work when I have a public domain such as moyer.wtf which has a wildcard record in Cloudflare? Would the pihole's response be the one that is used because it is the directly configured DNS server and it would respond before sending the query upstream?

**Response:**
This is a **Split Horizon** setup.

1. **Internal/VPN Users:** Tailscale forces the lookup to Pi-hole. Pi-hole answers `192.168.20.3` (Internal DMZ IP).
2. **Public Users:** Public DNS (Cloudflare) answers with your WAN IP (which forwards port 443 to `192.168.20.3`).

**Benefit:** Caddy uses a **DNS-01 Challenge** to get a valid Let's Encrypt wildcard certificate. This allows your internal services to have valid green HTTPS locks without exposing every service to the internet.

---

## Part 4: Tailscale Subnet Router Configuration

**User Prompt:**

> What changes when the Caddy reverse proxy is in the DMZ VLAN and the Tailscale subnet router is in the Homelab VLAN?

**Response:**
Since the Subnet Router (`192.168.10.20`) is in the Homelab VLAN, but Caddy (`192.168.20.3`) is in the DMZ VLAN, the router must advertise **BOTH** routes so remote users can reach both the services and the proxy.

**Configuration:**
Run this on the Subnet Router LXC (`192.168.10.20`):

```bash
# 1. Enable IP Forwarding
echo 'net.ipv4.ip_forward = 1' | sudo tee -a /etc/sysctl.d/99-tailscale.conf
echo 'net.ipv6.conf.all.forwarding = 1' | sudo tee -a /etc/sysctl.d/99-tailscale.conf
sudo sysctl -p /etc/sysctl.d/99-tailscale.conf

# 2. Start Tailscale
# We advertise 192.168.10.0/24 (Homelab) for direct IP access
# We advertise 192.168.20.0/24 (DMZ) so remote users can reach Caddy
sudo tailscale up \
  --advertise-routes=192.168.10.0/24,192.168.20.0/24 \
  --accept-dns=false \
  --ssh

```

---

## Part 5: MikroTik Firewall Rules

**User Prompt:**

> What are the Mikrotik firewall rules that need added to the configuration?

**Response:**
You need to punch holes in the firewall to allow the "hairpin" traffic.

1. **Caddy (DMZ)** must reach **Proxmox (Homelab)** to proxy traffic.
2. **Subnet Router (Homelab)** must reach **Caddy (DMZ)** so VPN users can load the site.

**MikroTik Configuration Script:**

```bash
# 1. Define Address List for your Backend Services (Homelab)
/ip firewall address-list
add list=caddy_backends address=192.168.10.29 comment="Proxmox VIP"
add list=caddy_backends address=192.168.10.27 comment="Pi-hole Web Interface"

# 2. Rule: Allow Caddy (DMZ) -> Homelab Backends
# This allows Caddy to proxy traffic DOWN to the secure zone
/ip firewall filter
add chain=forward action=accept \
    src-address=192.168.20.3 \
    dst-address-list=caddy_backends \
    dst-port=8006,80,3000 protocol=tcp \
    comment="Allow Caddy (DMZ) to Access Homelab Services"

# 3. Rule: Allow Tailscale Subnet Router (Homelab) -> Caddy (DMZ)
# This allows VPN users to loop UP to the proxy to get the SSL cert
/ip firewall filter
add chain=forward action=accept \
    src-address=192.168.10.20 \
    dst-address=192.168.20.3 \
    dst-port=80,443 protocol=tcp \
    comment="Allow Tailscale Router to Access Caddy"

# 4. Move rules (Optional CLI command to place them correctly)
# Ensure these rules are placed ABOVE your "Drop All" forward rule
# /ip firewall filter move [find comment="Allow Caddy (DMZ) to Access Homelab Services"] destination=1

```

---

## Part 6: Caddy Configuration (Custom Build & Caddyfile)

**User Prompt:**

> Generate the full Caddyfile that uses both Tailscale and Let's Encrypt using this new map setup... Ensure that any configuration files are printed as a single code block.

**Response:**
Because Caddy is in the DMZ (`192.168.20.3`) but proxmox is in the Homelab (`192.168.10.29`), the Caddyfile must map hostnames to the **Homelab IPs**.

### A. Dockerfile (Custom Build)

Required for the Cloudflare DNS plugin.

```dockerfile
FROM caddy:builder AS builder

RUN xcaddy build \
    --with github.com/caddy-dns/cloudflare

FROM caddy:latest

COPY --from=builder /usr/bin/caddy /usr/bin/caddy

```

### B. The Master Caddyfile

This configuration uses a **Map** to keep things clean. It listens on `192.168.20.3` and proxies traffic across the VLAN boundary to `192.168.10.x`.

```caddy
{
    email your-email@example.com
}

# ------------------------------------------------------------------
# Public Wildcard Handler (moyer.wtf)
# ------------------------------------------------------------------
*.moyer.wtf {
    # 1. Cloudflare DNS Challenge for Wildcard Certs
    tls {
        dns cloudflare {env.CLOUDFLARE_API_TOKEN}
    }

    # 2. Service Map (Hostname -> Backend IP in Homelab VLAN 10)
    map {host} {backend} {
        # Hostname              # Target IP (VLAN 10)
        proxmox.moyer.wtf       192.168.10.29:8006
        pihole.moyer.wtf        192.168.10.27:80
        
        # Add other services here...
        
        default                 unknown
    }

    # 3. Proxmox Handler (Special case: HTTPS backend + Self-Signed)
    @proxmox host proxmox.moyer.wtf
    handle @proxmox {
        reverse_proxy https://192.168.10.29:8006 {
            transport http {
                tls_insecure_skip_verify
            }
        }
    }

    # 4. Generic Handler (Standard HTTP backends)
    @mapped expression {backend} != "unknown"
    handle @mapped {
        reverse_proxy {backend}
    }

    # 5. Fallback for undefined subdomains
    handle {
        respond "Service not defined in Caddy Map" 404
    }
}

```

### C. Docker Compose (If using Docker)

```yaml
version: "3.7"
services:
  caddy:
    build: .
    container_name: caddy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    environment:
      - CLOUDFLARE_API_TOKEN=your_token_here
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
      - caddy_config:/config
    networks:
      - dmz_net

networks:
  dmz_net:
    driver: bridge

```