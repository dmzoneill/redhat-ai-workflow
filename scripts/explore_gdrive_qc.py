#!/usr/bin/env python3
"""Exploratory Google Drive API queries for QC data capture.

Validates data availability: lists user's Docs/Sheets/Slides this quarter,
checks revision history, and measures dataset volume.

Usage:
    python scripts/explore_gdrive_qc.py
"""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tool_modules.aa_gdrive.src.tools_basic import get_drive_service

GOOGLE_MIME_TYPES = {
    "application/vnd.google-apps.document": "Google Doc",
    "application/vnd.google-apps.spreadsheet": "Google Sheet",
    "application/vnd.google-apps.presentation": "Google Slides",
}

MIME_FILTER = " or ".join(f"mimeType='{m}'" for m in GOOGLE_MIME_TYPES)


def get_quarter_start() -> str:
    today = date.today()
    quarter = (today.month - 1) // 3 + 1
    quarter_starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
    m, d = quarter_starts[quarter]
    return date(today.year, m, d).isoformat() + "T00:00:00"


def explore_volume(service) -> dict:
    """Count total Google Docs/Sheets/Slides modified this quarter."""
    quarter_start = get_quarter_start()
    q = (
        f"({MIME_FILTER})"
        f" and modifiedTime >= '{quarter_start}'"
        f" and trashed = false"
    )

    total = 0
    page_token = None
    while True:
        resp = (
            service.files()
            .list(
                q=q,
                fields="nextPageToken, files(id)",
                pageSize=1000,
                pageToken=page_token,
            )
            .execute()
        )
        total += len(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    print(f"\n=== Dataset Volume ===")
    print(f"Total Google Docs/Sheets/Slides modified since {quarter_start}: {total}")
    return {"total_files": total, "quarter_start": quarter_start}


def explore_by_type(service) -> dict:
    """List files per MIME type with metadata."""
    quarter_start = get_quarter_start()
    results = {}

    for mime, label in GOOGLE_MIME_TYPES.items():
        q = (
            f"mimeType='{mime}'"
            f" and modifiedTime >= '{quarter_start}'"
            f" and trashed = false"
        )
        fields = (
            "files(id, name, mimeType, createdTime, modifiedTime, "
            "modifiedByMeTime, owners, lastModifyingUser, webViewLink)"
        )
        resp = (
            service.files()
            .list(
                q=q,
                fields=f"nextPageToken, {fields}",
                pageSize=50,
                orderBy="modifiedTime desc",
            )
            .execute()
        )
        files = resp.get("files", [])
        results[label] = files

        print(f"\n=== {label} (top {len(files)}) ===")
        for f in files[:10]:
            owners = [o.get("emailAddress", "?") for o in f.get("owners", [])]
            lm = f.get("lastModifyingUser", {}).get("emailAddress", "?")
            mbm = f.get("modifiedByMeTime", "n/a")
            print(f"  {f['name'][:60]:<60}")
            print(
                f"    created={f.get('createdTime','?')[:10]}  "
                f"modified={f.get('modifiedTime','?')[:10]}  "
                f"modifiedByMe={mbm[:10] if mbm != 'n/a' else 'n/a'}"
            )
            print(f"    owners={owners}  lastModifier={lm}")
        if len(files) > 10:
            print(f"  ... and {len(files) - 10} more")

    return results


def explore_revisions(service, file_id: str, file_name: str) -> dict:
    """Check revision history for a specific file."""
    print(f"\n=== Revisions for: {file_name} ===")
    try:
        resp = (
            service.revisions()
            .list(
                fileId=file_id,
                fields="revisions(id, modifiedTime, lastModifyingUser)",
                pageSize=200,
            )
            .execute()
        )
        revisions = resp.get("revisions", [])
        print(f"  Total revisions: {len(revisions)}")

        for rev in revisions[:5]:
            user = rev.get("lastModifyingUser", {})
            email = user.get("emailAddress", "?")
            name = user.get("displayName", "?")
            print(
                f"  rev {rev['id'][:8]}  "
                f"time={rev.get('modifiedTime','?')[:16]}  "
                f"by={name} ({email})"
            )
        if len(revisions) > 5:
            print(f"  ... and {len(revisions) - 5} more revisions")

        return {"file_id": file_id, "name": file_name, "revision_count": len(revisions)}
    except Exception as e:
        print(f"  ERROR: {e}")
        return {"file_id": file_id, "name": file_name, "error": str(e)}


def explore_user_info(service) -> dict:
    """Get current user info."""
    about = service.about().get(fields="user, storageQuota").execute()
    user = about.get("user", {})
    print(f"\n=== Authenticated User ===")
    print(f"  Name: {user.get('displayName')}")
    print(f"  Email: {user.get('emailAddress')}")
    return {"email": user.get("emailAddress"), "name": user.get("displayName")}


def main():
    service, error = get_drive_service()
    if error:
        print(f"ERROR: {error}")
        sys.exit(1)

    user_info = explore_user_info(service)
    volume = explore_volume(service)
    by_type = explore_by_type(service)

    sample_file = None
    for label, files in by_type.items():
        if files:
            sample_file = files[0]
            break

    rev_result = {}
    if sample_file:
        rev_result = explore_revisions(service, sample_file["id"], sample_file["name"])

    summary = {
        "user": user_info,
        "volume": volume,
        "counts_by_type": {k: len(v) for k, v in by_type.items()},
        "sample_revision": rev_result,
    }

    print(f"\n=== Summary ===")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
