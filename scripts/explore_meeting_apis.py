#!/usr/bin/env python3
"""Explore Calendar attendees + Meet conference records for QC data capture.

Tests:
1. Calendar API: events with attendee RSVP data
2. Meet API: conference records with actual participants
3. Linking: Calendar event -> Meet conference record
"""

import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TOKEN_FILE = Path.home() / ".config/google-calendar/token.json"
QUARTER_START = "2026-01-01T00:00:00Z"
TZ = ZoneInfo("Europe/Dublin")


def get_credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    with open("config.json") as f:
        cfg = json.load(f)
    scopes = cfg["google"]["oauth_scopes"]

    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


def explore_calendar_attendees(creds):
    """Get events with attendee RSVP data from Calendar API."""
    from googleapiclient.discovery import build

    print("=== Calendar API: Events with Attendees ===")
    service = build("calendar", "v3", credentials=creds)

    now = datetime.now(TZ)
    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=QUARTER_START,
            timeMax=now.isoformat(),
            maxResults=500,
            singleEvents=True,
            orderBy="startTime",
            fields=(
                "items(id,summary,start,end,organizer,attendees,"
                "conferenceData,status,creator,recurringEventId)"
            ),
        )
        .execute()
    )

    events = events_result.get("items", [])

    total = len(events)
    with_attendees = 0
    with_meet = 0
    organizer_count = Counter()
    attendee_count = Counter()
    rsvp_counts = Counter()
    meeting_types = Counter()
    my_organized = 0

    for ev in events:
        attendees = ev.get("attendees", [])
        if attendees:
            with_attendees += 1

        conf = ev.get("conferenceData", {})
        if conf.get("conferenceSolution", {}).get("name") == "Google Meet":
            with_meet += 1

        org_email = ev.get("organizer", {}).get("email", "?")
        organizer_count[org_email] += 1
        if "daoneill" in org_email:
            my_organized += 1

        for att in attendees:
            email = att.get("email", "?")
            status = att.get("responseStatus", "needsAction")
            attendee_count[email] += 1
            rsvp_counts[status] += 1

        summary = (ev.get("summary", "") or "").lower()
        if "standup" in summary or "scrum" in summary:
            meeting_types["standup"] += 1
        elif "sprint" in summary:
            meeting_types["sprint_ceremony"] += 1
        elif "1:1" in summary or "1-1" in summary:
            meeting_types["one_on_one"] += 1
        elif "demo" in summary or "review" in summary:
            meeting_types["demo_review"] += 1
        elif "planning" in summary:
            meeting_types["planning"] += 1
        elif "retro" in summary:
            meeting_types["retro"] += 1
        elif "interview" in summary:
            meeting_types["interview"] += 1
        else:
            meeting_types["other"] += 1

    print(f"\n  Total events this quarter: {total}")
    print(f"  Events with attendees: {with_attendees}")
    print(f"  Events with Google Meet: {with_meet}")
    print(f"  I organized: {my_organized}")

    print(f"\n  RSVP distribution:")
    for status, count in rsvp_counts.most_common():
        print(f"    {status}: {count}")

    print(f"\n  Meeting type classification:")
    for mtype, count in meeting_types.most_common():
        print(f"    {mtype}: {count}")

    print(f"\n  Top 10 co-attendees:")
    for email, count in attendee_count.most_common(10):
        print(f"    {email:<45} {count} meetings")

    print(f"\n  Top 10 organizers:")
    for email, count in organizer_count.most_common(10):
        print(f"    {email:<45} {count} meetings")

    # Sample: show a few events with attendee details
    print(f"\n  Sample events:")
    samples = [e for e in events if e.get("attendees")][:3]
    for ev in samples:
        print(f"\n  '{ev.get('summary', '?')}'")
        print(f"    Organizer: {ev.get('organizer', {}).get('email', '?')}")
        conf = ev.get("conferenceData", {})
        meet_uri = ""
        for ep in conf.get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                meet_uri = ep.get("uri", "")
                break
        if meet_uri:
            print(f"    Meet link: {meet_uri}")
        for att in ev.get("attendees", [])[:5]:
            print(f"    {att.get('email', '?'):<40} {att.get('responseStatus', '?')}")

    return events


