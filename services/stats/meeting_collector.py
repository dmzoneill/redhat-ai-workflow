"""Meeting attendance collector for QC data capture.

Collects meeting participation data from two sources:
  1. Google Calendar API: event metadata, attendee RSVPs, organizer info
  2. Google Meet API: actual participant join/leave times from conference records

Produces events for the QC scoring pipeline that map to competencies like
mentorship, leadership, speaking_publicity, planning_execution, and collaboration.

Meeting classification uses event title pattern matching similar to
gdrive_collector's filename classification.
"""

import json
import logging
import time
from datetime import date, datetime
from pathlib import Path

from services.stats.quarter_utils import QUARTER_STARTS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Meeting Title Classification
# ---------------------------------------------------------------------------

MEETING_CLASSIFICATION_RULES: list[tuple[list[str], str, list[str]]] = [
    (
        ["standup", "scrum", "daily sync", "daily check"],
        "standup",
        ["planning_execution"],
    ),
    (
        [
            "sprint planning",
            "backlog refinement",
            "backlog grooming",
            "sprint plan",
            "capacity planning",
        ],
        "sprint_planning",
        ["planning_execution", "leadership"],
    ),
    (
        [
            "sprint review",
            "sprint demo",
            "demo day",
            "show and tell",
            "show & tell",
            "showcase",
        ],
        "sprint_review",
        ["speaking_publicity", "evidence_record"],
    ),
    (
        ["retrospective", "retro", "post-mortem", "postmortem", "lessons learned"],
        "retrospective",
        ["continuous_improvement"],
    ),
    (
        [
            "1:1",
            "1-1",
            "1 on 1",
            "one on one",
            "catch up with",
            "check in with",
            "check-in with",
        ],
        "one_on_one",
        ["mentorship", "leadership"],
    ),
    (
        [
            "architecture",
            "design review",
            "arch review",
            "adr",
            "technical design",
            "rfc review",
        ],
        "architecture_review",
        ["technical_knowledge", "creativity_innovation"],
    ),
    (
        ["interview", "hiring", "debrief"],
        "interview",
        ["mentorship", "leadership"],
    ),
    (
        [
            "onboarding",
            "newcomer",
            "ramp-up",
            "ramp up",
            "orientation",
            "brown bag",
            "lunch and learn",
            "knowledge share",
            "workshop",
            "training",
        ],
        "training",
        ["mentorship", "technical_knowledge"],
    ),
    (
        [
            "incident",
            "outage",
            "war room",
            "sev1",
            "sev2",
            "p1",
            "p2",
            "escalation",
            "bridge",
        ],
        "incident_response",
        ["continuous_improvement", "technical_knowledge"],
    ),
    (
        [
            "all-hands",
            "all hands",
            "town hall",
            "org meeting",
            "team meeting",
            "staff meeting",
        ],
        "all_hands",
        ["scope"],
    ),
    (
        [
            "planning",
            "roadmap",
            "strategy",
            "okr",
            "quarterly",
            "initiative",
            "prioriti",
        ],
        "planning",
        ["planning_execution", "leadership"],
    ),
    (
        [
            "customer",
            "stakeholder",
            "partner",
            "vendor",
            "external",
            "field",
            "account",
        ],
        "customer_meeting",
        ["customer_focus"],
    ),
    (
        [
            "sig ",
            "sig-",
            "community",
            "working group",
            "cross-team",
            "cross team",
            "guild",
        ],
        "cross_team",
        ["scope", "collaboration"],
    ),
    (
        ["demo", "presentation", "talk", "lightning"],
        "presentation",
        ["speaking_publicity"],
    ),
    (
        ["code review", "pair program", "mob program", "pairing"],
        "code_review",
        ["technical_knowledge", "mentorship"],
    ),
]


def classify_meeting(title: str) -> tuple[str, list[str]]:
    """Classify a meeting by its title. Returns (classification, competency_ids)."""
    lower = (title or "").lower()
    for patterns, classification, competencies in MEETING_CLASSIFICATION_RULES:
        for pattern in patterns:
            if pattern in lower:
                return classification, competencies
    return "general_meeting", ["evidence_record"]


