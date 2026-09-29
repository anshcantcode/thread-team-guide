"""Check literal qualification; unimplemented engineering/artifact gates stay unmet."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thread_agent.fdb3_evidence import verify_series

parser = argparse.ArgumentParser()
parser.add_argument("--series", type=Path, required=True)
args = parser.parse_args()
try:
    result = verify_series(json.loads(args.series.read_text(encoding="utf-8")), args.series.parent)
except (OSError, ValueError, TypeError) as exc:
    result = {"passed":False,"errors":[type(exc).__name__ + ": " + str(exc)]}
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["passed"] else 1)