def explore_meet_api(creds):
    """Get conference records with actual participant data from Meet API."""
    from googleapiclient.discovery import build

    print("\n\n=== Meet API: Conference Records ===")
    try:
        service = build("meet", "v2", credentials=creds)
    except Exception as e:
        print(f"  ERROR building Meet service: {e}")
        return []

    try:
        response = (
            service.conferenceRecords()
            .list(
                filter=f'start_time>="{QUARTER_START}"',
                pageSize=100,
            )
            .execute()
        )
    except Exception as e:
        print(f"  ERROR listing conference records: {e}")
        print(f"  (Make sure Google Meet API is enabled in Cloud Console)")
        return []

    records = response.get("conferenceRecords", [])
    print(f"  Conference records this quarter: {len(records)}")

    if not records:
        print("  No records found. This may mean:")
        print("  - Meet API is not enabled")
        print("  - You haven't organized any meetings")
        print("  - Conference records are only available for meetings you organized")
        return []

    # Sample a few records and get participants
    participant_counts = Counter()
    total_participants = 0

    for rec in records[:10]:
        rec_name = rec.get("name", "")
        space = rec.get("space", "")
        start = rec.get("startTime", "?")
        end = rec.get("endTime", "?")

        print(f"\n  Record: {rec_name}")
        print(f"    Space: {space}")
        print(f"    Time: {start[:19]} -> {end[:19] if end != '?' else 'ongoing'}")

        try:
            parts_resp = (
                service.conferenceRecords()
                .participants()
                .list(
                    parent=rec_name,
                    pageSize=250,
                )
                .execute()
            )
            participants = parts_resp.get("participants", [])
            print(f"    Participants: {len(participants)}")
            total_participants += len(participants)

            for p in participants[:5]:
                user = p.get("signedinUser", {})
                display = user.get("displayName", "?")
                user_id = user.get("user", "?")
                earliest = p.get("earliestStartTime", "?")
                latest = p.get("latestEndTime", "?")
                print(
                    f"      {display:<30} joined={earliest[:19]} left={latest[:19] if latest != '?' else '?'}"
                )
                if display != "?":
                    participant_counts[display] += 1
        except Exception as e:
            print(f"    Error getting participants: {e}")

    print(f"\n  Total participants across sampled records: {total_participants}")
    if participant_counts:
        print(f"  Top participants:")
        for name, count in participant_counts.most_common(10):
            print(f"    {name:<40} {count} meetings")

    return records


def explore_calendar_meet_link(creds, events):
    """Try linking Calendar events to Meet conference records."""
    from googleapiclient.discovery import build

    print("\n\n=== Calendar <-> Meet Linking ===")
    service = build("meet", "v2", credentials=creds)

    linked = 0
    for ev in events[:20]:
        conf = ev.get("conferenceData", {})
        meet_code = ""
        for ep in conf.get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                uri = ep.get("uri", "")
                # Extract meeting code from URL like https://meet.google.com/abc-defg-hij
                if "meet.google.com/" in uri:
                    meet_code = uri.split("meet.google.com/")[-1].split("?")[0]
                break

        if not meet_code:
            continue

        try:
            resp = (
                service.conferenceRecords()
                .list(
                    filter=f'space.meeting_code="{meet_code}"',
                    pageSize=5,
                )
                .execute()
            )
            records = resp.get("conferenceRecords", [])
            if records:
                linked += 1
                if linked <= 3:
                    print(
                        f"\n  '{ev.get('summary', '?')}' -> {len(records)} conference record(s)"
                    )
                    for rec in records[:1]:
                        parts = (
                            service.conferenceRecords()
                            .participants()
                            .list(
                                parent=rec["name"],
                                pageSize=50,
                            )
                            .execute()
                            .get("participants", [])
                        )
                        att_count = len(ev.get("attendees", []))
                        print(
                            f"    Calendar attendees: {att_count}, Meet participants: {len(parts)}"
                        )
        except Exception:
            pass

    print(f"\n  Successfully linked {linked} events to Meet records")


def main():
    creds = get_credentials()
    events = explore_calendar_attendees(creds)
    records = explore_meet_api(creds)
    if events:
        explore_calendar_meet_link(creds, events)

    print("\n\n=== Summary ===")
    print(
        json.dumps(
            {
                "calendar_events_this_quarter": len(events),
                "meet_conference_records": len(records),
                "approach_1_calendar": "Available - RSVP data, attendee emails, organizer",
                "approach_2_meet": (
                    "Available" if records else "May need Meet API enabled"
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