_CLASSIFICATION_BOOST = {
    "standup": "standup scrum daily sync agile ceremony",
    "sprint_planning": "sprint planning capacity backlog agile ceremony",
    "sprint_review": "sprint review demo showcase presentation agile ceremony",
    "retrospective": "retro retrospective improvement process agile ceremony",
    "one_on_one": "mentorship coaching leadership one-on-one feedback",
    "architecture_review": "architecture design review technical documentation",
    "interview": "interview hiring talent mentorship leadership",
    "training": "training onboarding mentorship knowledge sharing workshop",
    "incident_response": "incident response operations troubleshooting",
    "all_hands": "all-hands organization leadership team communication",
    "planning": "planning roadmap strategy leadership execution",
    "customer_meeting": "customer stakeholder engagement feedback",
    "cross_team": "cross-team collaboration scope community working group",
    "presentation": "presentation demo speaking talk slides",
    "code_review": "code review mentorship technical knowledge sharing",
    "general_meeting": "meeting collaboration team",
}


# ---------------------------------------------------------------------------
# Rate limiting (shared with gdrive_collector style)
# ---------------------------------------------------------------------------

_MIN_REQUEST_INTERVAL = 0.1
_last_request_time = 0.0


def _rate_limit():
    global _last_request_time
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.monotonic()


def _api_call_with_backoff(call_fn, max_retries: int = 3):
    """Execute a Google API call with exponential backoff on 429/5xx errors."""
    for attempt in range(max_retries + 1):
        try:
            _rate_limit()
            return call_fn()
        except Exception as e:
            err_str = str(e)
            is_retryable = "429" in err_str or "500" in err_str or "503" in err_str
            if not is_retryable or attempt >= max_retries:
                raise
            wait = (2**attempt) + 0.5
            logger.debug(
                "API rate limited (attempt %d/%d), waiting %.1fs: %s",
                attempt + 1,
                max_retries,
                wait,
                err_str[:100],
            )
            time.sleep(wait)
    return None


# ---------------------------------------------------------------------------
# Calendar API: Attendee/RSVP Collection
# ---------------------------------------------------------------------------


def _get_qc_calendar_ids() -> list[dict]:
    """Read QC calendar configs from config.json."""
    try:
        config_path = Path(__file__).resolve().parent.parent.parent / "config.json"
        if not config_path.exists():
            return [{"id": "primary", "name": "Personal"}]
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        cals = config.get("google", {}).get("qc_calendars", [])
        return cals if cals else [{"id": "primary", "name": "Personal"}]
    except Exception as e:
        logger.warning("Reading QC calendar config from config.json: %s", e)
        return [{"id": "primary", "name": "Personal"}]


def _get_peer_calendar_ids() -> list[dict]:
    """Read additional peer calendar configs for broader meeting coverage.

    These are org-wide or team calendars that the user has read access to
    and that contain meetings peers attend but the primary user may not.
    This improves peer meeting coverage beyond just the primary user's
    calendar overlap.

    Config: google.peer_calendars in config.json
    Format: same as qc_calendars -- [{id, name, description}]
    """
    try:
        config_path = Path(__file__).resolve().parent.parent.parent / "config.json"
        if not config_path.exists():
            return []
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        return config.get("google", {}).get("peer_calendars", [])
    except Exception as e:
        logger.warning("Reading peer calendar config from config.json: %s", e)
        return []


def collect_calendar_meetings(
    service,
    quarter_start: str,
    quarter_end: str,
    user_email: str,
    calendar_ids: list[dict] | None = None,
) -> list[dict]:
    """Collect meetings with attendee data from one or more Calendar APIs.

    Queries each configured calendar and deduplicates by event ID.
    """
    if calendar_ids is None:
        calendar_ids = _get_qc_calendar_ids()

    all_events: list[dict] = []
    seen_event_ids: set[str] = set()

    for cal_config in calendar_ids:
        cal_id = cal_config["id"]
        cal_name = cal_config.get("name", cal_id)
        cal_events = _collect_single_calendar(
            service,
            cal_id,
            cal_name,
            quarter_start,
            quarter_end,
            user_email,
        )
        for ev in cal_events:
            eid = ev["id"]
            if eid not in seen_event_ids:
                seen_event_ids.add(eid)
                all_events.append(ev)

    logger.info(
        "Calendar meetings: %d events across %d calendars (quarter %s)",
        len(all_events),
        len(calendar_ids),
        quarter_start[:10],
    )
    return all_events


