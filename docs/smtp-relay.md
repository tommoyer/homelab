# SMTP Relay (Outbound) for Homelab Services

Last updated: 2025-12-30

## Overview

Recommended pattern for a homelab:

1. Use a reputable transactional SMTP provider for Internet delivery.
2. Run one internal SMTP relay (Postfix) that all apps talk to, and have it forward to the provider.

This avoids the two biggest pain points of self-hosting outbound email at home:

- Deliverability (PTR/rDNS, IP reputation, blacklists)
- ISP blocks/filters on outbound TCP/25

## Choosing an Outbound SMTP Provider

Pick a provider that supports:

- SMTP submission on 465 (SMTPS) or 587 (STARTTLS)
- Domain verification + DKIM signing
- Clear logs, bounces/blocks visibility, and reasonable pricing

Common choices: Amazon SES, Mailgun, SendGrid, Postmark, SMTP2GO, Brevo (Sendinblue), Mailjet, Fastmail, Zoho.

Note: Cloudflare Email Routing is inbound only (no outbound SMTP).

## DNS Requirements (Deliverability)

Publish the following for your sending domain:

- SPF
- DKIM
- DMARC

Your SMTP provider will give exact record values during domain authentication.

Optional: publish a Null MX to signal “no inbound mail” (example): `moyer.wtf MX 0 .`.

## Gitea Configuration (Mailer)

Example app.ini mailer configuration (use your provider values):

```ini
[mailer]
ENABLED   = true
FROM      = "Gitea <noreply@git.example.com>"
PROTOCOL  = smtp+starttls     ; or: smtps
SMTP_ADDR = smtp.yourprovider.tld
SMTP_PORT = 587               ; or: 465 for smtps
USER      = noreply@git.example.com
PASSWD    = your-smtp-password-or-token
```

Enable verification and notifications:

```ini
[service]
REGISTER_EMAIL_CONFIRM = true
ENABLE_NOTIFY_MAIL     = true
```

Use Gitea’s UI to send a test email after restart: Site Administration → Configuration → SMTP Mailer Configuration.

## Internal Relay Pattern (Recommended)

- Run an internal Postfix relay on your LAN/VLAN.
- Configure it as a smarthost authenticating to your SMTP provider.
- Restrict access to internal networks (and/or require internal auth).
- Point apps to `smtp-relay.lan:25` (or 587). Only the relay stores provider credentials.

Benefits: central credential rotation, logging, rate limiting, standardized sender addresses (better DMARC alignment).

## Free Tiers for <100 Emails/Day

- Brevo (Sendinblue): ~300/day free
- Mailjet: 6,000/month, 200/day cap
- SMTP2GO: 1,000/month, 200/day cap

Gmail/Google Workspace and Microsoft 365 expose SMTP and work for low volume, but transactional providers are generally smoother for app mail.

## Domain: moyer.wtf (Sending Only)

- Use a transactional provider (e.g., Brevo, Mailjet, SMTP2GO) as upstream.
- Publish SPF/DKIM/DMARC provided by your upstream.
- Optional: Null MX to signal no inbound.

## Postfix Smarthost (Debian 13)

Install packages:

```bash
sudo apt update
sudo apt install -y postfix libsasl2-modules ca-certificates mailutils
```

Core Postfix configuration in `/etc/postfix/main.cf` (Brevo example; keep distro defaults otherwise):

```conf
# Identity
myhostname = smtp-relay.lan
myorigin = moyer.wtf

# Listen for LAN clients
inet_interfaces = all
inet_protocols = ipv4

# Only allow relaying from internal networks (adjust to your VLANs/subnets)
mynetworks = 127.0.0.0/8, 192.168.10.0/24
smtpd_relay_restrictions = permit_mynetworks, reject_unauth_destination

# Upstream SMTP provider (smarthost)
relayhost = [smtp-relay.brevo.com]:587

# TLS + SMTP AUTH to upstream
smtp_tls_security_level = encrypt
smtp_sasl_auth_enable = yes
smtp_sasl_password_maps = hash:/etc/postfix/sasl_passwd
smtp_sasl_security_options = noanonymous
```

