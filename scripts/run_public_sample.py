"""Send one or all organizer public samples to a running GridWise API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_FILE = ROOT / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--case", default="SAMPLE-01")
    parser.add_argument("--all", action="store_true")
    return parser.parse_args()


def _post(base_url: str, payload: dict) -> dict:
    request = Request(
        f"{base_url.rstrip('/')}/optimize-energy",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def _semantics(entries: list[dict]) -> list[dict]:
    keys = ("note_index", "applies", "directive_type", "structured_adjustment")
    return [{key: entry[key] for key in keys} for entry in entries]


def main() -> int:
    args = _arguments()
    cases = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))["cases"]
    selected = cases if args.all else [case for case in cases if case["id"] == args.case]
    if not selected:
        raise SystemExit(f"Unknown sample case: {args.case}")

    for case in selected:
        try:
            body = _post(args.base_url, case["input"])
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            print(f"{case['id']}: HTTP {exc.code}: {detail}")
            return 1
        except URLError as exc:
            print(f"{case['id']}: endpoint unavailable: {exc.reason}")
            return 1

        if body.get("scenario_id") != case["input"]["scenario_id"]:
            print(f"{case['id']}: invalid scenario_id echo")
            return 1
        expected = case["expected_output"]
        if _semantics(body["directive_interpretation"]) != _semantics(
            expected["directive_interpretation"]
        ):
            print(f"{case['id']}: directive interpretation mismatch")
            return 1
        for field in ("total_cost_bdt", "total_grid_kwh", "peak_grid_kwh"):
            if abs(float(body[field]) - float(expected[field])) > 0.01:
                print(
                    f"{case['id']}: {field}={body[field]} does not match "
                    f"expected {expected[field]}"
                )
                return 1
        print(
            f"{case['id']}: PASS, cost={body['total_cost_bdt']}, "
            f"grid={body['total_grid_kwh']}, peak={body['peak_grid_kwh']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