def _collect_single_calendar(
    service,
    calendar_id: str,
    calendar_name: str,
    quarter_start: str,
    quarter_end: str,
    user_email: str,
) -> list[dict]:
    """Collect meetings from a single calendar."""
    is_shared = calendar_id != "primary"
    cal_events: list[dict] = []
    page_token = None

    while True:
        kwargs = {
            "calendarId": calendar_id,
            "timeMin": quarter_start,
            "timeMax": quarter_end,
            "maxResults": 250,
            "singleEvents": True,
            "orderBy": "startTime",
            "fields": (
                "nextPageToken,"
                "items(id,summary,start,end,organizer,creator,attendees,"
                "conferenceData,status,recurringEventId)"
            ),
        }
        if page_token:
            kwargs["pageToken"] = page_token

        resp = _api_call_with_backoff(
            lambda _kw=kwargs: service.events().list(**_kw).execute()
        )
        items = resp.get("items", [])

        for ev in items:
            attendees = ev.get("attendees", [])
            if not attendees and not is_shared:
                continue

            title = ev.get("summary", "") or ""
            classification, competencies = classify_meeting(title)

            organizer_email = ev.get("organizer", {}).get("email", "").lower()
            creator_email = ev.get("creator", {}).get("email", "").lower()
            user_lower = user_email.lower()
            is_organizer = user_lower == organizer_email or user_lower == creator_email

            accepted = []
            declined = []
            tentative = []
            no_response = []
            for att in attendees:
                email = att.get("email", "").lower()
                status = att.get("responseStatus", "needsAction")
                if status == "accepted":
                    accepted.append(email)
                elif status == "declined":
                    declined.append(email)
                elif status == "tentative":
                    tentative.append(email)
                else:
                    no_response.append(email)

            user_accepted = user_lower in accepted
            user_tentative = user_lower in tentative
            user_declined = user_lower in declined
            user_in_attendees = (
                user_accepted
                or user_tentative
                or user_declined
                or user_lower in no_response
            )

            if user_declined:
                continue

            if is_shared and not user_in_attendees:
                continue

            meet_code = ""
            conf = ev.get("conferenceData", {})
            for ep in conf.get("entryPoints", []):
                if ep.get("entryPointType") == "video":
                    uri = ep.get("uri", "")
                    if "meet.google.com/" in uri:
                        meet_code = uri.split("meet.google.com/")[-1].split("?")[0]
                    break

            start = ev.get("start", {})
            start_time = start.get("dateTime", start.get("date", ""))
            end = ev.get("end", {})
            end_time = end.get("dateTime", end.get("date", ""))

            cal_events.append(
                {
                    "id": ev["id"],
                    "title": title,
                    "start_time": start_time,
                    "end_time": end_time,
                    "organizer": organizer_email,
                    "is_organizer": is_organizer,
                    "is_recurring": bool(ev.get("recurringEventId")),
                    "classification": classification,
                    "competencies": competencies,
                    "attendee_count": len(attendees),
                    "accepted_count": len(accepted),
                    "accepted_emails": accepted,
                    "user_accepted": user_accepted,
                    "meet_code": meet_code,
                    "has_meet": bool(meet_code),
                    "calendar_id": calendar_id,
                    "calendar_name": calendar_name,
                }
            )

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    logger.info(
        "Calendar '%s': %d events with attendees (quarter %s)",
        calendar_name,
        len(cal_events),
        quarter_start[:10],
    )
    return cal_events


# ---------------------------------------------------------------------------
# Meet API: Actual Attendance from Conference Records
# ---------------------------------------------------------------------------