Credentials in `/etc/postfix/sasl_passwd`:

```conf
[smtp-relay.brevo.com]:587 YOUR_BREVO_SMTP_LOGIN:YOUR_BREVO_MASTER_PASSWORD
```

Secure and apply credentials:

```bash
sudo chmod 600 /etc/postfix/sasl_passwd
sudo postmap /etc/postfix/sasl_passwd
sudo systemctl restart postfix
sudo systemctl status postfix --no-pager
```

### Restrict to 192.168.10.0/24 (Host Firewall)

Using nftables (`/etc/nftables.conf` minimal example):

```nft
table inet filter {
	chain input {
		type filter hook input priority 0;
		policy drop;
		iif "lo" accept
		ct state established,related accept
		# Allow SMTP from VLAN10 only
		ip saddr 192.168.10.0/24 tcp dport 25 accept
		# Optional: allow SSH from VLAN10
		ip saddr 192.168.10.0/24 tcp dport 22 accept
	}
}
```

Enable/apply:

```bash
sudo systemctl enable --now nftables
sudo nft -f /etc/nftables.conf
sudo nft list ruleset
```

### MikroTik hEX S (RouterOS 7) Notes

- Same-VLAN traffic may bypass `/ip firewall filter` unless bridge firewalling is enabled (use-ip-firewall / use-ip-firewall-for-vlan). Prefer host firewall + Postfix `mynetworks`.
- Ensure no WAN port forward to the relay on TCP/25.
- Ensure outbound TCP/587 (and DNS/53) from the relay is allowed.

Optional RouterOS rules if traffic is routed (replace `<RELAY_IP>`):

```routeros
/ip firewall filter
add chain=forward action=accept protocol=tcp src-address=192.168.10.0/24 dst-address=<RELAY_IP> dst-port=25 comment="Allow VLAN10 to SMTP relay"
add chain=forward action=drop   protocol=tcp                          dst-address=<RELAY_IP> dst-port=25 comment="Drop SMTP relay from non-VLAN10"
```

### Testing

Send a test:

```bash
printf "Subject: postfix relay test\n\nhello\n" | sendmail -v you@example.com
```

Check logs:

```bash
sudo journalctl -u postfix -n 200 --no-pager
```

Validate upstream connectivity:

```bash
openssl s_client -starttls smtp -connect smtp-relay.brevo.com:587 -crlf
```

## DSN Handling and Cleanup

If DSNs (delivery status notifications) are being relayed upstream and rejected (e.g., `MAIL FROM: <>`), make mail to `@moyer.wtf` local:

```conf
mydomain = moyer.wtf
myorigin = $mydomain
mydestination = $myhostname, localhost.$mydomain, localhost, $mydomain
```

Reload and flush queue:

```bash
sudo postfix reload
postqueue -p
sudo postqueue -f
```

Remove deprecated settings warning (you already have `smtp_tls_security_level = encrypt`):

```bash
sudo postconf -X smtp_use_tls
sudo postfix reload
```

## Troubleshooting Checklist

- Relay host reaches provider on 465/587.
- `FROM` address is allowed by provider.
- SPF/DKIM/DMARC published and correct.
- Use Gitea’s test email page before real notifications.

## Outcome Log Example (Simplified)

Evidence of success and DSNs delivered locally:

- Outbound to Gmail accepted by Brevo: `status=sent (250 2.0.0 OK...)`
- DSNs delivered locally: `relay=local ... status=sent (delivered to mailbox)`

---

## Cleanups / Hardening

### 1) Remove deprecated `smtp_use_tls`

If you still see a warning like:

> support for parameter "smtp_use_tls" will be removed; instead, specify "smtp_tls_security_level"

Fix it:

