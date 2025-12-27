"""
aa-google-calendar MCP Server

Provides Google Calendar integration for creating events and meetings.

CONSTRAINTS:
- All meetings in Irish time (Europe/Dublin)
- Meetings only between 15:00-19:00 Irish time
- Checks attendee availability before scheduling
"""

from mcp.server.fastmcp import FastMCP

from .tools import (
    google_calendar_check_mutual_availability,
    google_calendar_find_meeting,
    google_calendar_list_events,
    google_calendar_quick_meeting,
    google_calendar_schedule_meeting,
    google_calendar_status,
)

mcp = FastMCP("aa-google-calendar")

# Register tools
mcp.add_tool(google_calendar_schedule_meeting)
mcp.add_tool(google_calendar_quick_meeting)
mcp.add_tool(google_calendar_check_mutual_availability)
mcp.add_tool(google_calendar_find_meeting)
mcp.add_tool(google_calendar_list_events)
mcp.add_tool(google_calendar_status)

if __name__ == "__main__":
    mcp.run()
