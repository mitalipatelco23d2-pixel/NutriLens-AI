#!/usr/bin/env bash
# Build a frozen revision on Linux without copying local secrets or model caches.
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
revision=$(git -C "$repo_root" rev-parse --verify "${1:-HEAD}^{commit}")
short_revision=${revision:0:12}
scratch=$(mktemp -d /tmp/nutrilens-cloudflare.XXXXXXXX)
artifact="$repo_root/.open-next/linux-$short_revision"
if [[ -e "$artifact" ]]; then
  printf 'Artifact already exists; refusing to overwrite: %s\n' "$artifact" >&2
  exit 1
fi
printf 'Linux build workspace: %s\nRevision: %s\n' "$scratch" "$revision"

cd "$scratch"
curl --fail --silent --show-error --location \
  https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt -o SHASUMS256.txt
archive=$(awk '/node-v22\.[0-9]+\.[0-9]+-linux-x64.tar.xz$/ {print $2; exit}' SHASUMS256.txt)
[[ "$archive" =~ ^node-v22\.[0-9]+\.[0-9]+-linux-x64.tar.xz$ ]]
curl --fail --silent --show-error --location \
  "https://nodejs.org/dist/latest-v22.x/$archive" -o "$archive"
awk -v archive="$archive" '$2 == archive' SHASUMS256.txt | sha256sum -c -
mkdir node source
tar -xJf "$archive" -C node --strip-components=1
export PATH="$scratch/node/bin:$PATH"
git -C "$repo_root" archive "$revision" | tar -xf - -C source
cd source

# These public origins are compiled into Next's headers and browser bundles.
export PUBLIC_API_URL=https://api.nutrilensx.tech
export NEXT_PUBLIC_API_URL=https://api.nutrilensx.tech
export NEXT_TELEMETRY_DISABLED=1
node --version
npm ci --no-audit --no-fund
npm run cf:build
test -f .open-next/worker.js
mkdir -p "$repo_root/.open-next"
cp -a .open-next "$artifact"
printf '\nValidated Linux build available at: %s\n' "$artifact"
# Retain the isolated workspace for diagnostics; never delete computed trees here.
