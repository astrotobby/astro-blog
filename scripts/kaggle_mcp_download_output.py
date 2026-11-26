#!/usr/bin/env python3
"""Download one completed Kaggle notebook output through Kaggle's official MCP API.

This avoids the ListKernelSessionOutput endpoint used by `kaggle kernels output`,
which may be throttled independently from the direct per-file download endpoint.
The Kaggle API token is read only from KAGGLE_API_TOKEN and is never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

# Direct single-file output endpoint; avoids the throttled ListKernelSessionOutput call.
# Prefer direct MCP file retrieval over paginated session-output listing.
# Bounded response-body mode follows Kaggle's verified MCP client behavior.
# Parse one JSON-RPC event and close the stream without waiting for EOF.
# The collector runner checks out this script before invoking it.
MCP_URL = "https://www.kaggle.com/mcp"
TIMEOUT = 30
MAX_MCP_RETRIES = 2
MAX_MCP_RETRY_WAIT = 30


def _parse_rpc_response(response: requests.Response, request_id: int) -> dict[str, Any]:
    """Parse Kaggle's finite JSON or SSE response using the verified text-body pattern."""
    try:
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        candidates: list[dict[str, Any]] = []

        if "application/json" in content_type:
            payload = response.json()
            if isinstance(payload, dict):
                candidates.append(payload)
        else:
            for line in response.text.splitlines():
                if not line.startswith("data:"):
                    continue
                try:
                    payload = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    candidates.append(payload)

        for payload in candidates:
            if payload.get("id") == request_id or payload.get("id") == str(request_id):
                if payload.get("error"):
                    raise RuntimeError(f"Kaggle MCP JSON-RPC error: {payload['error']}")
                result = payload.get("result")
                if not isinstance(result, dict):
                    raise RuntimeError("Kaggle MCP returned no result object.")
                if result.get("isError") is True:
                    details = " ".join(
                        str(item.get("text", ""))
                        for item in result.get("content", [])
                        if isinstance(item, dict)
                    )
                    if "kernels.get" in details.lower() and "denied" in details.lower():
                        raise RuntimeError(
                            "Kaggle MCP authorization denied kernels.get. The current "
                            "KAGGLE_API_TOKEN is not accepted for this MCP permission. "
                            "Generate a new Kaggle API token beginning KGAT_ at "
                            "https://www.kaggle.com/settings, then replace the GitHub "
                            "Actions secret KAGGLE_API_TOKEN. Never paste the token into "
                            "chat or commit it to the repository."
                        )
                    raise RuntimeError(f"Kaggle MCP tool error: {details or 'unspecified error'}")
                return result

        raise RuntimeError(
            "Kaggle MCP response did not include the expected JSON-RPC result "
            f"(HTTP {response.status_code}, content-type={content_type!r})."
        )
    finally:
        response.close()

def _tool_call(
    session: requests.Session,
    token: str,
    request_id: int,
    name: str,
    request_args: dict[str, Any],
) -> dict[str, Any]:
    body = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": {"request": request_args},
        },
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    last_error: Exception | None = None
    for attempt in range(MAX_MCP_RETRIES + 1):
        response = session.post(
            MCP_URL,
            json=body,
            headers=headers,
            timeout=TIMEOUT,
            allow_redirects=False,
        )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "")
            try:
                delay = float(retry_after)
            except (TypeError, ValueError):
                delay = 2.0 * (attempt + 1)
            delay = max(0.0, min(delay, MAX_MCP_RETRY_WAIT))
            response.close()
            if attempt < MAX_MCP_RETRIES:
                print(
                    f"Kaggle MCP returned HTTP 429 for {name}; retrying in {delay:g}s "
                    f"({attempt + 1}/{MAX_MCP_RETRIES}).",
                    file=sys.stderr,
                )
                time.sleep(delay)
                continue
            raise RuntimeError(
                f"Kaggle MCP returned HTTP 429 for {name} after "
                f"{MAX_MCP_RETRIES + 1} attempts."
            )
        try:
            return _parse_rpc_response(response, request_id)
        except RuntimeError as exc:
            last_error = exc
            throttled = re.search(
                r"rate.?limit|too many requests|http 429", str(exc), re.I
            )
            if throttled and attempt < MAX_MCP_RETRIES:
                delay = min(2.0 * (attempt + 1), MAX_MCP_RETRY_WAIT)
                print(
                    f"Kaggle MCP tool {name} was throttled; retrying in {delay:g}s "
                    f"({attempt + 1}/{MAX_MCP_RETRIES}).",
                    file=sys.stderr,
                )
                time.sleep(delay)
                continue
            raise
    raise RuntimeError(f"Kaggle MCP tool {name} failed after retries: {last_error}")


def _result_value(result: dict[str, Any]) -> Any:
    structured = result.get("structuredContent")
    if structured is not None:
        return structured

    content = result.get("content")
    if isinstance(content, list):
        texts = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        parsed_values = []
        for text in texts:
            try:
                parsed_values.append(json.loads(text))
            except json.JSONDecodeError:
                continue
        if len(parsed_values) == 1:
            return parsed_values[0]
        if parsed_values:
            return parsed_values
        if texts:
            return "\\n".join(texts)
    return result