def collect_meet_attendance(
    meet_service,
    quarter_start: str,
    quarter_end: str | None = None,
    max_records: int = 200,
) -> dict[str, list[dict]]:
    """Collect actual attendance from Meet conference records.

    Returns: {space_name_or_meet_code: [{display_name, email, join_time, leave_time, duration_minutes}]}
    Also returns a flat list keyed by meet_code for Calendar linking.
    """
    records: list[dict] = []
    page_token = None

    filter_str = f'start_time>="{quarter_start}"'
    if quarter_end:
        filter_str += f' AND end_time<"{quarter_end}"'

    while True:
        _rate_limit()
        kwargs = {
            "filter": filter_str,
            "pageSize": min(max_records, 100),
        }
        if page_token:
            kwargs["pageToken"] = page_token

        try:
            resp = _api_call_with_backoff(
                lambda _kw=kwargs: meet_service.conferenceRecords()
                .list(**_kw)
                .execute()
            )
        except Exception as e:
            logger.warning("Meet API conferenceRecords.list failed: %s", e)
            break

        batch = resp.get("conferenceRecords", [])
        records.extend(batch)
        page_token = resp.get("nextPageToken")
        if not page_token or len(records) >= max_records:
            break

    logger.info("Meet API: %d conference records this quarter", len(records))

    attendance_by_space: dict[str, dict] = {}

    for rec in records:
        rec_name = rec.get("name", "")
        space_name = rec.get("space", "")
        start = rec.get("startTime", "")
        end = rec.get("endTime", "")

        try:
            _rate_limit()
            parts_resp = (
                meet_service.conferenceRecords()
                .participants()
                .list(
                    parent=rec_name,
                    pageSize=250,
                )
                .execute()
            )
        except Exception as e:
            logger.debug("Failed to get participants for %s: %s", rec_name, e)
            continue

        participants = []
        for p in parts_resp.get("participants", []):
            user = p.get("signedinUser", {})
            display_name = user.get("displayName", "")
            if not display_name:
                continue

            join_time = p.get("earliestStartTime", "")
            leave_time = p.get("latestEndTime", "")

            duration_min = 0
            if join_time and leave_time:
                try:
                    jt = datetime.fromisoformat(join_time.replace("Z", "+00:00"))
                    lt = datetime.fromisoformat(leave_time.replace("Z", "+00:00"))
                    duration_min = max(0, (lt - jt).total_seconds() / 60)
                except (ValueError, TypeError):
                    pass

            participants.append(
                {
                    "display_name": display_name,
                    "join_time": join_time,
                    "leave_time": leave_time,
                    "duration_minutes": round(duration_min, 1),
                }
            )

        attendance_by_space[space_name] = {
            "record_name": rec_name,
            "space": space_name,
            "start_time": start,
            "end_time": end,
            "participants": participants,
        }

    return attendance_by_space


