#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

echo "==> Pulling latest code"
git pull

echo "==> Rebuilding image"
sudo docker compose build

echo "==> Restarting container"
sudo docker compose up -d

echo "==> Done. Verifying:"
sudo docker compose ps
