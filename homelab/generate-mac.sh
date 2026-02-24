#!/bin/bash
PREFIX="BC:24:11"
# for i in {01..10}; do
LAST=$(openssl rand -hex 3 | sed 's/\(..\)/\1:/g; s/:$//')
MAC="${PREFIX}:${LAST}"
printf "%s\n" "$MAC" | awk '{print toupper($0)}'  # Uppercase for standard format
# done