def _find_int(value: Any, keys: set[str]) -> int | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and isinstance(item, (int, float)) and int(item) > 0:
                return int(item)
        for item in value.values():
            found = _find_int(item, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_int(item, keys)
            if found is not None:
                return found
    return None


def _find_matching_output(value: Any, file_path: str) -> tuple[str | None, str | None]:
    """Find an exact output filename and its signed URL in Kaggle's session listing."""
    wanted = Path(file_path).name
    if isinstance(value, dict):
        name = next(
            (value.get(key) for key in ("fileName", "file_name", "name", "filename")
             if isinstance(value.get(key), str)),
            None,
        )
        url = next(
            (value.get(key) for key in ("url", "downloadUrl", "download_url")
             if isinstance(value.get(key), str) and value.get(key).startswith("https://")),
            None,
        )
        if name and Path(name).name == wanted and url:
            return str(name), url
        for item in value.values():
            found = _find_matching_output(item, file_path)
            if found[1]:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_matching_output(item, file_path)
            if found[1]:
                return found
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None:
            return _find_matching_output(parsed, file_path)
    return None, None


def _find_download_url(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {"url", "downloadurl", "download_url", "redirecturl", "redirect_url"} and isinstance(item, str):
                if item.startswith("https://"):
                    return item
        for item in value.values():
            found = _find_download_url(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_download_url(item)
            if found:
                return found
    elif isinstance(value, str):
        match = re.search(r"https://[^\s\"'<>]+", value)
        if match:
            return match.group(0).rstrip("),.;")
    return None


def download_output(kernel_ref: str, file_path: str, destination: Path) -> None:
    token = os.getenv("KAGGLE_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("KAGGLE_API_TOKEN is not configured.")
    token_kind = "KGAT_ bearer token" if token.startswith("KGAT_") else "legacy/unrecognized credential"
    print(f"Kaggle MCP credential format: {token_kind} (credential value hidden).")

    parts = kernel_ref.strip("/").split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError("kernel_ref must be owner/kernel-slug (without a version suffix).")
    owner, slug = parts

    destination.parent.mkdir(parents=True, exist_ok=True)
    with requests.Session() as session:
        # Prefer the session-output listing: it returns signed URLs for the exact
        # output without calling get_notebook_info / kernels.get. Some current
        # KGAT_ credentials can submit and inspect kernels through the CLI while
        # Kaggle MCP separately denies kernels.get permission.
        download_url = None
        version = None
        try:
            listing_result = _tool_call(
                session,
                token,
                1,
                "list_notebook_session_output",
                {"userName": owner, "kernelSlug": slug, "pageSize": 200},
            )
            listing = _result_value(listing_result)
            listed_name, download_url = _find_matching_output(listing, file_path)
            if download_url:
                print(f"Kaggle session listing located {listed_name}; using its signed file URL.")
            else:
                print(
                    "Kaggle session listing returned no exact file match; "
                    "trying the per-file download tool.",
                    file=sys.stderr,
                )
        except RuntimeError as exc:
            print(
                f"Kaggle session listing unavailable ({str(exc)[:200]}); "
                "trying the per-file download tool.",
                file=sys.stderr,
            )

        if not download_url:
            info_result = _tool_call(
                session,
                token,
                2,
                "get_notebook_info",
                {"userName": owner, "kernelSlug": slug},
            )
            info = _result_value(info_result)
            version = _find_int(
                info,
                {"currentVersionNumber", "current_version_number", "versionNumber", "version_number"},
            )
            if version is None:
                raise RuntimeError(
                    "Kaggle MCP did not return currentVersionNumber for the requested notebook."
                )

            output_result = _tool_call(
                session,
                token,
                3,
                "download_notebook_output",
                {
                    "ownerSlug": owner,
                    "kernelSlug": slug,
                    "filePath": file_path,
                    "versionNumber": version,
                },
            )
            output = _result_value(output_result)
            download_url = _find_download_url(output)
            if not download_url:
                raise RuntimeError(
                    "Kaggle MCP did not return a download URL for the requested output file."
                )

        with session.get(download_url, stream=True, timeout=TIMEOUT) as response:
            response.raise_for_status()
            temp = destination.with_suffix(destination.suffix + ".part")
            total = 0
            try:
                with temp.open("wb") as stream:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            stream.write(chunk)
                            total += len(chunk)
                if total < 100_000:
                    raise RuntimeError(f"Downloaded output is unexpectedly small ({total} bytes).")
                temp.replace(destination)
            except Exception:
                temp.unlink(missing_ok=True)
                raise

    print(json.dumps({
        "kernel": kernel_ref,
        "version": version,
        "file": file_path,
        "destination": str(destination),
        "bytes": total,
        "retrieval": "Kaggle MCP direct file download",
    }, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel-ref", required=True)
    parser.add_argument("--file-path", default="musetalk_preview.mp4")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        download_output(args.kernel_ref, args.file_path, args.output)
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2 if "authorization denied kernels.get" in str(exc).lower() else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
