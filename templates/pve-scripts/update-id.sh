#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  kanidm-update-gid.sh <group|person> <gidnumber> <name>

Examples:
  kanidm-update-gid.sh group 2001 unix-admins
  kanidm-update-gid.sh person 2001 alice

Notes:
  - This script prints and runs the appropriate Kanidm command.
  - It assumes your Kanidm CLI environment/authentication is already configured.
  - If your admin identity is not supplied through KANIDM_NAME, it defaults to idm_admin.
USAGE
}

if [[ $# -ne 3 ]]; then
  usage
  exit 1
fi

type_input="$1"
gidnumber="$2"
entry_name="$3"
admin_name="${KANIDM_NAME:-idm_admin}"

if [[ ! "$gidnumber" =~ ^[0-9]+$ ]]; then
  echo "Error: gidnumber must be a numeric value." >&2
  exit 1
fi

case "${type_input,,}" in
  group)
    cmd=(kanidm group posix set --name "$admin_name" "$entry_name" --gidnumber "$gidnumber")
    ;;
  person)
    cmd=(kanidm person posix set --name "$admin_name" "$entry_name" --gidnumber "$gidnumber")
    ;;
  *)
    echo "Error: first argument must be 'group' or 'person'." >&2
    usage
    exit 1
    ;;
esac

echo "Running: ${cmd[*]}"
"${cmd[@]}"