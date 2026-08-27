#!/usr/bin/env bash
set -euo pipefail

PACKET_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${PACKET_DIR}/.build"
mkdir -p "${BUILD_DIR}"

build_packet() {
  local source_name="$1"
  local output_name="$2"
  (
    cd "${PACKET_DIR}"
    pdflatex -interaction=nonstopmode -halt-on-error \
      -output-directory="${BUILD_DIR}" \
      "${source_name}" >/dev/null
    pdflatex -interaction=nonstopmode -halt-on-error \
      -output-directory="${BUILD_DIR}" \
      "${source_name}" >/dev/null
  )
  cp "${BUILD_DIR}/${source_name%.tex}.pdf" "${PACKET_DIR}/${output_name}"
}

build_packet frontend_onboarding.tex DroneRS_Frontend_Firmware_Onboarding.pdf
build_packet backend_onboarding.tex DroneRS_Backend_Model_Onboarding.pdf

echo "Built onboarding PDFs in ${PACKET_DIR}"
