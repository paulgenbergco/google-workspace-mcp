"""
Google Workspace Multi-Account MCP Server
------------------------------------------
Exposes Gmail, Google Calendar, and Google Drive operations for multiple
Google accounts via the Model Context Protocol (MCP) stdio transport.

Start with:  python server.py
Configure accounts in config.json and authenticate with: python setup_auth.py
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from auth import AuthManager
from config import get_accounts, get_client_secret_path, get_credentials_dir, load_config
from gcalendar import CalendarService
from gdocs import DocsService
from gdrive import DriveService
from gmail import GmailService
from gpeople import PeopleService
from gsheets import SheetsService
from gslides import SlidesService

# ---------------------------------------------------------------------------
# Bootstrap: load config and auth manager at startup
# ---------------------------------------------------------------------------

try:
    _config = load_config()
    _accounts = get_accounts(_config)
    _credentials_dir = get_credentials_dir(_config)
    _client_secret_path = get_client_secret_path(_config)
    _auth = AuthManager(_credentials_dir, _client_secret_path)
except FileNotFoundError as exc:
    print(f"STARTUP ERROR: {exc}", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_creds(account_name: str):
    """Return valid credentials for an account or raise ValueError."""
    if account_name not in _accounts:
        raise ValueError(
            f"Unknown account '{account_name}'. Available: {list(_accounts.keys())}"
        )
    creds = _auth.get_credentials(account_name)
    if creds is None:
        email = _accounts[account_name].get("email", account_name)
        raise ValueError(
            f"Account '{account_name}' ({email}) is not authenticated. "
            "Run 'python setup_auth.py' to authenticate."
        )
    return creds


def _get_service(account_name: str) -> GmailService:
    return GmailService(_get_creds(account_name), account_name)


def _get_calendar(account_name: str) -> CalendarService:
    return CalendarService(_get_creds(account_name), account_name)


def _get_drive(account_name: str) -> DriveService:
    return DriveService(_get_creds(account_name), account_name)


def _get_people(account_name: str) -> PeopleService:
    return PeopleService(_get_creds(account_name), account_name)


def _get_docs(account_name: str) -> DocsService:
    return DocsService(_get_creds(account_name), account_name)


def _get_sheets(account_name: str) -> SheetsService:
    return SheetsService(_get_creds(account_name), account_name)


def _get_slides(account_name: str) -> SlidesService:
    return SlidesService(_get_creds(account_name), account_name)


def _fmt(data: Any) -> list[types.TextContent]:
    if isinstance(data, str):
        return [types.TextContent(type="text", text=data)]
    return [types.TextContent(type="text", text=json.dumps(data, indent=2, ensure_ascii=False))]


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

server = Server("google-workspace")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_accounts",
            description=(
                "List all Gmail accounts configured in this MCP server, "
                "along with their authentication status."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="gmail_get_profile",
            description="Get the Gmail profile (email address, message count, thread count) for an account.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {
                        "type": "string",
                        "description": "Account name as defined in config.json (e.g. 'personal', 'work')",
                    }
                },
                "required": ["account"],
            },
        ),
        types.Tool(
            name="gmail_search",
            description=(
                "Search emails using Gmail search syntax. "
                "Searches a single account or all accounts if 'account' is omitted. "
                "Example queries: 'from:boss@company.com is:unread', 'subject:invoice has:attachment'"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {
                        "type": "string",
                        "description": "Account to search. Omit to search all configured accounts.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Gmail search query string",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max results per account (default 10, max 50)",
                        "default": 10,
                    },
                    "include_body": {
                        "type": "boolean",
                        "description": "Include full message body in results (slower). Default: false.",
                        "default": False,
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="gmail_read_message",
            description="Read the full content of a Gmail message by its ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {
                        "type": "string",
                        "description": "Account that owns the message",
                    },
                    "message_id": {
                        "type": "string",
                        "description": "Gmail message ID (from search results)",
                    },
                },
                "required": ["account", "message_id"],
            },
        ),
        types.Tool(
            name="gmail_read_thread",
            description="Read all messages in a Gmail thread/conversation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {
                        "type": "string",
                        "description": "Account that owns the thread",
                    },
                    "thread_id": {
                        "type": "string",
                        "description": "Gmail thread ID",
                    },
                },
                "required": ["account", "thread_id"],
            },
        ),
        types.Tool(
            name="gmail_send",
            description="Send an email from a specific Gmail account.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {
                        "type": "string",
                        "description": "Account to send from",
                    },
                    "to": {
                        "type": "string",
                        "description": "Recipient(s), comma-separated",
                    },
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body (plain text)"},
                    "cc": {"type": "string", "description": "CC recipients, comma-separated"},
                    "bcc": {"type": "string", "description": "BCC recipients, comma-separated"},
                },
                "required": ["account", "to", "subject", "body"],
            },
        ),
        types.Tool(
            name="gmail_create_draft",
            description="Save an email as a draft in a specific Gmail account.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {
                        "type": "string",
                        "description": "Account to create the draft in",
                    },
                    "to": {"type": "string", "description": "Recipient(s), comma-separated"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body (plain text)"},
                    "cc": {"type": "string", "description": "CC recipients"},
                    "bcc": {"type": "string", "description": "BCC recipients"},
                },
                "required": ["account", "to", "subject", "body"],
            },
        ),
        types.Tool(
            name="gmail_list_drafts",
            description="List draft emails in a Gmail account.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "max_results": {
                        "type": "integer",
                        "description": "Max drafts to return (default 10)",
                        "default": 10,
                    },
                },
                "required": ["account"],
            },
        ),
        types.Tool(
            name="gmail_list_labels",
            description="List all labels and folders in a Gmail account.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"}
                },
                "required": ["account"],
            },
        ),
        types.Tool(
            name="gmail_modify_labels",
            description=(
                "Add or remove labels on a Gmail message. "
                "Common label IDs: STARRED, UNREAD, INBOX, SPAM, TRASH, IMPORTANT."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "message_id": {"type": "string", "description": "Gmail message ID"},
                    "add_labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Label IDs to add (e.g. ['STARRED', 'UNREAD'])",
                    },
                    "remove_labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Label IDs to remove (e.g. ['UNREAD'])",
                    },
                },
                "required": ["account", "message_id"],
            },
        ),
        types.Tool(
            name="gmail_trash",
            description="Move a Gmail message to the Trash.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "message_id": {"type": "string", "description": "Gmail message ID"},
                },
                "required": ["account", "message_id"],
            },
        ),
        types.Tool(
            name="gmail_send_draft",
            description="Send an existing draft email by its draft ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "draft_id": {"type": "string", "description": "Draft ID (from gmail_list_drafts)"},
                },
                "required": ["account", "draft_id"],
            },
        ),
        types.Tool(
            name="gmail_list_attachments",
            description="List all attachments on a Gmail message (IDs, filenames, sizes).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "message_id": {"type": "string", "description": "Gmail message ID"},
                },
                "required": ["account", "message_id"],
            },
        ),
        types.Tool(
            name="gmail_download_attachment",
            description="Download the content of an attachment from a Gmail message.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "message_id": {"type": "string", "description": "Gmail message ID"},
                    "attachment_id": {
                        "type": "string",
                        "description": "Attachment ID (from gmail_list_attachments)",
                    },
                },
                "required": ["account", "message_id", "attachment_id"],
            },
        ),
        # ── Calendar tools ──────────────────────────────────────────────────
        types.Tool(
            name="calendar_list_calendars",
            description="List all Google Calendars available for an account (primary, work, shared, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                },
                "required": ["account"],
            },
        ),
        types.Tool(
            name="calendar_list_events",
            description=(
                "List upcoming calendar events for an account. "
                "Optionally filter by time range and calendar. "
                "Times must be in RFC3339 format, e.g. '2026-03-10T00:00:00Z'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar ID (default: 'primary'). Use calendar_list_calendars to get IDs.",
                        "default": "primary",
                    },
                    "time_min": {
                        "type": "string",
                        "description": "Start of range (RFC3339). Defaults to now.",
                    },
                    "time_max": {
                        "type": "string",
                        "description": "End of range (RFC3339). Optional.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max events to return (default 20, max 50)",
                        "default": 20,
                    },
                },
                "required": ["account"],
            },
        ),
        types.Tool(
            name="calendar_search",
            description="Search for events by keyword across a calendar (title, description, location, attendees).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "query": {"type": "string", "description": "Search keyword(s)"},
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar ID (default: 'primary')",
                        "default": "primary",
                    },
                    "time_min": {
                        "type": "string",
                        "description": "Start of range (RFC3339). Defaults to now.",
                    },
                    "time_max": {
                        "type": "string",
                        "description": "End of range (RFC3339). Optional.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max results (default 20)",
                        "default": 20,
                    },
                },
                "required": ["account", "query"],
            },
        ),
        types.Tool(
            name="calendar_get_event",
            description="Get full details of a specific calendar event by its ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "event_id": {"type": "string", "description": "Event ID (from list or search results)"},
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar ID (default: 'primary')",
                        "default": "primary",
                    },
                },
                "required": ["account", "event_id"],
            },
        ),
        types.Tool(
            name="calendar_create_event",
            description=(
                "Create a new calendar event. "
                "Times in RFC3339 (e.g. '2026-04-25T10:00:00-07:00'). "
                "For all-day events, use dates like '2026-04-25'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "summary": {"type": "string", "description": "Event title"},
                    "start": {"type": "string", "description": "Start time (RFC3339) or date (YYYY-MM-DD for all-day)"},
                    "end": {"type": "string", "description": "End time (RFC3339) or date (YYYY-MM-DD for all-day)"},
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: 'primary')", "default": "primary"},
                    "description": {"type": "string", "description": "Event description"},
                    "location": {"type": "string", "description": "Event location"},
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of attendee email addresses",
                    },
                    "all_day": {"type": "boolean", "description": "True for all-day event", "default": False},
                    "add_meet": {"type": "boolean", "description": "Auto-create a Google Meet link", "default": False},
                },
                "required": ["account", "summary", "start", "end"],
            },
        ),
        types.Tool(
            name="calendar_update_event",
            description="Update fields on an existing calendar event. Only pass the fields you want to change.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "event_id": {"type": "string", "description": "Event ID"},
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: 'primary')", "default": "primary"},
                    "summary": {"type": "string", "description": "New title"},
                    "start": {"type": "string", "description": "New start time (RFC3339)"},
                    "end": {"type": "string", "description": "New end time (RFC3339)"},
                    "description": {"type": "string", "description": "New description"},
                    "location": {"type": "string", "description": "New location"},
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Replace attendees with this list of emails",
                    },
                },
                "required": ["account", "event_id"],
            },
        ),
        types.Tool(
            name="calendar_delete_event",
            description="Delete a calendar event.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "event_id": {"type": "string", "description": "Event ID"},
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: 'primary')", "default": "primary"},
                },
                "required": ["account", "event_id"],
            },
        ),
        types.Tool(
            name="calendar_respond",
            description="Respond to a calendar event invitation (accepted, declined, tentative).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "event_id": {"type": "string", "description": "Event ID"},
                    "response": {
                        "type": "string",
                        "description": "Response: 'accepted', 'declined', or 'tentative'",
                        "enum": ["accepted", "declined", "tentative"],
                    },
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: 'primary')", "default": "primary"},
                },
                "required": ["account", "event_id", "response"],
            },
        ),
        types.Tool(
            name="calendar_find_free_time",
            description="Query free/busy information for a list of people in a time range.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "emails": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Email addresses to check availability for",
                    },
                    "time_min": {"type": "string", "description": "Start of range (RFC3339)"},
                    "time_max": {"type": "string", "description": "End of range (RFC3339)"},
                },
                "required": ["account", "emails", "time_min", "time_max"],
            },
        ),
        # ── Drive tools ────────────────────────────────────────────────────
        types.Tool(
            name="drive_search",
            description=(
                "Search Google Drive files using Drive query syntax. "
                "Examples: \"name contains 'invoice'\", \"mimeType = 'application/pdf'\", "
                "\"fullText contains 'quarterly report'\". "
                "Searches a single account or all accounts if 'account' is omitted."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {
                        "type": "string",
                        "description": "Account to search. Omit to search all accounts.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Drive search query (same syntax as Drive search bar)",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max results per account (default 20, max 100)",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="drive_list_recent",
            description="List recently modified files in Google Drive for an account.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "max_results": {
                        "type": "integer",
                        "description": "Max files to return (default 20, max 100)",
                        "default": 20,
                    },
                },
                "required": ["account"],
            },
        ),
        types.Tool(
            name="drive_get_file",
            description="Get detailed metadata for a specific file in Google Drive.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "file_id": {"type": "string", "description": "File ID (from search or list results)"},
                },
                "required": ["account", "file_id"],
            },
        ),
        types.Tool(
            name="drive_read_content",
            description=(
                "Read the content of a file in Google Drive. "
                "Automatically exports Google Docs as plain text, Sheets as CSV, "
                "and Slides as plain text. Returns content for text-based files; "
                "for binary files, returns a link."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "file_id": {"type": "string", "description": "File ID"},
                },
                "required": ["account", "file_id"],
            },
        ),
        types.Tool(
            name="drive_upload",
            description="Upload a new file to Google Drive with text content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "name": {"type": "string", "description": "File name (e.g. 'notes.txt', 'data.csv')"},
                    "content": {"type": "string", "description": "File content (text)"},
                    "mime_type": {
                        "type": "string",
                        "description": "MIME type (default: 'text/plain'). Use 'text/csv' for CSV, etc.",
                        "default": "text/plain",
                    },
                    "parent_folder_id": {
                        "type": "string",
                        "description": "Parent folder ID. Omit for root.",
                    },
                },
                "required": ["account", "name", "content"],
            },
        ),
        types.Tool(
            name="drive_update",
            description="Update the content of an existing file in Google Drive.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "file_id": {"type": "string", "description": "File ID to update"},
                    "content": {"type": "string", "description": "New file content (text)"},
                    "mime_type": {
                        "type": "string",
                        "description": "MIME type (default: 'text/plain')",
                        "default": "text/plain",
                    },
                },
                "required": ["account", "file_id", "content"],
            },
        ),
        types.Tool(
            name="drive_create_folder",
            description="Create a new folder in Google Drive.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "name": {"type": "string", "description": "Folder name"},
                    "parent_folder_id": {
                        "type": "string",
                        "description": "Parent folder ID. Omit for root.",
                    },
                },
                "required": ["account", "name"],
            },
        ),
        types.Tool(
            name="drive_move",
            description="Move a file or folder to a different parent folder.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "file_id": {"type": "string", "description": "File or folder ID to move"},
                    "new_parent_id": {"type": "string", "description": "Destination folder ID"},
                },
                "required": ["account", "file_id", "new_parent_id"],
            },
        ),
        types.Tool(
            name="drive_rename",
            description="Rename a file or folder in Google Drive.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "file_id": {"type": "string", "description": "File or folder ID"},
                    "new_name": {"type": "string", "description": "New name"},
                },
                "required": ["account", "file_id", "new_name"],
            },
        ),
        types.Tool(
            name="drive_trash",
            description="Move a file or folder to the trash in Google Drive.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "file_id": {"type": "string", "description": "File or folder ID"},
                },
                "required": ["account", "file_id"],
            },
        ),
        # ── People / Contacts tools ────────────────────────────────────────
        types.Tool(
            name="people_list_contacts",
            description="List the user's Google Contacts, ordered by most recently modified.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "max_results": {"type": "integer", "description": "Max contacts to return (default 50)", "default": 50},
                },
                "required": ["account"],
            },
        ),
        types.Tool(
            name="people_search",
            description="Search contacts by name, email, phone number, or other fields.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "query": {"type": "string", "description": "Search query (name, email, phone, etc.)"},
                    "max_results": {"type": "integer", "description": "Max results (default 20)", "default": 20},
                },
                "required": ["account", "query"],
            },
        ),
        types.Tool(
            name="people_get_contact",
            description="Get full details of a specific contact by resource name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "resource_name": {"type": "string", "description": "Contact resource name (e.g. 'people/c1234567')"},
                },
                "required": ["account", "resource_name"],
            },
        ),
        types.Tool(
            name="people_create_contact",
            description="Create a new Google Contact.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "given_name": {"type": "string", "description": "First name"},
                    "family_name": {"type": "string", "description": "Last name"},
                    "email": {"type": "string", "description": "Email address"},
                    "phone": {"type": "string", "description": "Phone number"},
                    "organization": {"type": "string", "description": "Company/organization name"},
                    "title": {"type": "string", "description": "Job title"},
                },
                "required": ["account", "given_name"],
            },
        ),
        types.Tool(
            name="people_update_contact",
            description="Update an existing Google Contact. Only pass the fields you want to change.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "resource_name": {"type": "string", "description": "Contact resource name"},
                    "given_name": {"type": "string", "description": "New first name"},
                    "family_name": {"type": "string", "description": "New last name"},
                    "email": {"type": "string", "description": "New email"},
                    "phone": {"type": "string", "description": "New phone"},
                    "organization": {"type": "string", "description": "New company name"},
                    "title": {"type": "string", "description": "New job title"},
                },
                "required": ["account", "resource_name"],
            },
        ),
        types.Tool(
            name="people_delete_contact",
            description="Delete a Google Contact.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "resource_name": {"type": "string", "description": "Contact resource name"},
                },
                "required": ["account", "resource_name"],
            },
        ),
        # ── Google Docs tools ──────────────────────────────────────────────
        types.Tool(
            name="docs_get",
            description="Read the full text content of a Google Doc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "document_id": {"type": "string", "description": "Google Doc ID (from URL or Drive search)"},
                },
                "required": ["account", "document_id"],
            },
        ),
        types.Tool(
            name="docs_create",
            description="Create a new Google Doc, optionally with initial text content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "title": {"type": "string", "description": "Document title"},
                    "body_text": {"type": "string", "description": "Initial text content (optional)"},
                },
                "required": ["account", "title"],
            },
        ),
        types.Tool(
            name="docs_write",
            description="Insert text at a specific position in a Google Doc. Index 1 = beginning of document.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "document_id": {"type": "string", "description": "Google Doc ID"},
                    "text": {"type": "string", "description": "Text to insert"},
                    "index": {"type": "integer", "description": "Character index to insert at (default: 1 = start)", "default": 1},
                },
                "required": ["account", "document_id", "text"],
            },
        ),
        types.Tool(
            name="docs_replace",
            description="Find and replace text throughout a Google Doc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "document_id": {"type": "string", "description": "Google Doc ID"},
                    "find": {"type": "string", "description": "Text to find"},
                    "replace": {"type": "string", "description": "Replacement text"},
                    "match_case": {"type": "boolean", "description": "Case-sensitive match (default: true)", "default": True},
                },
                "required": ["account", "document_id", "find", "replace"],
            },
        ),
        types.Tool(
            name="docs_format",
            description=(
                "Format a range of text in a Google Doc. "
                "Supports bold, italic, underline, font size, links, and heading styles. "
                "named_style can be: NORMAL_TEXT, HEADING_1 through HEADING_6, TITLE, SUBTITLE."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "document_id": {"type": "string", "description": "Google Doc ID"},
                    "start_index": {"type": "integer", "description": "Start character index"},
                    "end_index": {"type": "integer", "description": "End character index"},
                    "bold": {"type": "boolean", "description": "Apply bold"},
                    "italic": {"type": "boolean", "description": "Apply italic"},
                    "underline": {"type": "boolean", "description": "Apply underline"},
                    "font_size": {"type": "integer", "description": "Font size in points"},
                    "link_url": {"type": "string", "description": "Make text a hyperlink"},
                    "named_style": {"type": "string", "description": "Heading style (HEADING_1, TITLE, etc.)"},
                },
                "required": ["account", "document_id", "start_index", "end_index"],
            },
        ),
        # ── Google Sheets tools ────────────────────────────────────────────
        types.Tool(
            name="sheets_get_metadata",
            description="Get spreadsheet metadata (title, sheet/tab names, row and column counts).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                },
                "required": ["account", "spreadsheet_id"],
            },
        ),
        types.Tool(
            name="sheets_get_range",
            description="Read a specific range from a spreadsheet using A1 notation (e.g. 'Sheet1!A1:D10').",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "range": {"type": "string", "description": "Range in A1 notation (e.g. 'Sheet1!A1:D10')"},
                },
                "required": ["account", "spreadsheet_id", "range"],
            },
        ),
        types.Tool(
            name="sheets_get_data",
            description="Read an entire sheet as CSV, JSON (list of row objects using header row as keys), or raw values.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "sheet_name": {"type": "string", "description": "Sheet/tab name (default: 'Sheet1')"},
                    "format": {
                        "type": "string",
                        "description": "Output format: 'csv', 'json', or 'raw' (default: 'csv')",
                        "enum": ["csv", "json", "raw"],
                        "default": "csv",
                    },
                },
                "required": ["account", "spreadsheet_id"],
            },
        ),
        types.Tool(
            name="sheets_create",
            description="Create a new Google Spreadsheet.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "title": {"type": "string", "description": "Spreadsheet title"},
                    "sheet_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Names for the initial sheets/tabs",
                    },
                },
                "required": ["account", "title"],
            },
        ),
        types.Tool(
            name="sheets_update_range",
            description="Write values to a range in a spreadsheet using A1 notation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "range": {"type": "string", "description": "Range in A1 notation (e.g. 'Sheet1!A1:C3')"},
                    "values": {
                        "type": "array",
                        "items": {"type": "array", "items": {}},
                        "description": "2D array of values, e.g. [['Name', 'Age'], ['Alice', 30]]",
                    },
                },
                "required": ["account", "spreadsheet_id", "range", "values"],
            },
        ),
        types.Tool(
            name="sheets_append_rows",
            description="Append rows to the end of a sheet.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "range": {"type": "string", "description": "Sheet name or range to append to (e.g. 'Sheet1')"},
                    "values": {
                        "type": "array",
                        "items": {"type": "array", "items": {}},
                        "description": "Rows to append, e.g. [['Alice', 30], ['Bob', 25]]",
                    },
                },
                "required": ["account", "spreadsheet_id", "range", "values"],
            },
        ),
        types.Tool(
            name="sheets_add_sheet",
            description="Add a new sheet/tab to an existing spreadsheet.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "title": {"type": "string", "description": "Name for the new sheet/tab"},
                },
                "required": ["account", "spreadsheet_id", "title"],
            },
        ),
        # ── Google Slides tools ────────────────────────────────────────────
        types.Tool(
            name="slides_get_text",
            description="Read all text from a Google Slides presentation, organized by slide.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "presentation_id": {"type": "string", "description": "Presentation ID"},
                },
                "required": ["account", "presentation_id"],
            },
        ),
        types.Tool(
            name="slides_get_metadata",
            description="Get presentation metadata (title, slide count, dimensions, speaker notes).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "presentation_id": {"type": "string", "description": "Presentation ID"},
                },
                "required": ["account", "presentation_id"],
            },
        ),
        types.Tool(
            name="slides_create",
            description="Create a new Google Slides presentation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "title": {"type": "string", "description": "Presentation title"},
                },
                "required": ["account", "title"],
            },
        ),
        types.Tool(
            name="slides_add_slide",
            description="Add a new slide to a presentation. Layouts: BLANK, TITLE, TITLE_AND_BODY, TITLE_AND_TWO_COLUMNS, etc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "presentation_id": {"type": "string", "description": "Presentation ID"},
                    "layout": {"type": "string", "description": "Slide layout (default: 'BLANK')", "default": "BLANK"},
                    "insertion_index": {"type": "integer", "description": "Position to insert (0-based). Omit to append."},
                },
                "required": ["account", "presentation_id"],
            },
        ),
        types.Tool(
            name="slides_replace_text",
            description="Find and replace text across all slides in a presentation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "presentation_id": {"type": "string", "description": "Presentation ID"},
                    "find": {"type": "string", "description": "Text to find"},
                    "replace": {"type": "string", "description": "Replacement text"},
                    "match_case": {"type": "boolean", "description": "Case-sensitive (default: true)", "default": True},
                },
                "required": ["account", "presentation_id", "find", "replace"],
            },
        ),
        types.Tool(
            name="slides_insert_text",
            description="Insert text into a specific shape/text box on a slide (by shape object ID).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "presentation_id": {"type": "string", "description": "Presentation ID"},
                    "object_id": {"type": "string", "description": "Shape/text box object ID"},
                    "text": {"type": "string", "description": "Text to insert"},
                    "insertion_index": {"type": "integer", "description": "Character index within the shape (default: 0)", "default": 0},
                },
                "required": ["account", "presentation_id", "object_id", "text"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    args = arguments or {}

    try:
        # ---- list_accounts ------------------------------------------------
        if name == "list_accounts":
            result = []
            for acct, info in _accounts.items():
                authenticated = _auth.is_authenticated(acct)
                result.append({
                    "name": acct,
                    "email": info.get("email", ""),
                    "description": info.get("description", ""),
                    "authenticated": authenticated,
                    "status": "ready" if authenticated else "not authenticated — run setup_auth.py",
                })
            return _fmt(result)

        # ---- gmail_get_profile --------------------------------------------
        elif name == "gmail_get_profile":
            svc = _get_service(args["account"])
            return _fmt(svc.get_profile())

        # ---- gmail_search -------------------------------------------------
        elif name == "gmail_search":
            query: str = args["query"]
            max_results: int = int(args.get("max_results", 10))
            include_body: bool = bool(args.get("include_body", False))
            account: str | None = args.get("account")

            if account:
                svc = _get_service(account)
                data = svc.search_messages(query, max_results, include_body=include_body)
                data["account"] = account
                data["email"] = _accounts[account].get("email", "")
                return _fmt(data)
            else:
                all_results = []
                for acct in _accounts:
                    try:
                        svc = _get_service(acct)
                        data = svc.search_messages(query, max_results, include_body=include_body)
                        all_results.append({
                            "account": acct,
                            "email": _accounts[acct].get("email", ""),
                            **data,
                        })
                    except ValueError as exc:
                        all_results.append({
                            "account": acct,
                            "error": str(exc),
                            "messages": [],
                        })
                return _fmt(all_results)

        # ---- gmail_read_message -------------------------------------------
        elif name == "gmail_read_message":
            svc = _get_service(args["account"])
            return _fmt(svc.get_message(args["message_id"]))

        # ---- gmail_read_thread --------------------------------------------
        elif name == "gmail_read_thread":
            svc = _get_service(args["account"])
            return _fmt(svc.get_thread(args["thread_id"]))

        # ---- gmail_send ---------------------------------------------------
        elif name == "gmail_send":
            svc = _get_service(args["account"])
            result = svc.send_message(
                to=args["to"],
                subject=args["subject"],
                body=args["body"],
                cc=args.get("cc", ""),
                bcc=args.get("bcc", ""),
            )
            return _fmt({
                "status": "sent",
                "message_id": result.get("id"),
                "thread_id": result.get("threadId"),
            })

        # ---- gmail_create_draft -------------------------------------------
        elif name == "gmail_create_draft":
            svc = _get_service(args["account"])
            result = svc.create_draft(
                to=args["to"],
                subject=args["subject"],
                body=args["body"],
                cc=args.get("cc", ""),
                bcc=args.get("bcc", ""),
            )
            return _fmt({"status": "draft created", "draft_id": result.get("id")})

        # ---- gmail_list_drafts --------------------------------------------
        elif name == "gmail_list_drafts":
            svc = _get_service(args["account"])
            drafts = svc.list_drafts(int(args.get("max_results", 10)))
            return _fmt({"count": len(drafts), "drafts": drafts})

        # ---- gmail_list_labels --------------------------------------------
        elif name == "gmail_list_labels":
            svc = _get_service(args["account"])
            return _fmt(svc.list_labels())

        # ---- gmail_modify_labels -----------------------------------------
        elif name == "gmail_modify_labels":
            svc = _get_service(args["account"])
            svc.modify_labels(
                message_id=args["message_id"],
                add_labels=args.get("add_labels"),
                remove_labels=args.get("remove_labels"),
            )
            return _fmt({"status": "labels updated", "message_id": args["message_id"]})

        # ---- gmail_trash -------------------------------------------------
        elif name == "gmail_trash":
            svc = _get_service(args["account"])
            svc.trash_message(args["message_id"])
            return _fmt({"status": "moved to trash", "message_id": args["message_id"]})

        # ---- gmail_send_draft ---------------------------------------------
        elif name == "gmail_send_draft":
            svc = _get_service(args["account"])
            return _fmt(svc.send_draft(args["draft_id"]))

        # ---- gmail_list_attachments ---------------------------------------
        elif name == "gmail_list_attachments":
            svc = _get_service(args["account"])
            attachments = svc.list_attachments(args["message_id"])
            return _fmt({"message_id": args["message_id"], "count": len(attachments), "attachments": attachments})

        # ---- gmail_download_attachment ------------------------------------
        elif name == "gmail_download_attachment":
            svc = _get_service(args["account"])
            return _fmt(svc.download_attachment(args["message_id"], args["attachment_id"]))

        # ---- calendar_list_calendars --------------------------------------
        elif name == "calendar_list_calendars":
            svc = _get_calendar(args["account"])
            return _fmt(svc.list_calendars())

        # ---- calendar_list_events -----------------------------------------
        elif name == "calendar_list_events":
            svc = _get_calendar(args["account"])
            return _fmt(svc.list_events(
                time_min=args.get("time_min"),
                time_max=args.get("time_max"),
                max_results=int(args.get("max_results", 20)),
                calendar_id=args.get("calendar_id", "primary"),
            ))

        # ---- calendar_search ----------------------------------------------
        elif name == "calendar_search":
            svc = _get_calendar(args["account"])
            return _fmt(svc.search_events(
                query=args["query"],
                time_min=args.get("time_min"),
                time_max=args.get("time_max"),
                max_results=int(args.get("max_results", 20)),
                calendar_id=args.get("calendar_id", "primary"),
            ))

        # ---- calendar_get_event -------------------------------------------
        elif name == "calendar_get_event":
            svc = _get_calendar(args["account"])
            return _fmt(svc.get_event(
                event_id=args["event_id"],
                calendar_id=args.get("calendar_id", "primary"),
            ))

        # ---- calendar_create_event ----------------------------------------
        elif name == "calendar_create_event":
            svc = _get_calendar(args["account"])
            return _fmt(svc.create_event(
                summary=args["summary"],
                start=args["start"],
                end=args["end"],
                calendar_id=args.get("calendar_id", "primary"),
                description=args.get("description", ""),
                location=args.get("location", ""),
                attendees=args.get("attendees"),
                all_day=bool(args.get("all_day", False)),
                add_meet=bool(args.get("add_meet", False)),
            ))

        # ---- calendar_update_event ----------------------------------------
        elif name == "calendar_update_event":
            svc = _get_calendar(args["account"])
            return _fmt(svc.update_event(
                event_id=args["event_id"],
                calendar_id=args.get("calendar_id", "primary"),
                summary=args.get("summary"),
                start=args.get("start"),
                end=args.get("end"),
                description=args.get("description"),
                location=args.get("location"),
                attendees=args.get("attendees"),
            ))

        # ---- calendar_delete_event ----------------------------------------
        elif name == "calendar_delete_event":
            svc = _get_calendar(args["account"])
            return _fmt(svc.delete_event(
                event_id=args["event_id"],
                calendar_id=args.get("calendar_id", "primary"),
            ))

        # ---- calendar_respond ---------------------------------------------
        elif name == "calendar_respond":
            svc = _get_calendar(args["account"])
            return _fmt(svc.respond_to_event(
                event_id=args["event_id"],
                response=args["response"],
                calendar_id=args.get("calendar_id", "primary"),
            ))

        # ---- calendar_find_free_time --------------------------------------
        elif name == "calendar_find_free_time":
            svc = _get_calendar(args["account"])
            return _fmt(svc.find_free_time(
                emails=args["emails"],
                time_min=args["time_min"],
                time_max=args["time_max"],
            ))

        # ---- drive_search -------------------------------------------------
        elif name == "drive_search":
            query: str = args["query"]
            max_results: int = int(args.get("max_results", 20))
            account: str | None = args.get("account")

            if account:
                svc = _get_drive(account)
                data = svc.search_files(query, max_results)
                data["account"] = account
                data["email"] = _accounts[account].get("email", "")
                return _fmt(data)
            else:
                all_results = []
                for acct in _accounts:
                    try:
                        svc = _get_drive(acct)
                        data = svc.search_files(query, max_results)
                        all_results.append({
                            "account": acct,
                            "email": _accounts[acct].get("email", ""),
                            **data,
                        })
                    except ValueError as exc:
                        all_results.append({
                            "account": acct,
                            "error": str(exc),
                            "files": [],
                        })
                return _fmt(all_results)

        # ---- drive_list_recent --------------------------------------------
        elif name == "drive_list_recent":
            svc = _get_drive(args["account"])
            return _fmt(svc.list_recent(int(args.get("max_results", 20))))

        # ---- drive_get_file -----------------------------------------------
        elif name == "drive_get_file":
            svc = _get_drive(args["account"])
            return _fmt(svc.get_file(args["file_id"]))

        # ---- drive_read_content -------------------------------------------
        elif name == "drive_read_content":
            svc = _get_drive(args["account"])
            return _fmt(svc.read_content(args["file_id"]))

        # ---- drive_upload -------------------------------------------------
        elif name == "drive_upload":
            svc = _get_drive(args["account"])
            result = svc.upload_file(
                name=args["name"],
                content=args["content"],
                mime_type=args.get("mime_type", "text/plain"),
                parent_folder_id=args.get("parent_folder_id"),
            )
            return _fmt({"status": "uploaded", **result})

        # ---- drive_update -------------------------------------------------
        elif name == "drive_update":
            svc = _get_drive(args["account"])
            result = svc.update_file(
                file_id=args["file_id"],
                content=args["content"],
                mime_type=args.get("mime_type", "text/plain"),
            )
            return _fmt({"status": "updated", **result})

        # ---- drive_create_folder ------------------------------------------
        elif name == "drive_create_folder":
            svc = _get_drive(args["account"])
            result = svc.create_folder(
                name=args["name"],
                parent_folder_id=args.get("parent_folder_id"),
            )
            return _fmt({"status": "folder created", **result})

        # ---- drive_move ---------------------------------------------------
        elif name == "drive_move":
            svc = _get_drive(args["account"])
            result = svc.move_file(args["file_id"], args["new_parent_id"])
            return _fmt({"status": "moved", **result})

        # ---- drive_rename -------------------------------------------------
        elif name == "drive_rename":
            svc = _get_drive(args["account"])
            result = svc.rename_file(args["file_id"], args["new_name"])
            return _fmt({"status": "renamed", **result})

        # ---- drive_trash --------------------------------------------------
        elif name == "drive_trash":
            svc = _get_drive(args["account"])
            result = svc.trash_file(args["file_id"])
            return _fmt({"status": "moved to trash", **result})

        # ---- people_list_contacts -----------------------------------------
        elif name == "people_list_contacts":
            svc = _get_people(args["account"])
            return _fmt(svc.list_contacts(int(args.get("max_results", 50))))

        # ---- people_search ------------------------------------------------
        elif name == "people_search":
            svc = _get_people(args["account"])
            return _fmt(svc.search_contacts(args["query"], int(args.get("max_results", 20))))

        # ---- people_get_contact -------------------------------------------
        elif name == "people_get_contact":
            svc = _get_people(args["account"])
            return _fmt(svc.get_contact(args["resource_name"]))

        # ---- people_create_contact ----------------------------------------
        elif name == "people_create_contact":
            svc = _get_people(args["account"])
            result = svc.create_contact(
                given_name=args["given_name"],
                family_name=args.get("family_name", ""),
                email=args.get("email", ""),
                phone=args.get("phone", ""),
                organization=args.get("organization", ""),
                title=args.get("title", ""),
            )
            return _fmt({"status": "created", **result})

        # ---- people_update_contact ----------------------------------------
        elif name == "people_update_contact":
            svc = _get_people(args["account"])
            result = svc.update_contact(
                resource_name=args["resource_name"],
                given_name=args.get("given_name"),
                family_name=args.get("family_name"),
                email=args.get("email"),
                phone=args.get("phone"),
                organization=args.get("organization"),
                title=args.get("title"),
            )
            return _fmt({"status": "updated", **result})

        # ---- people_delete_contact ----------------------------------------
        elif name == "people_delete_contact":
            svc = _get_people(args["account"])
            return _fmt(svc.delete_contact(args["resource_name"]))

        # ---- docs_get -----------------------------------------------------
        elif name == "docs_get":
            svc = _get_docs(args["account"])
            return _fmt(svc.get_text(args["document_id"]))

        # ---- docs_create --------------------------------------------------
        elif name == "docs_create":
            svc = _get_docs(args["account"])
            return _fmt(svc.create(
                title=args["title"],
                body_text=args.get("body_text", ""),
            ))

        # ---- docs_write ---------------------------------------------------
        elif name == "docs_write":
            svc = _get_docs(args["account"])
            return _fmt(svc.write_text(
                document_id=args["document_id"],
                text=args["text"],
                index=int(args.get("index", 1)),
            ))

        # ---- docs_replace -------------------------------------------------
        elif name == "docs_replace":
            svc = _get_docs(args["account"])
            return _fmt(svc.replace_text(
                document_id=args["document_id"],
                find=args["find"],
                replace=args["replace"],
                match_case=bool(args.get("match_case", True)),
            ))

        # ---- docs_format --------------------------------------------------
        elif name == "docs_format":
            svc = _get_docs(args["account"])
            return _fmt(svc.format_text(
                document_id=args["document_id"],
                start_index=int(args["start_index"]),
                end_index=int(args["end_index"]),
                bold=args.get("bold"),
                italic=args.get("italic"),
                underline=args.get("underline"),
                font_size=int(args["font_size"]) if args.get("font_size") is not None else None,
                link_url=args.get("link_url"),
                named_style=args.get("named_style"),
            ))

        # ---- sheets_get_metadata ------------------------------------------
        elif name == "sheets_get_metadata":
            svc = _get_sheets(args["account"])
            return _fmt(svc.get_metadata(args["spreadsheet_id"]))

        # ---- sheets_get_range ---------------------------------------------
        elif name == "sheets_get_range":
            svc = _get_sheets(args["account"])
            return _fmt(svc.get_range(
                spreadsheet_id=args["spreadsheet_id"],
                range=args["range"],
            ))

        # ---- sheets_get_data ----------------------------------------------
        elif name == "sheets_get_data":
            svc = _get_sheets(args["account"])
            return _fmt(svc.get_data(
                spreadsheet_id=args["spreadsheet_id"],
                sheet_name=args.get("sheet_name"),
                format=args.get("format", "csv"),
            ))

        # ---- sheets_create ------------------------------------------------
        elif name == "sheets_create":
            svc = _get_sheets(args["account"])
            return _fmt(svc.create(
                title=args["title"],
                sheet_names=args.get("sheet_names"),
            ))

        # ---- sheets_update_range ------------------------------------------
        elif name == "sheets_update_range":
            svc = _get_sheets(args["account"])
            return _fmt(svc.update_range(
                spreadsheet_id=args["spreadsheet_id"],
                range=args["range"],
                values=args["values"],
            ))

        # ---- sheets_append_rows -------------------------------------------
        elif name == "sheets_append_rows":
            svc = _get_sheets(args["account"])
            return _fmt(svc.append_rows(
                spreadsheet_id=args["spreadsheet_id"],
                range=args["range"],
                values=args["values"],
            ))

        # ---- sheets_add_sheet ---------------------------------------------
        elif name == "sheets_add_sheet":
            svc = _get_sheets(args["account"])
            return _fmt(svc.add_sheet(
                spreadsheet_id=args["spreadsheet_id"],
                title=args["title"],
            ))

        # ---- slides_get_text ----------------------------------------------
        elif name == "slides_get_text":
            svc = _get_slides(args["account"])
            return _fmt(svc.get_text(args["presentation_id"]))

        # ---- slides_get_metadata ------------------------------------------
        elif name == "slides_get_metadata":
            svc = _get_slides(args["account"])
            return _fmt(svc.get_metadata(args["presentation_id"]))

        # ---- slides_create ------------------------------------------------
        elif name == "slides_create":
            svc = _get_slides(args["account"])
            return _fmt(svc.create(args["title"]))

        # ---- slides_add_slide ---------------------------------------------
        elif name == "slides_add_slide":
            svc = _get_slides(args["account"])
            return _fmt(svc.add_slide(
                presentation_id=args["presentation_id"],
                layout=args.get("layout", "BLANK"),
                insertion_index=int(args["insertion_index"]) if args.get("insertion_index") is not None else None,
            ))

        # ---- slides_replace_text ------------------------------------------
        elif name == "slides_replace_text":
            svc = _get_slides(args["account"])
            return _fmt(svc.replace_text(
                presentation_id=args["presentation_id"],
                find=args["find"],
                replace=args["replace"],
                match_case=bool(args.get("match_case", True)),
            ))

        # ---- slides_insert_text -------------------------------------------
        elif name == "slides_insert_text":
            svc = _get_slides(args["account"])
            return _fmt(svc.insert_text(
                presentation_id=args["presentation_id"],
                object_id=args["object_id"],
                text=args["text"],
                insertion_index=int(args.get("insertion_index", 0)),
            ))

        else:
            return _fmt(f"Unknown tool: {name}")

    except ValueError as exc:
        return _fmt(f"Error: {exc}")
    except Exception as exc:
        return _fmt(f"Error in '{name}': {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
