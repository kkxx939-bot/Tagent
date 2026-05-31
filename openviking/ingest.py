from __future__ import annotations

import argparse
import json
import mimetypes
import os
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
SOURCE_DIRS = {
    "requirement": DATA_DIR / "requirements",
    "case": DATA_DIR / "test_cases",
    "bug": DATA_DIR / "bugs",
    "api": DATA_DIR / "api_docs",
}
DEFAULT_TARGET_ROOT = "viking://resources/tagent"


def main() -> int:
    args = parse_args()
    files = collect_files(args.source_type)
    if args.limit:
        files = files[: args.limit]

    if args.dry_run:
        print(json.dumps(build_dry_run(files, args), ensure_ascii=False, indent=2))
        return 0

    if not args.url:
        print(json.dumps({"success": False, "error": "missing_openviking_url"}, ensure_ascii=False, indent=2))
        return 2

    results = ingest_files(files, args)
    output = {
        "success": all(item["success"] for item in results),
        "url": args.url,
        "target_root": args.target_root,
        "wait": args.wait,
        "total": len(results),
        "succeeded": sum(1 for item in results if item["success"]),
        "failed": sum(1 for item in results if not item["success"]),
        "results": results,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["success"] else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把 Tagent 本地资料导入 OpenViking。")
    parser.add_argument("--url", default=os.getenv("OPENVIKING_URL", "").strip())
    parser.add_argument("--api-key", default=os.getenv("OPENVIKING_API_KEY", ""))
    parser.add_argument("--target-root", default=os.getenv("OPENVIKING_TARGET_ROOT", DEFAULT_TARGET_ROOT))
    parser.add_argument("--account", default=os.getenv("OPENVIKING_ACCOUNT", ""))
    parser.add_argument("--user", default=os.getenv("OPENVIKING_USER", ""))
    parser.add_argument("--agent-id", default=os.getenv("OPENVIKING_AGENT_ID", ""))
    parser.add_argument("--source-type", choices=["all", *SOURCE_DIRS.keys()], default="all")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--timeout", type=float, default=float(os.getenv("OPENVIKING_TIMEOUT", "120")))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "result/openviking_ingest_result.json")
    args = parser.parse_args()
    if not args.execute:
        args.dry_run = True
    return args


def collect_files(source_type: str) -> list[tuple[str, Path]]:
    selected = SOURCE_DIRS.items() if source_type == "all" else [(source_type, SOURCE_DIRS[source_type])]
    files: list[tuple[str, Path]] = []
    for item_type, directory in selected:
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and not path.name.startswith("."):
                files.append((item_type, path))
    return files


def build_dry_run(files: list[tuple[str, Path]], args: argparse.Namespace) -> dict[str, Any]:
    return {
        "dry_run": True,
        "url_configured": bool(args.url),
        "target_root": args.target_root,
        "total": len(files),
        "files": [
            {
                "source_type": source_type,
                "path": str(path),
                "target_uri": target_uri(args.target_root, source_type, path),
            }
            for source_type, path in files
        ],
    }


def ingest_files(files: list[tuple[str, Path]], args: argparse.Namespace) -> list[dict[str, Any]]:
    results = []
    for source_type, path in files:
        try:
            temp_file_id = upload_temp_file(path, args)
            response = add_resource(temp_file_id, source_type, path, args)
            results.append(
                {
                    "source_type": source_type,
                    "path": str(path),
                    "success": True,
                    "temp_file_id": temp_file_id,
                    "response": response,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "source_type": source_type,
                    "path": str(path),
                    "success": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            if args.stop_on_error:
                break
    return results


def upload_temp_file(path: Path, args: argparse.Namespace) -> str:
    with path.open("rb") as file_obj:
        response = request_json(
            "POST",
            f"{args.url.rstrip('/')}/api/v1/resources/temp_upload",
            args,
            files={"file": (path.name, file_obj, mimetypes.guess_type(path.name)[0] or "application/octet-stream")},
        )
    result = response.get("result") if isinstance(response, dict) else {}
    temp_file_id = result.get("temp_file_id") if isinstance(result, dict) else None
    if not temp_file_id:
        raise RuntimeError(f"OpenViking temp_upload 未返回 temp_file_id: {response}")
    return str(temp_file_id)


def add_resource(temp_file_id: str, source_type: str, path: Path, args: argparse.Namespace) -> dict[str, Any]:
    payload = {
        "temp_file_id": temp_file_id,
        "to": target_uri(args.target_root, source_type, path),
        "create_parent": True,
        "reason": f"Tagent {source_type} source import",
        "wait": args.wait,
        "timeout": args.timeout if args.wait else None,
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    return request_json("POST", f"{args.url.rstrip('/')}/api/v1/resources", args, json_body=payload)


def request_json(
    method: str,
    url: str,
    args: argparse.Namespace,
    *,
    json_body: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = requests.request(
        method,
        url,
        headers=auth_headers(args),
        json=json_body,
        files=files,
        timeout=args.timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(response.text or f"HTTP {response.status_code}")
    data = response.json()
    if isinstance(data, dict) and data.get("status") == "error":
        raise RuntimeError(json.dumps(data.get("error") or data, ensure_ascii=False))
    return data


def auth_headers(args: argparse.Namespace) -> dict[str, str]:
    headers: dict[str, str] = {}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"
        headers["X-API-Key"] = args.api_key
    if args.account:
        headers["X-OpenViking-Account"] = args.account
    if args.user:
        headers["X-OpenViking-User"] = args.user
    if args.agent_id:
        headers["X-OpenViking-Agent"] = args.agent_id
    return headers


def target_uri(root: str, source_type: str, path: Path) -> str:
    safe_name = path.name.replace(" ", "_")
    return f"{root.rstrip('/')}/{source_type}/{safe_name}"


if __name__ == "__main__":
    raise SystemExit(main())
