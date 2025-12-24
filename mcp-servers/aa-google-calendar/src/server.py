"""
aa-google-calendar MCP Server

Provides Google Calendar integration for creating events and meetings.
"""

from mcp.server.fastmcp import FastMCP

from .tools import (
    google_calendar_create_event,
    google_calendar_list_events,
    google_calendar_quick_meeting,
    google_calendar_check_availability,
    google_calendar_status,
)

mcp = FastMCP("aa-google-calendar")

# Register tools
mcp.add_tool(google_calendar_create_event)
mcp.add_tool(google_calendar_list_events)
mcp.add_tool(google_calendar_quick_meeting)
mcp.add_tool(google_calendar_check_availability)
mcp.add_tool(google_calendar_status)

if __name__ == "__main__":
    mcp.run()