def link_calendar_to_meet(
    calendar_meetings: list[dict],
    meet_service,
) -> dict[str, dict]:
    """Link Calendar events to Meet conference records via meeting code.

    Returns: {calendar_event_id: {participants: [...], actual_count, ...}}
    """
    linked: dict[str, dict] = {}
    meet_codes_seen: set[str] = set()

    meetings_with_meet = [m for m in calendar_meetings if m.get("meet_code")]

    unique_codes = {}
    for m in meetings_with_meet:
        code = m["meet_code"]
        if code not in unique_codes:
            unique_codes[code] = m

    for code, _meeting in unique_codes.items():
        if code in meet_codes_seen:
            continue
        meet_codes_seen.add(code)

        try:
            resp = _api_call_with_backoff(
                lambda _c=code: meet_service.conferenceRecords()
                .list(
                    filter=f'space.meeting_code="{_c}"',
                    pageSize=10,
                )
                .execute()
            )
        except Exception as e:
            logger.debug("Meet lookup for code %s failed: %s", code, e)
            continue

        records = resp.get("conferenceRecords", [])
        if not records:
            continue

        all_participants = []
        for rec in records:
            try:
                rec_name = rec["name"]
                parts_resp = _api_call_with_backoff(
                    lambda _rn=rec_name: meet_service.conferenceRecords()
                    .participants()
                    .list(
                        parent=_rn,
                        pageSize=250,
                    )
                    .execute()
                )
                for p in parts_resp.get("participants", []):
                    user = p.get("signedinUser", {})
                    display_name = user.get("displayName", "")
                    if display_name:
                        join_time = p.get("earliestStartTime", "")
                        leave_time = p.get("latestEndTime", "")
                        duration_min = 0
                        if join_time and leave_time:
                            try:
                                jt = datetime.fromisoformat(
                                    join_time.replace("Z", "+00:00")
                                )
                                lt = datetime.fromisoformat(
                                    leave_time.replace("Z", "+00:00")
                                )
                                duration_min = max(0, (lt - jt).total_seconds() / 60)
                            except (ValueError, TypeError):
                                pass
                        all_participants.append(
                            {
                                "display_name": display_name,
                                "join_time": join_time,
                                "leave_time": leave_time,
                                "duration_minutes": round(duration_min, 1),
                            }
                        )
            except Exception as e:
                logger.debug("Participants for %s failed: %s", rec["name"], e)

        for m in meetings_with_meet:
            if m["meet_code"] == code:
                linked[m["id"]] = {
                    "actual_participants": all_participants,
                    "actual_count": len(all_participants),
                    "conference_records": len(records),
                }

    logger.info(
        "Calendar-Meet linking: %d/%d events linked",
        len(linked),
        len(meetings_with_meet),
    )
    return linked


# ---------------------------------------------------------------------------
# Event Generation for QC Pipeline
# ---------------------------------------------------------------------------


def _build_meeting_classification_text(meeting: dict) -> str:
    """Build classification text for scorer matching."""
    classification = meeting.get("classification", "")
    parts = [
        meeting.get("title", ""),
        classification,
        _CLASSIFICATION_BOOST.get(classification, ""),
    ]
    if meeting.get("is_organizer"):
        parts.append("organized led facilitated leadership")
    count = meeting.get("attendee_count", 0)
    if count >= 10:
        parts.append("large meeting cross-team scope")
    return " ".join(p for p in parts if p)


def generate_meeting_events(
    calendar_meetings: list[dict],
    user_email: str,
    meet_link_data: dict[str, dict] | None = None,
) -> list[dict]:
    """Convert calendar meetings + optional Meet data into QC pipeline events."""
    events = []
    link_data = meet_link_data or {}

    for m in calendar_meetings:
        classification = m.get("classification", "general_meeting")
        is_org = m.get("is_organizer", False)

        if is_org:
            event_type = f"meeting_organized_{classification}"
        else:
            event_type = f"meeting_attended_{classification}"

        event_id = f"meeting:{m['id']}:{event_type}"

        actual = link_data.get(m["id"], {})
        actual_count = actual.get("actual_count", 0)

        role = "assignee" if is_org else "contributor"

        classification_text = _build_meeting_classification_text(m)

        event = {
            "id": event_id,
            "source": "meeting",
            "type": event_type,
            "item_id": m["id"],
            "title": f"[Meeting] {m['title']}",
            "timestamp": m.get("start_time", ""),
            "meeting_classification": classification,
            "meeting_competencies": m.get("competencies", []),
            "meeting_role": role,
            "meeting_is_organizer": is_org,
            "meeting_attendee_count": m.get("attendee_count", 0),
            "meeting_accepted_count": m.get("accepted_count", 0),
            "meeting_actual_participants": actual_count,
            "meeting_is_recurring": m.get("is_recurring", False),
            "meeting_has_meet_data": bool(actual),
            "extra_classification_text": classification_text,
        }
        events.append(event)

    return events


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

CACHE_FILENAME = "meeting_contributions_cache.json"


