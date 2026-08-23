#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VALIDATION_OUTPUT_DIR="${VALIDATION_OUTPUT_DIR:-${PROJECT_DIR}/logs/plain_follow_app_validation}"

VERIFY_PYTHON="${PLAIN_FOLLOW_VERIFY_PYTHON:-python3}"
if ! command -v "${VERIFY_PYTHON}" >/dev/null 2>&1; then
  echo "ERROR: ${VERIFY_PYTHON} is required for the handoff integrity check." >&2
  exit 1
fi
"${VERIFY_PYTHON}" "${PROJECT_DIR}/tools/verify_plain_follow_handoff.py"

export HOST_APP_DIR="${HOST_APP_DIR:-${PROJECT_DIR}/application}"
export HOST_VALIDATION_MAIN="${HOST_VALIDATION_MAIN:-${PROJECT_DIR}/aideck_val_main_plain_follow.c}"
export HOST_EXPECTED_OUTPUT="${HOST_EXPECTED_OUTPUT:-${PROJECT_DIR}/application/validation/output.txt}"
export HOST_INPUT_HEX="${HOST_INPUT_HEX:-${PROJECT_DIR}/application/hex/inputs.hex}"
export HOST_RUN_LOG_COPY="${HOST_RUN_LOG_COPY:-${VALIDATION_OUTPUT_DIR}/gvsoc_run.log}"
export HOST_FINAL_TENSOR_JSON="${HOST_FINAL_TENSOR_JSON:-${VALIDATION_OUTPUT_DIR}/gvsoc_final_tensor.json}"
export COMPARE_SCRIPT="${COMPARE_SCRIPT:-${PROJECT_DIR}/export/archive/compare_gap8_final_tensor.py}"
export EXPECTED_TENSOR_COUNT="${EXPECTED_TENSOR_COUNT:-14}"
export HOST_PATCH_BN_QUANT_INT64="${HOST_PATCH_BN_QUANT_INT64:-1}"
export AUTO_REFRESH_APP="${AUTO_REFRESH_APP:-0}"
export RUN_STAGE_DRIFT_DEBUG="${RUN_STAGE_DRIFT_DEBUG:-0}"
export MODEL_SENTINEL="${MODEL_SENTINEL:-${PROJECT_DIR}/application/src/network.c}"
export MODEL_MANIFEST="${MODEL_MANIFEST:-${PROJECT_DIR}/application/src/network.c}"
export PLATFORM="${PLATFORM:-gvsoc}"
export AIDECK_IMAGE="${AIDECK_IMAGE:-bitcraze/aideck@sha256:038197df9cb86ccf8e6649e93dd0cf23781830e136288523983768918851633e}"
export CONTAINER_NAME="${CONTAINER_NAME:-plain-follow-app-val}"

container_created_by_wrapper=0
if command -v docker >/dev/null 2>&1 &&
   ! docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
  container_created_by_wrapper=1
fi

cleanup_container() {
  if [[ "${container_created_by_wrapper}" == "1" && "${KEEP_VALIDATION_CONTAINER:-0}" != "1" ]]; then
    docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  fi
}
trap cleanup_container EXIT

bash "${PROJECT_DIR}/tools/run_aideck_val_impl.sh" "$@"
