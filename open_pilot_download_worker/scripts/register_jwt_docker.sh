#!/usr/bin/env bash
set -euo pipefail
set -x

if [ "$#" -lt 1 ]; then
	echo "Usage: $0 <jtw>"
	exit 1
fi

jwt="$1"

source ~/miniconda3/etc/profile.d/conda.sh
conda activate $CONDA_ENV_NAME
cd /app/openpilot/
source ./.venv/bin/activate

python ./tools/lib/auth.py jwt "$jwt"