def _filter_cached_events(cached: dict) -> list[str]:
    """Filter cached events to only those from the primary calendar.

    The cache stores both raw meetings (with calendar_id) and generated
    events (with item_id matching meeting id).  Shared calendar meetings
    where the user is not an attendee are excluded.
    """
    events = cached.get("events", [])
    meetings = cached.get("meetings", [])
    if not meetings:
        return events

    primary_ids = {
        m["id"]
        for m in meetings
        if m.get("calendar_id") == "primary" or m.get("user_accepted", False)
    }

    if not primary_ids:
        return events

    filtered = [e for e in events if e.get("item_id") in primary_ids]
    if len(filtered) != len(events):
        logger.info(
            "Meeting cache filter: %d -> %d events (removed %d shared calendar events)",
            len(events),
            len(filtered),
            len(events) - len(filtered),
        )
    return filtered


def _cache_path(perf_dir: Path) -> Path:
    return perf_dir / CACHE_FILENAME


def load_cache(perf_dir: Path) -> dict | None:
    path = _cache_path(perf_dir)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        cached_at = data.get("cached_at", "")
        if cached_at:
            cached_dt = datetime.fromisoformat(cached_at)
            age_hours = (datetime.now() - cached_dt).total_seconds() / 3600
            if age_hours > 24:
                logger.info("Meeting cache expired (%.1f hours old)", age_hours)
                return None
        return data
    except Exception as e:
        logger.debug("Failed to load meeting cache: %s", e)
        return None


def save_cache(
    perf_dir: Path,
    meetings: list[dict],
    events: list[dict],
    meet_link_data: dict,
) -> None:
    perf_dir.mkdir(parents=True, exist_ok=True)
    cache_data = {
        "meetings": meetings,
        "events": events,
        "meet_link_data": meet_link_data,
        "meeting_count": len(meetings),
        "event_count": len(events),
        "cached_at": datetime.now().isoformat(),
    }
    try:
        with open(_cache_path(perf_dir), "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2)
        logger.info(
            "Meeting cache saved: %d meetings, %d events",
            len(meetings),
            len(events),
        )
    except Exception as e:
        logger.warning("Failed to save meeting cache: %s", e)


# ---------------------------------------------------------------------------
# Peer Meeting Data from Calendar Attendees
# ---------------------------------------------------------------------------


def build_peer_meeting_index(
    calendar_meetings: list[dict],
) -> dict[str, list[dict]]:
    """Build a per-email index of meeting attendance from Calendar data.

    For peer QC capture: since we can see attendee emails on our own
    calendar events, we can attribute meeting participation to peers
    who accepted the same meetings.

    Returns: {email: [{meeting_id, title, classification, accepted, is_organizer_of_meeting}]}
    """
    index: dict[str, list[dict]] = {}

    for m in calendar_meetings:
        for email in m.get("accepted_emails", []):
            entry = {
                "meeting_id": m["id"],
                "title": m["title"],
                "start_time": m["start_time"],
                "classification": m["classification"],
                "competencies": m["competencies"],
                "attendee_count": m["attendee_count"],
                "is_organizer": email == m.get("organizer", ""),
            }
            index.setdefault(email, []).append(entry)

    return index


def generate_peer_meeting_events(
    peer_email: str,
    peer_index: dict[str, list[dict]],
) -> list[dict]:
    """Generate meeting events for a peer from the attendee index."""
    contributions = peer_index.get(peer_email.lower(), [])
    if not contributions:
        return []

    events = []
    for c in contributions:
        classification = c.get("classification", "general_meeting")
        is_org = c.get("is_organizer", False)

        if is_org:
            event_type = f"meeting_organized_{classification}"
        else:
            event_type = f"meeting_attended_{classification}"

        event_id = f"meeting_peer:{c['meeting_id']}:{peer_email}:{event_type}"

        role = "assignee" if is_org else "contributor"

        meeting_for_text = {
            "title": c["title"],
            "classification": classification,
            "is_organizer": is_org,
            "attendee_count": c.get("attendee_count", 0),
        }
        classification_text = _build_meeting_classification_text(meeting_for_text)

        event = {
            "id": event_id,
            "source": "meeting",
            "type": event_type,
            "item_id": c["meeting_id"],
            "title": f"[Meeting] {c['title']}",
            "timestamp": c.get("start_time", ""),
            "meeting_classification": classification,
            "meeting_competencies": c.get("competencies", []),
            "meeting_role": role,
            "meeting_is_organizer": is_org,
            "meeting_attendee_count": c.get("attendee_count", 0),
            "meeting_peer_source": True,
            "extra_classification_text": classification_text,
        }
        events.append(event)

    logger.info(
        "Peer meeting events for %s: %d events from %d meeting contributions",
        peer_email,
        len(events),
        len(contributions),
    )
    return events


# ---------------------------------------------------------------------------
# Main Entry Points
# ---------------------------------------------------------------------------


def _get_services():
    """Get authenticated Calendar and Meet services."""
    token_file = Path.home() / ".config/google-calendar/token.json"
    if not token_file.exists():
        return None, None, "No OAuth token"

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        with open(Path(__file__).resolve().parent.parent.parent / "config.json") as f:
            cfg = json.load(f)
        scopes = cfg["google"]["oauth_scopes"]

        creds = Credentials.from_authorized_user_file(str(token_file), scopes)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_file, "w") as f:
                f.write(creds.to_json())

        cal_service = build("calendar", "v3", credentials=creds)

        meet_service = None
        if any("meetings" in s for s in (creds.scopes or [])):
            try:
                meet_service = build("meet", "v2", credentials=creds)
            except Exception as e:
                logger.debug("Meet service unavailable: %s", e)

        return cal_service, meet_service, None
    except Exception as e:
        return None, None, str(e)


