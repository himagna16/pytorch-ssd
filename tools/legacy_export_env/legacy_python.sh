#!/usr/bin/env bash
# Proxy python3 into the legacy py3.8.10/torch1.10.2 NEMO export container
# (image: nemo-legacy-export:py38, built from the Dockerfile next to this
# script). Mounts the drone workspace (three levels up) at its own host
# path so absolute paths in wrapped commands resolve identically inside.
DRONE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
exec docker run --rm -i --platform linux/amd64 \
  -v "${DRONE_ROOT}:${DRONE_ROOT}" \
  -w "$PWD" \
  -e PYTHONUNBUFFERED=1 \
  nemo-legacy-export:py38 python3 "$@"
