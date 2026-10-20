#!/bin/zsh
# Deploy the "Geraubte Häuser" map to the Hetzner box (dictionaryofml.org).
# Run this yourself when ready to publish — it pushes to the public site.
#
#   ./deploy.sh
#
# Prereqs: SSH access to host `dictionaryofml` (in ~/.ssh/config) and a fresh
# build (`make all`, or scripts/06_build_site.py if only the site is stale).
set -e
cd "${0:A:h}"            # the directory this script lives in

SLUG="geraubte-haeuser"
REMOTE_DIR="/var/www/dictionaryofml.org/html/${SLUG}/"

[[ -f docs/data/map_data.json ]] || { echo "no build — run scripts/06_build_site.py first"; exit 1; }
echo "staging $(du -sh docs | cut -f1) from docs/"

ssh dictionaryofml "mkdir -p ${REMOTE_DIR}"
rsync -az --delete docs/ "dictionaryofml:${REMOTE_DIR}"
echo "rsync exit: $?"

CODE=$(curl -sS -o /dev/null -w "%{http_code}" "https://dictionaryofml.org/${SLUG}/")
echo "DEPLOY COMPLETE: page=HTTP${CODE}"
echo "Live at: https://dictionaryofml.org/${SLUG}/"