def collect_meeting_contributions(
    perf_dir: Path,
    target: date,
    user_email: str | None = None,
    force_refresh: bool = False,
    include_meet: bool = True,
) -> list[dict]:
    """Collect meeting attendance events for the QC pipeline.

    Main entry point called from collector.py for self-collection.
    """
    if not force_refresh:
        cached = load_cache(perf_dir)
        if cached:
            events = _filter_cached_events(cached)
            logger.info(
                "Using cached meeting contributions: %d events",
                len(events),
            )
            return events

    cal_service, meet_service, error = _get_services()
    if error or not cal_service:
        logger.warning("Meeting collection unavailable: %s", error)
        return []

    if not user_email:
        try:
            from googleapiclient.discovery import build

            drive = build("drive", "v3", credentials=cal_service._http.credentials)
            about = drive.about().get(fields="user").execute()
            user_email = about["user"]["emailAddress"]
        except Exception as e:
            logger.warning("Getting user email from Drive about().get(): %s", e)
            try:
                import subprocess

                user_email = subprocess.check_output(
                    ["git", "config", "user.email"], text=True
                ).strip()
            except Exception as e2:
                logger.warning("Getting user email from git config: %s", e2)
                pass

    if not user_email:
        logger.warning("No user email for meeting collection")
        return []

    year = target.year
    quarter = (target.month - 1) // 3 + 1
    quarter_starts = QUARTER_STARTS
    m, d = quarter_starts[quarter]
    quarter_start = date(year, m, d).isoformat() + "T00:00:00Z"

    next_q = quarter + 1
    if next_q > 4:
        next_q = 1
        year += 1
    nm, nd = quarter_starts[next_q]
    quarter_end = date(year, nm, nd).isoformat() + "T00:00:00Z"

    now_str = datetime.utcnow().isoformat() + "Z"
    effective_end = min(quarter_end, now_str)

    meetings = collect_calendar_meetings(
        cal_service,
        quarter_start,
        effective_end,
        user_email,
    )

    meet_link_data: dict[str, dict] = {}
    if include_meet and meet_service:
        meet_link_data = link_calendar_to_meet(meetings, meet_service)

    events = generate_meeting_events(meetings, user_email, meet_link_data)

    save_cache(perf_dir, meetings, events, meet_link_data)

    logger.info(
        "Meeting collection complete: %d meetings -> %d events " "(Meet linked: %d)",
        len(meetings),
        len(events),
        len(meet_link_data),
    )
    return events


