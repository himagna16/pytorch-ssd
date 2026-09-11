#!/usr/bin/env bash
# Build and run the decoder tests. Needs a C compiler and the team's trainenv.
set -euo pipefail
cd "$(dirname "$0")"
PY=${PY:-../../../trainenv/bin/python}
mkdir -p build
"$PY" gen_vectors.py --out build/vectors.txt
cc -std=c99 -Wall -Wextra -Werror -O2 -o build/test_follow_decode test_follow_decode.c follow_decode.c -lm
./build/test_follow_decode build/vectors.txt
