#!/usr/bin/env python3
"""Explore the Ansible org shared drive for QC peer data capture.

Investigates:
1. Drive type (Shared Drive vs shared folder)
2. File volume this quarter (Docs/Sheets/Slides)
3. Unique contributors (owners, last modifiers)
4. Revision history with per-user attribution
5. Subfolder structure

Usage:
    python scripts/explore_shared_drive.py
"""

import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tool_modules.aa_gdrive.src.tools_basic import get_drive_service

SHARED_DRIVE_ID = "0AAeigat9qAfFUk9PVA"
QUARTER_START = "2026-01-01T00:00:00"

GOOGLE_MIME_TYPES = {
    "application/vnd.google-apps.document": "Doc",
    "application/vnd.google-apps.spreadsheet": "Sheet",
    "application/vnd.google-apps.presentation": "Slides",
}


def explore_drive_info(service):
    """Check if the ID is a Shared Drive (Team Drive)."""
    print("=== Drive Info ===")
    try:
        drive = (
            service.drives()
            .get(
                driveId=SHARED_DRIVE_ID,
                fields="id, name, kind, createdTime",
            )
            .execute()
        )
        print(f"  Type: Shared Drive (Team Drive)")
        print(f"  Name: {drive.get('name')}")
        print(f"  ID: {drive.get('id')}")
        print(f"  Created: {drive.get('createdTime', '?')[:10]}")
        return "shared_drive"
    except Exception as e:
        print(f"  Not a Shared Drive ({e})")
        try:
            folder = (
                service.files()
                .get(
                    fileId=SHARED_DRIVE_ID,
                    fields="id, name, mimeType, owners",
                    supportsAllDrives=True,
                )
                .execute()
            )
            print(f"  Type: Shared Folder")
            print(f"  Name: {folder.get('name')}")
            owners = [o.get("emailAddress", "?") for o in folder.get("owners", [])]
            print(f"  Owners: {owners}")
            return "folder"
        except Exception as e2:
            print(f"  Also not a folder: {e2}")
            return "unknown"


def explore_top_folders(service, drive_type):
    """List top-level folders."""
    print("\n=== Top-Level Folders ===")
    kwargs = {
        "q": f"'{SHARED_DRIVE_ID}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        "fields": "files(id, name, modifiedTime)",
        "pageSize": 50,
        "orderBy": "name",
    }
    if drive_type == "shared_drive":
        kwargs["corpora"] = "drive"
        kwargs["driveId"] = SHARED_DRIVE_ID
        kwargs["includeItemsFromAllDrives"] = True
        kwargs["supportsAllDrives"] = True

    resp = service.files().list(**kwargs).execute()
    folders = resp.get("files", [])
    for f in folders:
        print(f"  {f['name']:<50} modified={f.get('modifiedTime', '?')[:10]}")
    print(f"  Total: {len(folders)} folders")
    return folders


def explore_quarter_files(service, drive_type):
    """Count and analyze Docs/Sheets/Slides modified this quarter."""
    print(f"\n=== Files Modified Since {QUARTER_START[:10]} ===")

    mime_filter = " or ".join(f"mimeType='{m}'" for m in GOOGLE_MIME_TYPES)
    q = (
        f"({mime_filter})"
        f" and modifiedTime >= '{QUARTER_START}'"
        f" and trashed = false"
    )

    kwargs = {
        "q": q,
        "fields": (
            "nextPageToken, files(id, name, mimeType, createdTime, modifiedTime, "
            "modifiedByMeTime, owners, lastModifyingUser, webViewLink)"
        ),
        "pageSize": 500,
        "orderBy": "modifiedTime desc",
    }
    if drive_type == "shared_drive":
        kwargs["corpora"] = "drive"
        kwargs["driveId"] = SHARED_DRIVE_ID
        kwargs["includeItemsFromAllDrives"] = True
        kwargs["supportsAllDrives"] = True

    all_files = []
    page_token = None
    while True:
        if page_token:
            kwargs["pageToken"] = page_token
        resp = service.files().list(**kwargs).execute()
        files = resp.get("files", [])
        all_files.extend(files)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    type_counts = Counter()
    owner_counts = Counter()
    modifier_counts = Counter()
    my_edits = []
    contributors = set()

    for f in all_files:
        mime = f.get("mimeType", "")
        label = GOOGLE_MIME_TYPES.get(mime, "Other")
        type_counts[label] += 1

        for o in f.get("owners", []):
            email = o.get("emailAddress", "?")
            owner_counts[email] += 1
            contributors.add(email)

        lm = f.get("lastModifyingUser", {})
        lm_email = lm.get("emailAddress", "?")
        if lm_email != "?":
            modifier_counts[lm_email] += 1
            contributors.add(lm_email)

        if f.get("modifiedByMeTime"):
            my_edits.append(f)

    print(f"\n  Total files: {len(all_files)}")
    print(f"  By type:")
    for t, c in type_counts.most_common():
        print(f"    {t}: {c}")

    print(f"\n  Unique contributors: {len(contributors)}")
    print(f"  Top 15 file owners:")
    for email, c in owner_counts.most_common(15):
        print(f"    {email:<40} {c} files")

    print(f"\n  Top 15 last modifiers:")
    for email, c in modifier_counts.most_common(15):
        print(f"    {email:<40} {c} files")

    print(f"\n  Files I edited this quarter: {len(my_edits)}")
    for f in my_edits[:5]:
        print(f"    {f['name'][:60]}")

    return all_files, contributors


