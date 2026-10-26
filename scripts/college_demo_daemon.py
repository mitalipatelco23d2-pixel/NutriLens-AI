import json
import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

qa_env_file = Path("/home/yash0/projects/nutrilens-x/reports/recovery/private-local-qa-env.json")
if qa_env_file.exists():
    try:
        qa_env = json.loads(qa_env_file.read_text())
        for k, v in qa_env.items():
            if k not in os.environ:
                os.environ[k] = str(v)
    except Exception:
        pass

import uvicorn  # noqa: E402

if __name__ == "__main__":
    os.environ["APP_ENVIRONMENT"] = "development"
    os.environ["COLLEGE_DEMO_MODE"] = "true"
    os.environ["PERSISTENCE_BACKEND"] = "postgres"
    os.environ["RATE_LIMIT_BACKEND"] = "memory"
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, log_level="info")
