"""
Google Calendar MCP Tools

Provides tools for creating Google Calendar events with Google Meet links.

Setup:
1. Create OAuth 2.0 credentials in Google Cloud Console
2. Download credentials.json to ~/.config/google-calendar/credentials.json
3. Run the server once to complete OAuth flow and save token.json

Or use service account:
1. Create service account in Google Cloud Console
2. Enable domain-wide delegation
3. Download service account JSON to ~/.config/google-calendar/service_account.json
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

# Initialize FastMCP
mcp = FastMCP("aa-google-calendar")

# Config paths
CONFIG_DIR = Path.home() / ".config" / "google-calendar"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
TOKEN_FILE = CONFIG_DIR / "token.json"
SERVICE_ACCOUNT_FILE = CONFIG_DIR / "service_account.json"

# Scopes required for calendar access
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]


def get_calendar_service():
    """
    Get authenticated Google Calendar service.
    
    Tries OAuth2 first, then service account.
    Returns None if not configured.
    """
    try:
        from google.oauth2.credentials import Credentials
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        return None, "Google API libraries not installed. Run: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
    
    creds = None
    
    # Try token file first (OAuth2)
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception:
            pass
    
    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_FILE, 'w') as f:
                f.write(creds.to_json())
        except Exception:
            creds = None
    
    # Try service account
    if not creds and SERVICE_ACCOUNT_FILE.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(SERVICE_ACCOUNT_FILE),
                scopes=SCOPES
            )
        except Exception:
            pass
    
    # Need to authenticate
    if not creds or not creds.valid:
        if CREDENTIALS_FILE.exists():
            try:
                from google_auth_oauthlib.flow import InstalledAppFlow
                flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
                creds = flow.run_local_server(port=0)
                # Save credentials for next run
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                with open(TOKEN_FILE, 'w') as f:
                    f.write(creds.to_json())
            except Exception as e:
                return None, f"OAuth flow failed: {e}"
        else:
            return None, f"No credentials found. Add credentials.json to {CONFIG_DIR}"
    
    try:
        service = build('calendar', 'v3', credentials=creds)
        return service, None
    except Exception as e:
        return None, f"Failed to build calendar service: {e}"


@mcp.tool()
async def google_calendar_create_event(
    summary: str,
    start_time: str,
    duration_minutes: int = 30,
    attendees: str = "",
    description: str = "",
    add_meet_link: bool = True,
    timezone: str = "Europe/Dublin",
) -> str:
    """
    Create a Google Calendar event with optional Google Meet link.
    
    Args:
        summary: Event title (e.g., "MR !1450 Review Discussion")
        start_time: Start time in ISO format (e.g., "2025-12-26T10:00:00")
        duration_minutes: Duration in minutes (default: 30)
        attendees: Comma-separated email addresses
        description: Event description/agenda
        add_meet_link: Create Google Meet video conference (default: True)
        timezone: Timezone for the event (default: Europe/Dublin)
    
    Returns:
        Event details including Google Meet link if created
    """
    service, error = get_calendar_service()
    
    if error:
        return f"❌ {error}"
    
    if not service:
        return "❌ Google Calendar service not available"
    
    try:
        # Parse start time
        try:
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        except ValueError:
            # Try common formats
            for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%d/%m/%Y %H:%M"]:
                try:
                    start_dt = datetime.strptime(start_time, fmt)
                    break
                except ValueError:
                    continue
            else:
                return f"❌ Invalid start_time format: {start_time}. Use ISO format: 2025-12-26T10:00:00"
        
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        
        # Build event
        event = {
            'summary': summary,
            'description': description,
            'start': {
                'dateTime': start_dt.isoformat(),
                'timeZone': timezone,
            },
            'end': {
                'dateTime': end_dt.isoformat(),
                'timeZone': timezone,
            },
        }
        
        # Add attendees
        if attendees:
            attendee_list = [{'email': email.strip()} for email in attendees.split(',') if email.strip()]
            if attendee_list:
                event['attendees'] = attendee_list
        
        # Add Google Meet
        if add_meet_link:
            event['conferenceData'] = {
                'createRequest': {
                    'requestId': f"meet-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    'conferenceSolutionKey': {
                        'type': 'hangoutsMeet'
                    }
                }
            }
        
        # Create event
        created_event = service.events().insert(
            calendarId='primary',
            body=event,
            conferenceDataVersion=1 if add_meet_link else 0,
            sendUpdates='all'  # Send invites to attendees
        ).execute()
        
        # Format response
        event_link = created_event.get('htmlLink', '')
        meet_link = ""
        if created_event.get('conferenceData', {}).get('entryPoints'):
            for entry in created_event['conferenceData']['entryPoints']:
                if entry.get('entryPointType') == 'video':
                    meet_link = entry.get('uri', '')
                    break
        
        result = [
            f"✅ **Event Created**",
            f"",
            f"**Title:** {summary}",
            f"**When:** {start_dt.strftime('%Y-%m-%d %H:%M')} ({duration_minutes} min)",
            f"**Calendar Link:** {event_link}",
        ]
        
        if meet_link:
            result.append(f"**Google Meet:** {meet_link}")
        
        if attendees:
            result.append(f"**Attendees:** {attendees} (invites sent)")
        
        return '\n'.join(result)
        
    except Exception as e:
        return f"❌ Failed to create event: {e}"


@mcp.tool()
async def google_calendar_list_events(
    days: int = 7,
    max_results: int = 10,
) -> str:
    """
    List upcoming calendar events.
    
    Args:
        days: Number of days to look ahead (default: 7)
        max_results: Maximum number of events to return (default: 10)
    
    Returns:
        List of upcoming events
    """
    service, error = get_calendar_service()
    
    if error:
        return f"❌ {error}"
    
    if not service:
        return "❌ Google Calendar service not available"
    
    try:
        now = datetime.utcnow().isoformat() + 'Z'
        end = (datetime.utcnow() + timedelta(days=days)).isoformat() + 'Z'
        
        events_result = service.events().list(
            calendarId='primary',
            timeMin=now,
            timeMax=end,
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        if not events:
            return f"📅 No upcoming events in the next {days} days."
        
        lines = [f"📅 **Upcoming Events** (next {days} days):", ""]
        
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary = event.get('summary', 'No title')
            
            # Parse and format start time
            try:
                if 'T' in start:
                    dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    time_str = dt.strftime('%Y-%m-%d %H:%M')
                else:
                    time_str = start
            except:
                time_str = start
            
            # Check for Meet link
            meet_link = ""
            if event.get('conferenceData', {}).get('entryPoints'):
                for entry in event['conferenceData']['entryPoints']:
                    if entry.get('entryPointType') == 'video':
                        meet_link = f" 📹 [Join]({entry.get('uri', '')})"
                        break
            
            lines.append(f"- **{time_str}** - {summary}{meet_link}")
        
        return '\n'.join(lines)
        
    except Exception as e:
        return f"❌ Failed to list events: {e}"


@mcp.tool()
async def google_calendar_quick_meeting(
    title: str,
    attendee_email: str,
    when: str = "tomorrow 10:00",
    duration_minutes: int = 30,
) -> str:
    """
    Quickly schedule a meeting with a single attendee.
    
    This is a convenience wrapper for common meeting scenarios like
    "schedule a meeting with Brian about the race condition fix".
    
    Args:
        title: Meeting title
        attendee_email: Email of the person to meet with
        when: Natural language time like "tomorrow 10:00", "next monday 14:00"
        duration_minutes: Meeting duration (default: 30)
    
    Returns:
        Meeting details and Google Meet link
    """
    from datetime import datetime, timedelta
    import re
    
    # Parse natural language time
    now = datetime.now()
    
    when_lower = when.lower()
    
    # Extract time component
    time_match = re.search(r'(\d{1,2})[:\.]?(\d{2})?', when)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
    else:
        hour, minute = 10, 0  # Default to 10:00
    
    # Parse date component
    if 'tomorrow' in when_lower:
        target_date = now + timedelta(days=1)
    elif 'today' in when_lower:
        target_date = now
    elif 'monday' in when_lower:
        days_ahead = (0 - now.weekday()) % 7 or 7
        target_date = now + timedelta(days=days_ahead)
    elif 'tuesday' in when_lower:
        days_ahead = (1 - now.weekday()) % 7 or 7
        target_date = now + timedelta(days=days_ahead)
    elif 'wednesday' in when_lower:
        days_ahead = (2 - now.weekday()) % 7 or 7
        target_date = now + timedelta(days=days_ahead)
    elif 'thursday' in when_lower:
        days_ahead = (3 - now.weekday()) % 7 or 7
        target_date = now + timedelta(days=days_ahead)
    elif 'friday' in when_lower:
        days_ahead = (4 - now.weekday()) % 7 or 7
        target_date = now + timedelta(days=days_ahead)
    else:
        # Try to parse as date
        target_date = now + timedelta(days=1)  # Default to tomorrow
    
    # Build datetime
    start_time = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    # Call the main create function
    return await google_calendar_create_event(
        summary=title,
        start_time=start_time.isoformat(),
        duration_minutes=duration_minutes,
        attendees=attendee_email,
        description=f"Meeting scheduled via AI Workflow assistant.\n\nRequested: {title}",
        add_meet_link=True,
    )


@mcp.tool()
async def google_calendar_check_availability(
    date: str,
    attendees: str = "",
) -> str:
    """
    Check calendar availability for a specific date.
    
    Args:
        date: Date to check (YYYY-MM-DD format)
        attendees: Comma-separated emails to check availability for (requires domain-wide delegation)
    
    Returns:
        Free/busy information for the date
    """
    service, error = get_calendar_service()
    
    if error:
        return f"❌ {error}"
    
    if not service:
        return "❌ Google Calendar service not available"
    
    try:
        # Parse date
        try:
            check_date = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return f"❌ Invalid date format: {date}. Use YYYY-MM-DD."
        
        # Set time bounds for the day
        time_min = check_date.replace(hour=0, minute=0, second=0).isoformat() + 'Z'
        time_max = (check_date + timedelta(days=1)).replace(hour=0, minute=0, second=0).isoformat() + 'Z'
        
        # Get events for the day
        events_result = service.events().list(
            calendarId='primary',
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        lines = [f"📅 **Availability for {date}**", ""]
        
        if not events:
            lines.append("✅ Calendar is clear for the day!")
        else:
            # Build busy periods
            busy_periods = []
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                summary = event.get('summary', 'Busy')
                
                try:
                    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                    busy_periods.append({
                        'start': start_dt.strftime('%H:%M'),
                        'end': end_dt.strftime('%H:%M'),
                        'summary': summary,
                    })
                except:
                    continue
            
            lines.append("**Busy times:**")
            for period in busy_periods:
                lines.append(f"- {period['start']} - {period['end']}: {period['summary']}")
            
            lines.append("")
            
            # Suggest free slots (simple version - working hours 9-17)
            lines.append("**Suggested free slots:**")
            
            # Very simplified free slot detection
            busy_hours = set()
            for period in busy_periods:
                try:
                    start_hour = int(period['start'].split(':')[0])
                    end_hour = int(period['end'].split(':')[0])
                    for h in range(start_hour, end_hour + 1):
                        busy_hours.add(h)
                except:
                    continue
            
            for hour in range(9, 17):
                if hour not in busy_hours:
                    lines.append(f"- {hour:02d}:00 - {hour+1:02d}:00")
        
        return '\n'.join(lines)
        
    except Exception as e:
        return f"❌ Failed to check availability: {e}"


@mcp.tool()
async def google_calendar_status() -> str:
    """
    Check Google Calendar integration status and configuration.
    
    Returns:
        Configuration status and setup instructions if needed
    """
    lines = ["# Google Calendar Integration Status", ""]
    
    # Check config directory
    lines.append(f"**Config directory:** `{CONFIG_DIR}`")
    lines.append("")
    
    # Check credentials
    if CREDENTIALS_FILE.exists():
        lines.append("✅ OAuth credentials file found")
    else:
        lines.append("❌ OAuth credentials not found")
        lines.append(f"   Add `credentials.json` to `{CONFIG_DIR}`")
    
    if SERVICE_ACCOUNT_FILE.exists():
        lines.append("✅ Service account file found")
    else:
        lines.append("⚪ Service account not configured (optional)")
    
    if TOKEN_FILE.exists():
        lines.append("✅ OAuth token cached (authenticated)")
    else:
        lines.append("⚪ No cached token (will need to authenticate)")
    
    lines.append("")
    
    # Try to connect
    service, error = get_calendar_service()
    
    if service:
        lines.append("✅ **Connected to Google Calendar**")
        
        # Try to get calendar info
        try:
            calendar = service.calendars().get(calendarId='primary').execute()
            lines.append(f"   Calendar: {calendar.get('summary', 'Primary')}")
            lines.append(f"   Timezone: {calendar.get('timeZone', 'Unknown')}")
        except Exception as e:
            lines.append(f"   (Could not fetch calendar details: {e})")
    else:
        lines.append(f"❌ **Not connected:** {error}")
    
    lines.append("")
    lines.append("## Setup Instructions")
    lines.append("")
    lines.append("1. Go to [Google Cloud Console](https://console.cloud.google.com/)")
    lines.append("2. Create or select a project")
    lines.append("3. Enable the Google Calendar API")
    lines.append("4. Create OAuth 2.0 credentials (Desktop app)")
    lines.append(f"5. Download and save as `{CREDENTIALS_FILE}`")
    lines.append("6. Run any calendar tool to complete OAuth flow")
    
    return '\n'.join(lines)


def register_tools(server: FastMCP):
    """Register all Google Calendar tools with a FastMCP server."""
    server.add_tool(google_calendar_create_event)
    server.add_tool(google_calendar_list_events)
    server.add_tool(google_calendar_quick_meeting)
    server.add_tool(google_calendar_check_availability)
    server.add_tool(google_calendar_status)


if __name__ == "__main__":
    mcp.run()

