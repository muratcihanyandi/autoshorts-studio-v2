#!/usr/bin/env sh
# Autonomous Creator Studio - uygulama imajlarini derler.
# Pi uzerinde, kaynak klasorunun icinden calistirin:
#   sh deploy/casaos/build-on-pi.sh
# CasaOS zaten docker + docker compose v2 ile birlikte gelir.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "HATA: docker bulunamadi."
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "HATA: docker compose (v2) bulunamadi."
  exit 1
fi

echo ">> Backend imaji derleniyor (ilk seferde 5-10 dakika surebilir)..."
docker build -f backend/Dockerfile -t autoshorts-studio-backend:local .

echo ">> Frontend imaji derleniyor (npm ci + vite build)..."
docker build -f frontend/Dockerfile -t autoshorts-studio-frontend:local .

echo ""
echo ">> Hazir. Yerel imajlar:"
docker images --format "{{.Repository}}:{{.Tag}}" | grep "^autoshorts-studio-" || true
echo ""
echo ">> Sonraki adim: deploy/casaos/docker-compose.external-db.yml (veya"
echo "   docker-compose.casaos.yml) icindeki sifre yer tutucusunu doldurup"
echo "   CasaOS'a yapistirin. Ayrinti: deploy/casaos/README.md"