PEER_INDEX_FILENAME = "meeting_peer_index_cache.json"


def _peer_index_cache_path(perf_dir: Path) -> Path:
    return perf_dir / PEER_INDEX_FILENAME


def ensure_meeting_peer_index(
    perf_dir: Path,
    target: date,
    force_refresh: bool = False,
) -> dict[str, list[dict]]:
    """Build/load the peer meeting attendance index.

    This is called once before iterating over peers. Uses the same
    Calendar data as self-collection but indexes all attendee emails.

    Also queries any additional peer_calendars configured in config.json
    to capture meetings that peers attend but the primary user does not.
    """
    cache_path = _peer_index_cache_path(perf_dir)
    if not force_refresh and cache_path.exists():
        try:
            with open(cache_path, encoding="utf-8") as f:
                data = json.load(f)
            cached_at = data.get("cached_at", "")
            if cached_at:
                cached_dt = datetime.fromisoformat(cached_at)
                age_hours = (datetime.now() - cached_dt).total_seconds() / 3600
                if age_hours <= 24:
                    index = data.get("index", {})
                    logger.info(
                        "Using cached meeting peer index: %d users",
                        len(index),
                    )
                    return index
        except Exception as e:
            logger.warning("Loading meeting peer index cache: %s", e)
            pass

    cal_service, _, error = _get_services()
    if error or not cal_service:
        logger.warning("Cannot build meeting peer index: %s", error)
        return {}

    user_email = ""
    try:
        import subprocess

        user_email = subprocess.check_output(
            ["git", "config", "user.email"], text=True
        ).strip()
    except Exception as e:
        logger.warning("Getting user email from git config for peer index: %s", e)
        pass

    year = target.year
    quarter = (target.month - 1) // 3 + 1
    quarter_starts = QUARTER_STARTS
    m, d = quarter_starts[quarter]
    quarter_start = date(year, m, d).isoformat() + "T00:00:00Z"

    next_q = quarter + 1
    if next_q > 4:
        next_q = 1
        year += 1
    nm, nd = quarter_starts[next_q]
    quarter_end = date(year, nm, nd).isoformat() + "T00:00:00Z"

    now_str = datetime.utcnow().isoformat() + "Z"
    effective_end = min(quarter_end, now_str)

    meetings = collect_calendar_meetings(
        cal_service,
        quarter_start,
        effective_end,
        user_email or "unknown",
    )

    peer_calendars = _get_peer_calendar_ids()
    if peer_calendars:
        peer_cal_meetings = collect_calendar_meetings(
            cal_service,
            quarter_start,
            effective_end,
            user_email or "unknown",
            calendar_ids=peer_calendars,
        )
        existing_ids = {m["id"] for m in meetings}
        added = 0
        for m in peer_cal_meetings:
            if m["id"] not in existing_ids:
                existing_ids.add(m["id"])
                meetings.append(m)
                added += 1
        if added:
            logger.info(
                "Peer calendars added %d extra meetings from %d calendars",
                added,
                len(peer_calendars),
            )

    index = build_peer_meeting_index(meetings)

    perf_dir.mkdir(parents=True, exist_ok=True)
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "index": index,
                    "meeting_count": len(meetings),
                    "user_count": len(index),
                    "peer_calendar_count": len(peer_calendars),
                    "cached_at": datetime.now().isoformat(),
                },
                f,
                indent=2,
            )
    except Exception as e:
        logger.warning("Failed to save meeting peer index: %s", e)

    logger.info(
        "Meeting peer index built: %d meetings (%d peer calendars), "
        "%d unique attendees",
        len(meetings),
        len(peer_calendars),
        len(index),
    )
    return index


def collect_meeting_peer_contributions(
    perf_dir: Path,
    peer_email: str,
    target: date,
    force_refresh: bool = False,
) -> list[dict]:
    """Collect meeting attendance events for a peer.

    Uses the pre-built peer index from Calendar attendee data.
    """
    index = ensure_meeting_peer_index(perf_dir, target, force_refresh)
    if not index:
        return []
    return generate_peer_meeting_events(peer_email, index)