```bash
sudo postconf -n | grep -E '^smtp_use_tls|^smtp_tls_security_level'
sudo postconf -X smtp_use_tls
sudo postfix reload
```

Confirm the warning is gone:

```bash
sudo systemctl restart postfix
sudo journalctl -u postfix -n 50 --no-pager
```

### 2) Ensure only VLAN10 can reach TCP/25

Even if Postfix is configured with `mynetworks`, enforce it at the host firewall as well (especially if traffic stays L2 and the router never sees it).

Minimal nftables rule idea (SMTP portion only):

```nft
ip saddr 192.168.10.0/24 tcp dport 25 accept
tcp dport 25 drop
```

### 3) Prefer a non-root sender

For app mail, standardize on something like:

- `noreply@moyer.wtf`
- `gitea@moyer.wtf`

For a one-off shell test with an explicit From:

```bash
printf "Subject: test\nFrom: noreply@moyer.wtf\n\nhello\n" | sendmail -v you@example.com
```


## If Gmail Doesn’t Receive the Test Email

If Postfix logs show `status=sent`, that only proves the relay-to-provider hop worked (not that Gmail accepted it).

Do this in order:

1. Check Gmail placement
	- Look in Spam and All Mail
	- Search Gmail for `subject:"postfix relay test"` and `from:root@moyer.wtf`
2. Check provider logs (most important)
	- In your provider (e.g., Brevo), check SMTP activity/transactional logs
	- Search by recipient and/or Message-ID (from Postfix logs)
	- Look for “blocked”, “bounced”, or “not authorized sender”
3. Make the sender a verified address (common root cause)
	- Prefer `noreply@moyer.wtf` (or `gitea@moyer.wtf`) rather than `root@moyer.wtf`
	- Ensure the domain is authenticated with SPF/DKIM/DMARC
4. Optional: rewrite outbound `root@…` to `noreply@…`

Create `/etc/postfix/generic`:

```conf
root@moyer.wtf noreply@moyer.wtf
root@smtp-relay.homelab.moyer.wtf noreply@moyer.wtf
```

Enable it:

```bash
sudo postmap /etc/postfix/generic
sudo postconf -e 'smtp_generic_maps = hash:/etc/postfix/generic'
sudo postfix reload
```

Send another test with a unique subject:

```bash
printf "Subject: postfix relay test 2\n\nhello\n" | sendmail -v you@example.com
```

5. High-signal testing: use `swaks`

```bash
sudo apt install -y swaks
swaks --to you@example.com --server 127.0.0.1 --port 25 --from noreply@moyer.wtf --header "Subject: swaks test $(date -Is)"
```


## Application Settings (Gitea and Other Services)

Treat the Postfix host as a trusted internal SMTP relay and keep application SMTP settings simple.

Recommended defaults for most apps:

- SMTP host: `smtp-relay.<lan-domain>` (or the relay IP)
- SMTP port: `25`
- Encryption/TLS: off
- Authentication: off
- From address: a standardized sender (e.g., `noreply@moyer.wtf` or `gitea@moyer.wtf`)
- HELO/EHLO name (if the app asks): app hostname or `smtp-relay.<lan-domain>`

Rationale: TLS/auth is enforced by your network boundary (only trusted networks can reach the relay) and by Postfix (`mynetworks`).

### Gitea app.ini example

```ini
[mailer]
ENABLED   = true
FROM      = "Gitea <gitea@moyer.wtf>"
PROTOCOL  = smtp
SMTP_ADDR = smtp-relay.lan
SMTP_PORT = 25
USER      =
PASSWD    =
```

Enable the behaviors you want:

```ini
[service]
REGISTER_EMAIL_CONFIRM = true    ; user verification emails
ENABLE_NOTIFY_MAIL     = true    ; repo/activity notifications
```

If you see “invalid sender” or missing mail at Gmail, ensure your chosen From address/domain is allowed by your upstream provider and your SPF/DKIM/DMARC are published.