def explore_revisions_sample(service, files, drive_type):
    """Check revision history for a few files to see per-user attribution."""
    print("\n=== Revision History Samples ===")

    samples = files[:5]
    all_revision_users = Counter()

    for f in samples:
        fid = f["id"]
        name = f["name"][:50]
        print(f"\n  {name}")
        try:
            kwargs = {
                "fileId": fid,
                "fields": "revisions(id, modifiedTime, lastModifyingUser)",
                "pageSize": 200,
            }
            resp = service.revisions().list(**kwargs).execute()
            revisions = resp.get("revisions", [])

            rev_users = Counter()
            quarter_revs = 0
            for rev in revisions:
                user = rev.get("lastModifyingUser", {})
                email = user.get("emailAddress", "?")
                rev_time = rev.get("modifiedTime", "")
                if rev_time >= QUARTER_START:
                    rev_users[email] += 1
                    quarter_revs += 1
                    all_revision_users[email] += 1

            print(
                f"    Total revisions: {len(revisions)}, this quarter: {quarter_revs}"
            )
            for email, c in rev_users.most_common(5):
                print(f"      {email:<40} {c} revisions")
        except Exception as e:
            print(f"    Error: {e}")

    print(f"\n  Aggregate revision contributors (sample):")
    for email, c in all_revision_users.most_common(15):
        print(f"    {email:<40} {c} revisions")

    return all_revision_users


def check_peer_overlap(contributors):
    """Check how many peer roster members appear in the shared drive."""
    print("\n=== Peer Roster Overlap ===")
    try:
        roster_path = (
            Path.home() / ".config/aa-workflow/performance/org/org_roster.json"
        )
        if not roster_path.exists():
            print("  No org_roster.json found")
            return

        with open(roster_path) as f:
            roster = json.load(f)

        peer_usernames = set()
        peer_emails = set()
        for level, plist in roster.get("peers", {}).items():
            for p in plist:
                uname = p.get("username", "")
                peer_usernames.add(uname)
                if uname:
                    peer_emails.add(f"{uname}@redhat.com")

        contributor_lower = {c.lower() for c in contributors}
        overlap = peer_emails & contributor_lower

        print(f"  Total peers in roster: {len(peer_usernames)}")
        print(f"  Total unique contributors in shared drive: {len(contributors)}")
        print(f"  Peers found as contributors: {len(overlap)}")
        if overlap:
            for email in sorted(overlap):
                print(f"    {email}")
    except Exception as e:
        print(f"  Error: {e}")


def main():
    service, error = get_drive_service()
    if error:
        print(f"ERROR: {error}")
        sys.exit(1)

    drive_type = explore_drive_info(service)
    explore_top_folders(service, drive_type)
    files, contributors = explore_quarter_files(service, drive_type)

    if files:
        explore_revisions_sample(service, files, drive_type)

    check_peer_overlap(contributors)

    print("\n=== Summary ===")
    print(
        json.dumps(
            {
                "drive_type": drive_type,
                "drive_id": SHARED_DRIVE_ID,
                "total_files_this_quarter": len(files),
                "unique_contributors": len(contributors),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
