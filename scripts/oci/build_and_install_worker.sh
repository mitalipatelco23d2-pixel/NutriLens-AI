#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "Refusing OCI production build: native aarch64 host required." >&2
  exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo so the service and root-only environment files can be installed." >&2
  exit 1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"

for command in docker systemctl python3 sha256sum; do
  command -v "${command}" >/dev/null || {
    echo "Missing required command: ${command}" >&2
    exit 1
  }
done

model_path=".model-cache/r3/custom/nutrition-table-yolo11n-v1.pt"
expected_model_sha="af30081551e4f9c5dfae3c6d28515ec848c2559e27c15c31e363d474d00bd16b"
if [[ ! -f "${model_path}" ]]; then
  echo "Private custom model is absent. Transfer it through the approved private channel." >&2
  exit 1
fi
actual_model_sha="$(sha256sum "${model_path}" | awk '{print $1}')"
if [[ "${actual_model_sha}" != "${expected_model_sha}" ]]; then
  echo "Custom model checksum mismatch; refusing to build." >&2
  exit 1
fi

for model in PP-OCRv5_mobile_det PP-OCRv5_mobile_rec; do
  model_root=".model-cache/r3/paddle/official_models/${model}"
  for file in config.json inference.json inference.pdiparams inference.yml; do
    [[ -s "${model_root}/${file}" ]] || {
      echo "Missing cached Paddle artifact: ${model_root}/${file}" >&2
      exit 1
    }
  done
done

docker build \
  --platform linux/arm64 \
  --file infrastructure/docker/ai-worker.Dockerfile \
  --tag nutrilens-ai-worker:oci-arm64 \
  .

docker run --rm --entrypoint python nutrilens-ai-worker:oci-arm64 -c \
  "import cv2, numpy, paddle, platform, torch, ultralytics; assert platform.machine() in {'aarch64','arm64'}; assert paddle.device.get_device() == 'cpu'; print({'machine': platform.machine(), 'torch': torch.__version__, 'paddle': paddle.__version__, 'opencv': cv2.__version__, 'ultralytics': ultralytics.__version__})"

install -d -m 0700 /etc/nutrilens
if [[ ! -f /etc/nutrilens/worker.env ]]; then
  install -m 0600 infrastructure/oci/worker.env.example /etc/nutrilens/worker.env
  echo "Created /etc/nutrilens/worker.env. Replace the placeholder token, then rerun." >&2
  exit 2
fi
if grep -q 'replace_with_' /etc/nutrilens/worker.env; then
  echo "Placeholder remains in /etc/nutrilens/worker.env; refusing to start." >&2
  exit 2
fi

install -m 0600 infrastructure/oci/worker-service.env.example /etc/nutrilens/worker-service.env
install -m 0644 infrastructure/oci/nutrilens-ai-worker.service /etc/systemd/system/nutrilens-ai-worker.service
systemctl daemon-reload
systemctl enable --now nutrilens-ai-worker.service

python3 - <<'PY'
import json
import time
import urllib.request

deadline = time.monotonic() + 240
while True:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3) as response:
            body = json.load(response)
        if response.status == 200 and body.get("status") == "ok":
            print(json.dumps(body, sort_keys=True))
            break
    except Exception:
        pass
    if time.monotonic() >= deadline:
        raise SystemExit("Worker did not become healthy within 240 seconds")
    time.sleep(3)
PY

docker image inspect nutrilens-ai-worker:oci-arm64 \
  --format '{{json .RepoDigests}} {{.Id}} {{.Architecture}} {{.Os}}'
