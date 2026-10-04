#!/usr/bin/env bash
# Bounded asset download. Preserve every failed transfer; publish only checked bytes.
set -Eeuo pipefail
url="${1:?URL}"; output="${2:?new output path}"; expected="${3:?SHA-256}"
[ "$#" -eq 3 ] && [[ "$expected" =~ ^[0-9a-f]{64}$ ]] || exit 2
[ ! -e "$output" ] || { echo "Refusing existing download: $output" >&2; exit 2; }
for attempt in 1 2 3; do
  partial="$output.attempt-$attempt"
  [ ! -e "$partial" ] || { echo "Refusing existing transfer evidence: $partial" >&2; exit 2; }
  code=0
  curl -fsSL --connect-timeout 30 --max-time 1800 -o "$partial" "$url" || code=$?
  if [ "$code" -eq 0 ]; then
    actual="$(sha256sum "$partial" | cut -c1-64)"
    [ "$actual" = "$expected" ] || { echo "SHA-256 mismatch; retained $partial" >&2; exit 2; }
    mv -- "$partial" "$output"
    exit 0
  fi
  echo "Transfer $attempt failed (curl exit $code); retained $partial" >&2
  [ "$attempt" -eq 3 ] || sleep 2
done
echo "Download incomplete after 3 attempts: $output" >&2
exit 2
