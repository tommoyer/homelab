#!/usr/bin/env python3
"""
apply_cloudflare_dnscontrol.py

Generates external_records.json from dns_names.yaml (external.enabled + cloudflare.target_ip)
and runs:
  dnscontrol preview
  dnscontrol push (after confirmation), unless --dry-run

Requires:
  - dnscontrol in PATH
  - CLOUDFLARE_API_TOKEN env var (unless --dry-run)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from netops_lib import check_prerequisites, iter_cloudflare_records, load_sot


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--json", default="external_records.json")
    args = ap.parse_args()

    if not check_prerequisites(needs_dnscontrol=True):
        return 1

    sot = load_sot(args.data_dir)
    records = list(iter_cloudflare_records(sot))
    if not records:
        print("No Cloudflare records found. Skipping.")
        return 0

    if "CLOUDFLARE_API_TOKEN" not in os.environ and not args.dry_run:
        print("[Error] CLOUDFLARE_API_TOKEN is missing.", file=sys.stderr)
        return 2

    if args.dry_run:
        os.makedirs("dry-run", exist_ok=True)
        dry_path = os.path.join("dry-run", os.path.basename(args.json))
        with open(dry_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)
        print(f"[Dry Run] Wrote: {dry_path}")
        return 0

    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    print(f"Wrote: {args.json}")

    print("Running DNSControl preview...")
    subprocess.run(["dnscontrol", "preview"], check=False)

    print("\n--- external_records.json ---")
    print(json.dumps(records, indent=2))
    print("-----------------------------\n")

    confirm = input("Type 'yes' to push to Cloudflare: ").strip().lower()
    if confirm == "yes":
        print("Pushing changes to Cloudflare...")
        try:
            subprocess.run(["dnscontrol", "push"], check=True)
            print("Cloudflare update complete.")
        except subprocess.CalledProcessError:
            print("[Error] dnscontrol push failed.", file=sys.stderr)
            return 2
    else:
        print("Push aborted by user.")

    if not args.keep and os.path.exists(args.json):
        os.remove(args.json)
        print(f"Cleaned up {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
