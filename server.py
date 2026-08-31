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
from googleapiclient.errors import HttpError
from mcp.server import Server
from mcp.server.stdio import stdio_server

from auth import AuthManager
from config import get_accounts, get_client_secret_path, get_credentials_dir, load_config
from gapi import describe_http_error
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


def _describe(exc: BaseException) -> str:
    """Readable one-liner for an exception raised by a Google API call."""
    if isinstance(exc, HttpError):
        return describe_http_error(exc)
    return f"{type(exc).__name__}: {exc}"


async def _fan_out(call, empty_key: str) -> list[dict]:
    """Run `call(account_name)` against every configured account concurrently.

    Each account contributes one result object. Failures (unauthenticated,
    rate-limited, revoked scope) are reported inline with an empty
    `empty_key` list so one bad account never sinks the whole search.
    """

    async def one(acct: str) -> dict:
        header = {"account": acct, "email": _accounts[acct].get("email", "")}
        try:
            data = await asyncio.to_thread(call, acct)
        except Exception as exc:
            return {**header, "error": _describe(exc), empty_key: []}
        return {**header, **data}

    return list(await asyncio.gather(*(one(acct) for acct in _accounts)))


async def _verify_identities(rows: list[dict]) -> None:
    """Annotate `rows` in place with each token's real Google identity.

    `list_accounts` otherwise echoes the email straight out of config.json, so
    an account whose config was edited without re-running setup_auth.py reads
    as correct while every call still runs as the previous account. One
    getProfile per authenticated account, concurrently.
    """

    def identity(acct: str) -> str:
        return _get_service(acct).get_profile().get("emailAddress", "")

    async def one(row: dict) -> None:
        if not row["authenticated"]:
            return
        try:
            actual = await asyncio.to_thread(identity, row["name"])
        except Exception as exc:
            row["verified_email"] = None
            row["verify_error"] = _describe(exc)
            row["status"] = "ready — token identity could not be verified"
            return

        configured = row["email"]
        row["verified_email"] = actual
        row["email_mismatch"] = bool(
            configured and actual and actual.lower() != configured.lower()
        )
        if row["email_mismatch"]:
            row["status"] = (
                f"MISMATCH — this token is for {actual}, but config.json says "
                f"{configured}. Every call on '{row['name']}' runs as {actual}. "
                "Re-run setup_auth.py and sign in as the configured account."
            )
        else:
            row["status"] = "ready — token identity verified"

    await asyncio.gather(*(one(row) for row in rows))


def _fmt(data: Any) -> list[types.TextContent]:
    if isinstance(data, str):
        return [types.TextContent(type="text", text=data)]
    return [types.TextContent(type="text", text=json.dumps(data, indent=2, ensure_ascii=False))]


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

server = Server("google-workspace")


# ---------------------------------------------------------------------------
# Tool annotations
# ---------------------------------------------------------------------------
# MCP clients use these hints to decide what needs a confirmation prompt.
# Anything not listed as read-only is treated as a write; writes are additive
# unless listed as destructive.

# Tools that touch nothing, locally or remotely.
# Deliberately excluded: gmail_download_attachment, drive_read_content and
# drive_export all accept a save_path and can overwrite a local file.
_READ_ONLY_TOOLS = frozenset({
    "list_accounts",
    "gmail_get_profile", "gmail_search", "gmail_read_message", "gmail_read_thread",
    "gmail_list_drafts", "gmail_list_labels", "gmail_list_attachments",
    "gmail_list_send_as", "gmail_list_filters", "gmail_get_vacation",
    "calendar_list_calendars", "calendar_list_events", "calendar_search",
    "calendar_get_event", "calendar_find_free_time", "calendar_suggest_slots",
    "calendar_list_instances",
    "drive_search", "drive_list_recent", "drive_get_file", "drive_list_permissions",
    "people_list_contacts", "people_search", "people_get_contact",
    "people_list_other_contacts", "people_list_groups",
    "docs_get",
    "sheets_get_metadata", "sheets_get_range", "sheets_get_data", "sheets_batch_get",
    "slides_get_text", "slides_get_metadata",
})

# Writes that can delete or overwrite existing content. Renames, moves and
# formatting are not here: they change metadata or presentation, not content.
# sheets_merge_cells is, because Sheets keeps only the top-left value.
# The three raw batch_update passthroughs are, because they can express
# anything the underlying API can, including deletes.
_DESTRUCTIVE_TOOLS = frozenset({
    "gmail_trash", "gmail_delete_label", "gmail_delete_filter", "gmail_set_vacation",
    "calendar_update_event", "calendar_delete_event", "calendar_delete_calendar",
    "drive_update", "drive_trash", "drive_remove_permission",
    "people_update_contact", "people_delete_contact",
    "docs_replace", "docs_batch_update",
    "sheets_update_range", "sheets_clear_range", "sheets_delete_sheet",
    "sheets_merge_cells", "sheets_batch_update",
    "slides_replace_text", "slides_delete_object", "slides_set_speaker_notes",
    "slides_batch_update",
})


def _annotate(tools: list[types.Tool]) -> list[types.Tool]:
    """Attach read-only / destructive hints to every tool."""
    names = {tool.name for tool in tools}
    unknown = (_READ_ONLY_TOOLS | _DESTRUCTIVE_TOOLS) - names
    if unknown:
        print(
            f"WARNING: annotation lists name tools that do not exist: {sorted(unknown)}",
            file=sys.stderr,
        )

    for tool in tools:
        read_only = tool.name in _READ_ONLY_TOOLS
        tool.annotations = types.ToolAnnotations(
            readOnlyHint=read_only,
            destructiveHint=False if read_only else tool.name in _DESTRUCTIVE_TOOLS,
            openWorldHint=True,
        )
    return tools


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return _annotate([
        types.Tool(
            name="list_accounts",
            description=(
                "List all Google accounts configured in this MCP server, along with "
                "their authentication status. By default the email shown is the one "
                "recorded in config.json, which is not proof of what the stored token "
                "actually signs in as — pass verify=true to check that against Google."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "verify": {
                        "type": "boolean",
                        "description": (
                            "Confirm each authenticated account's token against Google and "
                            "report the identity it really signs in as as 'verified_email', "
                            "flagging any that disagrees with config.json. Costs one API "
                            "call per account, so it is off by default. Use it after "
                            "editing an email in config.json or re-authenticating."
                        ),
                    }
                },
            },
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
                    "page_token": {"type": "string", "description": "Page token from a previous call's nextPageToken, to fetch the next page. Only valid together with 'account' \u2014 tokens are per-account and cannot be reused across a multi-account search."},
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
                    "from_alias": {"type": "string", "description": "Send from a verified send-as alias instead of the account's primary address. Accepts 'alias@example.com' or 'Name <alias@example.com>'. Use gmail_list_send_as to see valid values."},
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
                    "html_body": {"type": "string", "description": "HTML body (optional; sent as a multipart alternative alongside the plain-text body)"},
                    "attachments": {"type": "array", "items": {"type": "string"}, "description": "Local file paths to attach (optional)"},
                    "thread_id": {"type": "string", "description": "Gmail thread ID to attach this message to (optional)"},
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
                    "from_alias": {"type": "string", "description": "Send from a verified send-as alias instead of the account's primary address. Accepts 'alias@example.com' or 'Name <alias@example.com>'. Use gmail_list_send_as to see valid values."},
                    "account": {
                        "type": "string",
                        "description": "Account to create the draft in",
                    },
                    "to": {"type": "string", "description": "Recipient(s), comma-separated"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body (plain text)"},
                    "cc": {"type": "string", "description": "CC recipients"},
                    "bcc": {"type": "string", "description": "BCC recipients"},
                    "html_body": {"type": "string", "description": "HTML body (optional)"},
                    "attachments": {"type": "array", "items": {"type": "string"}, "description": "Local file paths to attach (optional)"},
                    "thread_id": {"type": "string", "description": "Gmail thread ID to attach this draft to (optional)"},
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
                    "save_path": {"type": "string", "description": "Local path to save the attachment to (optional; if omitted, base64 content is returned)"},
                },
                "required": ["account", "message_id", "attachment_id"],
            },
        ),
        types.Tool(
            name="gmail_reply",
            description=(
                "Reply to a Gmail message, preserving the thread (sets In-Reply-To/References and threadId). "
                "reply_all also includes the original To/Cc recipients."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "from_alias": {"type": "string", "description": "Send from a verified send-as alias instead of the account's primary address. Accepts 'alias@example.com' or 'Name <alias@example.com>'. Use gmail_list_send_as to see valid values."},
                    "account": {"type": "string", "description": "Account name"},
                    "message_id": {"type": "string", "description": "Message ID to reply to"},
                    "body": {"type": "string", "description": "Reply body (plain text)"},
                    "reply_all": {"type": "boolean", "description": "Reply to all original recipients (default false)", "default": False},
                    "html_body": {"type": "string", "description": "HTML body (optional)"},
                    "attachments": {"type": "array", "items": {"type": "string"}, "description": "Local file paths to attach (optional)"},
                },
                "required": ["account", "message_id", "body"],
            },
        ),
        types.Tool(
            name="gmail_forward",
            description="Forward a Gmail message to new recipients, quoting the original.",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_alias": {"type": "string", "description": "Send from a verified send-as alias instead of the account's primary address. Accepts 'alias@example.com' or 'Name <alias@example.com>'. Use gmail_list_send_as to see valid values."},
                    "account": {"type": "string", "description": "Account name"},
                    "message_id": {"type": "string", "description": "Message ID to forward"},
                    "to": {"type": "string", "description": "Recipient(s), comma-separated"},
                    "body": {"type": "string", "description": "Optional note to prepend"},
                    "cc": {"type": "string", "description": "CC recipients"},
                    "bcc": {"type": "string", "description": "BCC recipients"},
                },
                "required": ["account", "message_id", "to"],
            },
        ),
        types.Tool(
            name="gmail_create_label",
            description="Create a new Gmail label.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "name": {"type": "string", "description": "Label name (use 'Parent/Child' for nesting)"},
                    "label_list_visibility": {"type": "string", "description": "labelShow | labelHide | labelShowIfUnread", "default": "labelShow"},
                    "message_list_visibility": {"type": "string", "description": "show | hide", "default": "show"},
                },
                "required": ["account", "name"],
            },
        ),
        types.Tool(
            name="gmail_update_label",
            description="Rename or change visibility of an existing Gmail label.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "label_id": {"type": "string", "description": "Label ID"},
                    "name": {"type": "string", "description": "New name (optional)"},
                    "label_list_visibility": {"type": "string", "description": "labelShow | labelHide | labelShowIfUnread"},
                    "message_list_visibility": {"type": "string", "description": "show | hide"},
                },
                "required": ["account", "label_id"],
            },
        ),
        types.Tool(
            name="gmail_delete_label",
            description="Delete a Gmail label.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "label_id": {"type": "string", "description": "Label ID"},
                },
                "required": ["account", "label_id"],
            },
        ),
        types.Tool(
            name="gmail_batch_modify",
            description="Add/remove labels on many Gmail messages at once.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "message_ids": {"type": "array", "items": {"type": "string"}, "description": "Message IDs to modify"},
                    "add_labels": {"type": "array", "items": {"type": "string"}, "description": "Label IDs to add"},
                    "remove_labels": {"type": "array", "items": {"type": "string"}, "description": "Label IDs to remove"},
                },
                "required": ["account", "message_ids"],
            },
        ),
        types.Tool(
            name="gmail_modify_thread_labels",
            description="Add/remove labels on every message in a Gmail thread.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "thread_id": {"type": "string", "description": "Gmail thread ID"},
                    "add_labels": {"type": "array", "items": {"type": "string"}, "description": "Label IDs to add"},
                    "remove_labels": {"type": "array", "items": {"type": "string"}, "description": "Label IDs to remove"},
                },
                "required": ["account", "thread_id"],
            },
        ),
        types.Tool(
            name="gmail_mark_read",
            description="Mark a Gmail message as read (removes the UNREAD label).",
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
            name="gmail_mark_unread",
            description="Mark a Gmail message as unread (adds the UNREAD label).",
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
            name="gmail_untrash",
            description="Restore a Gmail message from the Trash.",
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
            name="gmail_list_send_as",
            description=(
                "List the addresses this account can send mail as: the primary address plus any "
                "aliases. Entries with usable=true may be passed as 'from_alias' to gmail_send, "
                "gmail_create_draft, gmail_reply and gmail_forward."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                },
                "required": ["account"],
            },
        ),
        types.Tool(
            name="gmail_list_filters",
            description="List Gmail filters (rules) for an account.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                },
                "required": ["account"],
            },
        ),
        types.Tool(
            name="gmail_create_filter",
            description=(
                "Create a Gmail filter. `criteria` keys: from, to, subject, query, negatedQuery, hasAttachment, size. "
                "`action` keys: addLabelIds, removeLabelIds, forward."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "criteria": {"type": "object", "description": "Filter criteria object"},
                    "action": {"type": "object", "description": "Filter action object"},
                },
                "required": ["account", "criteria", "action"],
            },
        ),
        types.Tool(
            name="gmail_delete_filter",
            description="Delete a Gmail filter by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "filter_id": {"type": "string", "description": "Filter ID (from gmail_list_filters)"},
                },
                "required": ["account", "filter_id"],
            },
        ),
        types.Tool(
            name="gmail_get_vacation",
            description="Get the current vacation responder (out-of-office) settings.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                },
                "required": ["account"],
            },
        ),
        types.Tool(
            name="gmail_set_vacation",
            description="Enable or disable the Gmail vacation responder (out-of-office auto-reply).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "enabled": {"type": "boolean", "description": "Turn the auto-reply on or off"},
                    "subject": {"type": "string", "description": "Auto-reply subject"},
                    "body": {"type": "string", "description": "Auto-reply plain-text body"},
                    "html_body": {"type": "string", "description": "Auto-reply HTML body (optional)"},
                    "restrict_to_contacts": {"type": "boolean", "description": "Only reply to known contacts", "default": False},
                    "restrict_to_domain": {"type": "boolean", "description": "Only reply within your organization", "default": False},
                    "start_time": {"type": "integer", "description": "Start time as epoch milliseconds (optional)"},
                    "end_time": {"type": "integer", "description": "End time as epoch milliseconds (optional)"},
                },
                "required": ["account", "enabled"],
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
                    "page_token": {"type": "string", "description": "Page token from a previous call's nextPageToken, to fetch the next page."},
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
                    "page_token": {"type": "string", "description": "Page token from a previous call's nextPageToken, to fetch the next page."},
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
                    "recurrence": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Recurrence rules, e.g. ['RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=10']",
                    },
                    "reminders": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Override reminders, e.g. [{'method':'popup','minutes':10}]",
                    },
                    "visibility": {"type": "string", "description": "default | public | private | confidential"},
                    "color_id": {"type": "string", "description": "Calendar color ID (1-11)"},
                },
                "required": ["account", "summary", "start", "end"],
            },
        ),
        types.Tool(
            name="calendar_update_event",
            description="Update fields on an existing calendar event (patch — only the fields you pass are changed).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "event_id": {"type": "string", "description": "Event ID"},
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: 'primary')", "default": "primary"},
                    "summary": {"type": "string", "description": "New title"},
                    "start": {"type": "string", "description": "New start time (RFC3339) or date (YYYY-MM-DD)"},
                    "end": {"type": "string", "description": "New end time (RFC3339) or date (YYYY-MM-DD)"},
                    "description": {"type": "string", "description": "New description"},
                    "location": {"type": "string", "description": "New location"},
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Replace attendees with this list of emails",
                    },
                    "recurrence": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Replace recurrence rules, e.g. ['RRULE:FREQ=DAILY;COUNT=5']",
                    },
                    "reminders": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Override reminders, e.g. [{'method':'email','minutes':60}]",
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
        types.Tool(
            name="calendar_suggest_slots",
            description=(
                "Suggest open meeting slots for a group by scanning everyone's free/busy. "
                "Returns up to max_slots time windows of duration_minutes within working hours (UTC)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "emails": {"type": "array", "items": {"type": "string"}, "description": "Attendee emails to check"},
                    "time_min": {"type": "string", "description": "Earliest time to consider (RFC3339)"},
                    "time_max": {"type": "string", "description": "Latest time to consider (RFC3339)"},
                    "duration_minutes": {"type": "integer", "description": "Meeting length in minutes (default 30)", "default": 30},
                    "day_start_hour": {"type": "integer", "description": "Earliest hour of day, UTC (default 9)", "default": 9},
                    "day_end_hour": {"type": "integer", "description": "Latest hour of day, UTC (default 18)", "default": 18},
                    "max_slots": {"type": "integer", "description": "Max slots to return (default 10)", "default": 10},
                },
                "required": ["account", "emails", "time_min", "time_max"],
            },
        ),
        types.Tool(
            name="calendar_quick_add",
            description="Create an event from natural language, e.g. 'Lunch with Sam tomorrow at noon'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "text": {"type": "string", "description": "Natural-language event description"},
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: 'primary')", "default": "primary"},
                },
                "required": ["account", "text"],
            },
        ),
        types.Tool(
            name="calendar_move_event",
            description="Move an event from one calendar to another.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "event_id": {"type": "string", "description": "Event ID"},
                    "destination_calendar_id": {"type": "string", "description": "Target calendar ID"},
                    "source_calendar_id": {"type": "string", "description": "Source calendar ID (default: 'primary')", "default": "primary"},
                },
                "required": ["account", "event_id", "destination_calendar_id"],
            },
        ),
        types.Tool(
            name="calendar_list_instances",
            description="List the individual instances of a recurring event.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "event_id": {"type": "string", "description": "Recurring event ID"},
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: 'primary')", "default": "primary"},
                    "time_min": {"type": "string", "description": "Start of range (RFC3339, optional)"},
                    "time_max": {"type": "string", "description": "End of range (RFC3339, optional)"},
                    "max_results": {"type": "integer", "description": "Max instances (default 25)", "default": 25},
                },
                "required": ["account", "event_id"],
            },
        ),
        types.Tool(
            name="calendar_create_calendar",
            description="Create a new secondary calendar.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "summary": {"type": "string", "description": "Calendar name"},
                    "description": {"type": "string", "description": "Calendar description (optional)"},
                    "time_zone": {"type": "string", "description": "IANA time zone, e.g. 'America/Los_Angeles' (optional)"},
                },
                "required": ["account", "summary"],
            },
        ),
        types.Tool(
            name="calendar_delete_calendar",
            description="Delete a secondary calendar (cannot delete the primary calendar).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "calendar_id": {"type": "string", "description": "Calendar ID to delete"},
                },
                "required": ["account", "calendar_id"],
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
                    "page_token": {"type": "string", "description": "Page token from a previous call's nextPageToken, to fetch the next page. Only valid together with 'account' \u2014 tokens are per-account and cannot be reused across a multi-account search."},
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
                    "page_token": {"type": "string", "description": "Page token from a previous call's nextPageToken, to fetch the next page."},
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
                    "save_path": {"type": "string", "description": "Local path to save binary content to (optional; otherwise base64 is returned)"},
                    "export_mime": {"type": "string", "description": "Override export format for Workspace files, e.g. 'application/pdf' (optional)"},
                },
                "required": ["account", "file_id"],
            },
        ),
        types.Tool(
            name="drive_upload",
            description="Upload a new file to Google Drive from text content or a local file path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "name": {"type": "string", "description": "File name (e.g. 'notes.txt', 'data.csv')"},
                    "content": {"type": "string", "description": "File content as text (omit if using source_path)"},
                    "mime_type": {
                        "type": "string",
                        "description": "MIME type (default: 'text/plain'). Use 'text/csv' for CSV, etc.",
                        "default": "text/plain",
                    },
                    "parent_folder_id": {
                        "type": "string",
                        "description": "Parent folder ID. Omit for root.",
                    },
                    "source_path": {"type": "string", "description": "Local file path to upload (binary-safe). Takes precedence over content."},
                },
                "required": ["account", "name"],
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
        types.Tool(
            name="drive_copy",
            description="Make a copy of a Drive file, optionally with a new name and parent folder.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "file_id": {"type": "string", "description": "File ID to copy"},
                    "name": {"type": "string", "description": "Name for the copy (optional)"},
                    "parent_folder_id": {"type": "string", "description": "Destination folder ID (optional)"},
                },
                "required": ["account", "file_id"],
            },
        ),
        types.Tool(
            name="drive_share",
            description=(
                "Share a Drive file/folder by granting a permission. "
                "type: user|group (needs email), domain (needs domain), or anyone."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "file_id": {"type": "string", "description": "File or folder ID"},
                    "role": {"type": "string", "description": "reader | commenter | writer | owner", "default": "reader"},
                    "type": {"type": "string", "description": "user | group | domain | anyone", "default": "user"},
                    "email": {"type": "string", "description": "Email for user/group grants"},
                    "domain": {"type": "string", "description": "Domain for domain grants"},
                    "notify": {"type": "boolean", "description": "Send notification email (user/group only)", "default": True},
                    "message": {"type": "string", "description": "Custom message for the notification email"},
                },
                "required": ["account", "file_id"],
            },
        ),
        types.Tool(
            name="drive_list_permissions",
            description="List who has access to a Drive file or folder.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "file_id": {"type": "string", "description": "File or folder ID"},
                },
                "required": ["account", "file_id"],
            },
        ),
        types.Tool(
            name="drive_remove_permission",
            description="Revoke a permission (access grant) from a Drive file or folder.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "file_id": {"type": "string", "description": "File or folder ID"},
                    "permission_id": {"type": "string", "description": "Permission ID (from drive_list_permissions)"},
                },
                "required": ["account", "file_id", "permission_id"],
            },
        ),
        types.Tool(
            name="drive_export",
            description="Export a Google Workspace file to a given format (e.g. 'application/pdf', 'text/csv').",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "file_id": {"type": "string", "description": "Workspace file ID (Doc/Sheet/Slides)"},
                    "mime_type": {"type": "string", "description": "Target MIME type, e.g. 'application/pdf'"},
                    "save_path": {"type": "string", "description": "Local path to save to (optional; otherwise base64 is returned)"},
                },
                "required": ["account", "file_id", "mime_type"],
            },
        ),
        types.Tool(
            name="drive_untrash",
            description="Restore a Drive file or folder from the trash.",
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
                    "page_token": {"type": "string", "description": "Page token from a previous call's nextPageToken, to fetch the next page."},
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
            description="Create a new Google Contact. Supports multiple emails/phones and notes/birthday/URLs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "given_name": {"type": "string", "description": "First name"},
                    "family_name": {"type": "string", "description": "Last name"},
                    "middle_name": {"type": "string", "description": "Middle name"},
                    "email": {"type": "string", "description": "Single email (convenience; merged with 'emails')"},
                    "emails": {"type": "array", "items": {"type": "string"}, "description": "Email addresses"},
                    "phone": {"type": "string", "description": "Single phone (convenience; merged with 'phones')"},
                    "phones": {"type": "array", "items": {"type": "string"}, "description": "Phone numbers"},
                    "organization": {"type": "string", "description": "Company/organization name"},
                    "title": {"type": "string", "description": "Job title"},
                    "notes": {"type": "string", "description": "Freeform notes / biography"},
                    "birthday": {"type": "string", "description": "Birthday as 'YYYY-MM-DD' or 'MM-DD'"},
                    "urls": {"type": "array", "items": {"type": "string"}, "description": "Website URLs"},
                },
                "required": ["account", "given_name"],
            },
        ),
        types.Tool(
            name="people_update_contact",
            description="Update an existing Google Contact. Only pass the fields you want to change (lists replace).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "resource_name": {"type": "string", "description": "Contact resource name"},
                    "given_name": {"type": "string", "description": "New first name"},
                    "family_name": {"type": "string", "description": "New last name"},
                    "middle_name": {"type": "string", "description": "New middle name"},
                    "email": {"type": "string", "description": "Replace emails with this single address"},
                    "emails": {"type": "array", "items": {"type": "string"}, "description": "Replace all emails"},
                    "phone": {"type": "string", "description": "Replace phones with this single number"},
                    "phones": {"type": "array", "items": {"type": "string"}, "description": "Replace all phones"},
                    "organization": {"type": "string", "description": "New company name"},
                    "title": {"type": "string", "description": "New job title"},
                    "notes": {"type": "string", "description": "New notes / biography"},
                    "birthday": {"type": "string", "description": "New birthday 'YYYY-MM-DD' or 'MM-DD'"},
                    "urls": {"type": "array", "items": {"type": "string"}, "description": "Replace all URLs"},
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
        types.Tool(
            name="people_list_other_contacts",
            description="List auto-collected 'Other contacts' (people you've emailed but not saved).",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_token": {"type": "string", "description": "Page token from a previous call's nextPageToken, to fetch the next page."},
                    "account": {"type": "string", "description": "Account name"},
                    "max_results": {"type": "integer", "description": "Max to return (default 50)", "default": 50},
                },
                "required": ["account"],
            },
        ),
        types.Tool(
            name="people_list_groups",
            description="List Google Contacts groups (labels).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "max_results": {"type": "integer", "description": "Max to return (default 50)", "default": 50},
                },
                "required": ["account"],
            },
        ),
        types.Tool(
            name="people_create_group",
            description="Create a new Google Contacts group (label).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "name": {"type": "string", "description": "Group name"},
                },
                "required": ["account", "name"],
            },
        ),
        types.Tool(
            name="people_add_to_group",
            description="Add contacts to a group (label) by their resource names.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "group_resource_name": {"type": "string", "description": "Group resource name (e.g. 'contactGroups/abc')"},
                    "contact_resource_names": {"type": "array", "items": {"type": "string"}, "description": "Contact resource names to add"},
                },
                "required": ["account", "group_resource_name", "contact_resource_names"],
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
                    "tab_id": {"type": "string", "description": "Target tab ID (optional; defaults to the first tab). Get IDs from docs_get."},
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
                    "tab_ids": {"type": "array", "items": {"type": "string"}, "description": "Restrict the replace to these tab IDs (optional; default = all tabs)"},
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
                    "tab_id": {"type": "string", "description": "Target tab ID (optional; defaults to the first tab). Get IDs from docs_get."},
                },
                "required": ["account", "document_id", "start_index", "end_index"],
            },
        ),
        types.Tool(
            name="docs_insert_table",
            description="Insert a table with the given rows and columns at a character index in a Google Doc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "document_id": {"type": "string", "description": "Google Doc ID"},
                    "rows": {"type": "integer", "description": "Number of rows"},
                    "columns": {"type": "integer", "description": "Number of columns"},
                    "index": {"type": "integer", "description": "Character index to insert at (default: 1)", "default": 1},
                    "tab_id": {"type": "string", "description": "Target tab ID (optional; defaults to first tab)"},
                },
                "required": ["account", "document_id", "rows", "columns"],
            },
        ),
        types.Tool(
            name="docs_insert_image",
            description="Insert an inline image from a public URL at a character index in a Google Doc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "document_id": {"type": "string", "description": "Google Doc ID"},
                    "image_url": {"type": "string", "description": "Publicly accessible image URL (PNG/JPEG/GIF)"},
                    "index": {"type": "integer", "description": "Character index to insert at (default: 1)", "default": 1},
                    "width_pt": {"type": "number", "description": "Width in points (optional)"},
                    "height_pt": {"type": "number", "description": "Height in points (optional)"},
                    "tab_id": {"type": "string", "description": "Target tab ID (optional)"},
                },
                "required": ["account", "document_id", "image_url"],
            },
        ),
        types.Tool(
            name="docs_insert_page_break",
            description="Insert a page break at a character index in a Google Doc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "document_id": {"type": "string", "description": "Google Doc ID"},
                    "index": {"type": "integer", "description": "Character index (default: 1)", "default": 1},
                    "tab_id": {"type": "string", "description": "Target tab ID (optional)"},
                },
                "required": ["account", "document_id"],
            },
        ),
        types.Tool(
            name="docs_create_bullets",
            description="Turn a range of paragraphs into a bulleted or numbered list in a Google Doc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "document_id": {"type": "string", "description": "Google Doc ID"},
                    "start_index": {"type": "integer", "description": "Start character index of the range"},
                    "end_index": {"type": "integer", "description": "End character index of the range"},
                    "ordered": {"type": "boolean", "description": "True = numbered list, False = bullet list (default)", "default": False},
                    "tab_id": {"type": "string", "description": "Target tab ID (optional)"},
                },
                "required": ["account", "document_id", "start_index", "end_index"],
            },
        ),
        types.Tool(
            name="docs_batch_update",
            description=(
                "Advanced: run a raw Google Docs API batchUpdate. `requests` is a list of Docs API "
                "Request objects (insertText, updateTableCellStyle, insertInlineImage, etc.). "
                "Use this for anything the dedicated docs_* tools don't cover."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "document_id": {"type": "string", "description": "Google Doc ID"},
                    "requests": {"type": "array", "description": "List of Docs API Request objects", "items": {"type": "object"}},
                },
                "required": ["account", "document_id", "requests"],
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
        types.Tool(
            name="sheets_format_cells",
            description=(
                "Format a rectangular block of cells (0-based, end-exclusive indices). "
                "Get sheet_id from sheets_get_metadata. Colors are hex like '#FFCC00'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "sheet_id": {"type": "integer", "description": "Numeric sheet ID (from sheets_get_metadata)"},
                    "start_row": {"type": "integer", "description": "Start row index (0-based)"},
                    "end_row": {"type": "integer", "description": "End row index (exclusive)"},
                    "start_col": {"type": "integer", "description": "Start column index (0-based)"},
                    "end_col": {"type": "integer", "description": "End column index (exclusive)"},
                    "bold": {"type": "boolean", "description": "Bold text"},
                    "italic": {"type": "boolean", "description": "Italic text"},
                    "font_size": {"type": "integer", "description": "Font size in points"},
                    "background_color": {"type": "string", "description": "Cell background hex, e.g. '#FFF2CC'"},
                    "text_color": {"type": "string", "description": "Text color hex"},
                    "number_format": {"type": "string", "description": "Named type (CURRENCY/PERCENT/DATE/...) or a pattern like '#,##0.00'"},
                    "horizontal_alignment": {"type": "string", "description": "LEFT | CENTER | RIGHT"},
                },
                "required": ["account", "spreadsheet_id", "sheet_id", "start_row", "end_row", "start_col", "end_col"],
            },
        ),
        types.Tool(
            name="sheets_clear_range",
            description="Clear the values in a range (A1 notation), leaving formatting intact.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "range": {"type": "string", "description": "A1 range, e.g. 'Sheet1!A2:D100'"},
                },
                "required": ["account", "spreadsheet_id", "range"],
            },
        ),
        types.Tool(
            name="sheets_delete_sheet",
            description="Delete a sheet/tab by its numeric sheet ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "sheet_id": {"type": "integer", "description": "Numeric sheet ID (from sheets_get_metadata)"},
                },
                "required": ["account", "spreadsheet_id", "sheet_id"],
            },
        ),
        types.Tool(
            name="sheets_rename_sheet",
            description="Rename a sheet/tab by its numeric sheet ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "sheet_id": {"type": "integer", "description": "Numeric sheet ID"},
                    "title": {"type": "string", "description": "New sheet name"},
                },
                "required": ["account", "spreadsheet_id", "sheet_id", "title"],
            },
        ),
        types.Tool(
            name="sheets_duplicate_sheet",
            description="Duplicate a sheet/tab within the same spreadsheet.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "sheet_id": {"type": "integer", "description": "Numeric sheet ID to duplicate"},
                    "new_title": {"type": "string", "description": "Name for the duplicate (optional)"},
                },
                "required": ["account", "spreadsheet_id", "sheet_id"],
            },
        ),
        types.Tool(
            name="sheets_batch_get",
            description="Read several ranges at once (A1 notation). Returns a value range per input range.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "ranges": {"type": "array", "items": {"type": "string"}, "description": "A1 ranges, e.g. ['Sheet1!A1:B2','Sheet2!C:C']"},
                    "value_render": {"type": "string", "description": "FORMATTED_VALUE | UNFORMATTED_VALUE | FORMULA", "default": "FORMATTED_VALUE"},
                },
                "required": ["account", "spreadsheet_id", "ranges"],
            },
        ),
        types.Tool(
            name="sheets_freeze",
            description="Freeze header rows and/or columns on a sheet.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "sheet_id": {"type": "integer", "description": "Numeric sheet ID"},
                    "rows": {"type": "integer", "description": "Number of rows to freeze (default 0)", "default": 0},
                    "cols": {"type": "integer", "description": "Number of columns to freeze (default 0)", "default": 0},
                },
                "required": ["account", "spreadsheet_id", "sheet_id"],
            },
        ),
        types.Tool(
            name="sheets_merge_cells",
            description="Merge a block of cells (0-based, end-exclusive indices).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "sheet_id": {"type": "integer", "description": "Numeric sheet ID"},
                    "start_row": {"type": "integer", "description": "Start row (0-based)"},
                    "end_row": {"type": "integer", "description": "End row (exclusive)"},
                    "start_col": {"type": "integer", "description": "Start column (0-based)"},
                    "end_col": {"type": "integer", "description": "End column (exclusive)"},
                    "merge_type": {"type": "string", "description": "MERGE_ALL | MERGE_COLUMNS | MERGE_ROWS", "default": "MERGE_ALL"},
                },
                "required": ["account", "spreadsheet_id", "sheet_id", "start_row", "end_row", "start_col", "end_col"],
            },
        ),
        types.Tool(
            name="sheets_batch_update",
            description=(
                "Advanced: run a raw Google Sheets API batchUpdate. `requests` is a list of Sheets API "
                "Request objects (addChart, setDataValidation, conditional formatting, sort, etc.)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "requests": {"type": "array", "items": {"type": "object"}, "description": "List of Sheets API Request objects"},
                },
                "required": ["account", "spreadsheet_id", "requests"],
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
        types.Tool(
            name="slides_create_textbox",
            description=(
                "Create a text box on a slide and optionally fill it with text. "
                "Position/size are in points (PT). Returns the new object ID."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "presentation_id": {"type": "string", "description": "Presentation ID"},
                    "slide_object_id": {"type": "string", "description": "Slide (page) object ID to place the box on"},
                    "text": {"type": "string", "description": "Text to insert (optional)"},
                    "x": {"type": "number", "description": "Left offset in points (default 100)", "default": 100},
                    "y": {"type": "number", "description": "Top offset in points (default 100)", "default": 100},
                    "width": {"type": "number", "description": "Width in points (default 300)", "default": 300},
                    "height": {"type": "number", "description": "Height in points (default 100)", "default": 100},
                },
                "required": ["account", "presentation_id", "slide_object_id"],
            },
        ),
        types.Tool(
            name="slides_create_image",
            description="Place an image from a public URL onto a slide. Position/size in points (PT).",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "presentation_id": {"type": "string", "description": "Presentation ID"},
                    "slide_object_id": {"type": "string", "description": "Slide (page) object ID"},
                    "image_url": {"type": "string", "description": "Publicly accessible image URL"},
                    "x": {"type": "number", "description": "Left offset in points (default 100)", "default": 100},
                    "y": {"type": "number", "description": "Top offset in points (default 100)", "default": 100},
                    "width": {"type": "number", "description": "Width in points (default 300)", "default": 300},
                    "height": {"type": "number", "description": "Height in points (default 200)", "default": 200},
                },
                "required": ["account", "presentation_id", "slide_object_id", "image_url"],
            },
        ),
        types.Tool(
            name="slides_delete_object",
            description="Delete a shape, image, or slide by its object ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "presentation_id": {"type": "string", "description": "Presentation ID"},
                    "object_id": {"type": "string", "description": "Object ID to delete (shape, image, or slide)"},
                },
                "required": ["account", "presentation_id", "object_id"],
            },
        ),
        types.Tool(
            name="slides_duplicate_object",
            description="Duplicate a shape, image, or slide. Returns the new object ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "presentation_id": {"type": "string", "description": "Presentation ID"},
                    "object_id": {"type": "string", "description": "Object ID to duplicate"},
                },
                "required": ["account", "presentation_id", "object_id"],
            },
        ),
        types.Tool(
            name="slides_format_text",
            description=(
                "Format text inside a shape/text box. Omit start_index/end_index to format all text. "
                "color is hex like '#1155CC'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "presentation_id": {"type": "string", "description": "Presentation ID"},
                    "object_id": {"type": "string", "description": "Shape/text box object ID"},
                    "start_index": {"type": "integer", "description": "Start character index (optional)"},
                    "end_index": {"type": "integer", "description": "End character index (optional)"},
                    "bold": {"type": "boolean", "description": "Bold"},
                    "italic": {"type": "boolean", "description": "Italic"},
                    "underline": {"type": "boolean", "description": "Underline"},
                    "font_size": {"type": "integer", "description": "Font size in points"},
                    "font_family": {"type": "string", "description": "Font family, e.g. 'Arial'"},
                    "color": {"type": "string", "description": "Text color hex, e.g. '#1155CC'"},
                },
                "required": ["account", "presentation_id", "object_id"],
            },
        ),
        types.Tool(
            name="slides_set_speaker_notes",
            description="Set (replace) the speaker notes for a slide.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "presentation_id": {"type": "string", "description": "Presentation ID"},
                    "slide_object_id": {"type": "string", "description": "Slide (page) object ID"},
                    "text": {"type": "string", "description": "Speaker notes text"},
                },
                "required": ["account", "presentation_id", "slide_object_id", "text"],
            },
        ),
        types.Tool(
            name="slides_batch_update",
            description=(
                "Advanced: run a raw Google Slides API batchUpdate. `requests` is a list of Slides API "
                "Request objects (createTable, createShape, updatePageProperties, etc.)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account name"},
                    "presentation_id": {"type": "string", "description": "Presentation ID"},
                    "requests": {"type": "array", "items": {"type": "object"}, "description": "List of Slides API Request objects"},
                },
                "required": ["account", "presentation_id", "requests"],
            },
        ),
    ])


@server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    args = arguments or {}

    try:
        # ---- list_accounts ------------------------------------------------
        if name == "list_accounts":
            verify: bool = bool(args.get("verify", False))
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
            if verify:
                await _verify_identities(result)
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
                data = svc.search_messages(
                    query, max_results, include_body=include_body,
                    page_token=args.get("page_token"),
                )
                data["account"] = account
                data["email"] = _accounts[account].get("email", "")
                return _fmt(data)
            else:
                return _fmt(await _fan_out(
                    lambda acct: _get_service(acct).search_messages(
                        query, max_results, include_body=include_body
                    ),
                    empty_key="messages",
                ))

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
                html_body=args.get("html_body", ""),
                attachments=args.get("attachments"),
                thread_id=args.get("thread_id"),
                from_alias=args.get("from_alias", ""),
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
                html_body=args.get("html_body", ""),
                attachments=args.get("attachments"),
                thread_id=args.get("thread_id"),
                from_alias=args.get("from_alias", ""),
            )
            return _fmt({"status": "draft created", "draft_id": result.get("id")})

        # ---- gmail_reply --------------------------------------------------
        elif name == "gmail_reply":
            svc = _get_service(args["account"])
            return _fmt(svc.reply_message(
                message_id=args["message_id"],
                body=args["body"],
                reply_all=bool(args.get("reply_all", False)),
                html_body=args.get("html_body", ""),
                attachments=args.get("attachments"),
                from_alias=args.get("from_alias", ""),
            ))

        # ---- gmail_forward ------------------------------------------------
        elif name == "gmail_forward":
            svc = _get_service(args["account"])
            return _fmt(svc.forward_message(
                message_id=args["message_id"],
                to=args["to"],
                body=args.get("body", ""),
                cc=args.get("cc", ""),
                bcc=args.get("bcc", ""),
                from_alias=args.get("from_alias", ""),
            ))

        # ---- gmail_create_label -------------------------------------------
        elif name == "gmail_create_label":
            svc = _get_service(args["account"])
            return _fmt(svc.create_label(
                name=args["name"],
                label_list_visibility=args.get("label_list_visibility", "labelShow"),
                message_list_visibility=args.get("message_list_visibility", "show"),
            ))

        # ---- gmail_update_label -------------------------------------------
        elif name == "gmail_update_label":
            svc = _get_service(args["account"])
            return _fmt(svc.update_label(
                label_id=args["label_id"],
                name=args.get("name"),
                label_list_visibility=args.get("label_list_visibility"),
                message_list_visibility=args.get("message_list_visibility"),
            ))

        # ---- gmail_delete_label -------------------------------------------
        elif name == "gmail_delete_label":
            svc = _get_service(args["account"])
            return _fmt(svc.delete_label(args["label_id"]))

        # ---- gmail_batch_modify -------------------------------------------
        elif name == "gmail_batch_modify":
            svc = _get_service(args["account"])
            return _fmt(svc.batch_modify(
                message_ids=args["message_ids"],
                add_labels=args.get("add_labels"),
                remove_labels=args.get("remove_labels"),
            ))

        # ---- gmail_modify_thread_labels -----------------------------------
        elif name == "gmail_modify_thread_labels":
            svc = _get_service(args["account"])
            return _fmt(svc.modify_thread_labels(
                thread_id=args["thread_id"],
                add_labels=args.get("add_labels"),
                remove_labels=args.get("remove_labels"),
            ))

        # ---- gmail_mark_read ----------------------------------------------
        elif name == "gmail_mark_read":
            svc = _get_service(args["account"])
            return _fmt(svc.mark_read(args["message_id"]))

        # ---- gmail_mark_unread --------------------------------------------
        elif name == "gmail_mark_unread":
            svc = _get_service(args["account"])
            return _fmt(svc.mark_unread(args["message_id"]))

        # ---- gmail_untrash ------------------------------------------------
        elif name == "gmail_untrash":
            svc = _get_service(args["account"])
            svc.untrash_message(args["message_id"])
            return _fmt({"status": "restored from trash", "message_id": args["message_id"]})

        # ---- gmail_list_send_as -------------------------------------------
        elif name == "gmail_list_send_as":
            svc = _get_service(args["account"])
            return _fmt(svc.list_send_as())

        # ---- gmail_list_filters -------------------------------------------
        elif name == "gmail_list_filters":
            svc = _get_service(args["account"])
            return _fmt(svc.list_filters())

        # ---- gmail_create_filter ------------------------------------------
        elif name == "gmail_create_filter":
            svc = _get_service(args["account"])
            return _fmt(svc.create_filter(
                criteria=args["criteria"],
                action=args["action"],
            ))

        # ---- gmail_delete_filter ------------------------------------------
        elif name == "gmail_delete_filter":
            svc = _get_service(args["account"])
            return _fmt(svc.delete_filter(args["filter_id"]))

        # ---- gmail_get_vacation -------------------------------------------
        elif name == "gmail_get_vacation":
            svc = _get_service(args["account"])
            return _fmt(svc.get_vacation())

        # ---- gmail_set_vacation -------------------------------------------
        elif name == "gmail_set_vacation":
            svc = _get_service(args["account"])
            return _fmt(svc.set_vacation(
                enabled=bool(args["enabled"]),
                subject=args.get("subject", ""),
                body=args.get("body", ""),
                html_body=args.get("html_body", ""),
                restrict_to_contacts=bool(args.get("restrict_to_contacts", False)),
                restrict_to_domain=bool(args.get("restrict_to_domain", False)),
                start_time=args.get("start_time"),
                end_time=args.get("end_time"),
            ))

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
            return _fmt(svc.download_attachment(
                args["message_id"], args["attachment_id"], save_path=args.get("save_path")
            ))

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
                page_token=args.get("page_token"),
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
                page_token=args.get("page_token"),
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
                recurrence=args.get("recurrence"),
                reminders=args.get("reminders"),
                visibility=args.get("visibility"),
                color_id=args.get("color_id"),
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
                recurrence=args.get("recurrence"),
                reminders=args.get("reminders"),
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

        # ---- calendar_suggest_slots ---------------------------------------
        elif name == "calendar_suggest_slots":
            svc = _get_calendar(args["account"])
            return _fmt(svc.suggest_free_slots(
                emails=args["emails"],
                time_min=args["time_min"],
                time_max=args["time_max"],
                duration_minutes=int(args.get("duration_minutes", 30)),
                day_start_hour=int(args.get("day_start_hour", 9)),
                day_end_hour=int(args.get("day_end_hour", 18)),
                max_slots=int(args.get("max_slots", 10)),
            ))

        # ---- calendar_quick_add -------------------------------------------
        elif name == "calendar_quick_add":
            svc = _get_calendar(args["account"])
            return _fmt(svc.quick_add(
                text=args["text"],
                calendar_id=args.get("calendar_id", "primary"),
            ))

        # ---- calendar_move_event ------------------------------------------
        elif name == "calendar_move_event":
            svc = _get_calendar(args["account"])
            return _fmt(svc.move_event(
                event_id=args["event_id"],
                destination_calendar_id=args["destination_calendar_id"],
                source_calendar_id=args.get("source_calendar_id", "primary"),
            ))

        # ---- calendar_list_instances --------------------------------------
        elif name == "calendar_list_instances":
            svc = _get_calendar(args["account"])
            return _fmt(svc.list_instances(
                event_id=args["event_id"],
                calendar_id=args.get("calendar_id", "primary"),
                time_min=args.get("time_min"),
                time_max=args.get("time_max"),
                max_results=int(args.get("max_results", 25)),
            ))

        # ---- calendar_create_calendar -------------------------------------
        elif name == "calendar_create_calendar":
            svc = _get_calendar(args["account"])
            return _fmt(svc.create_calendar(
                summary=args["summary"],
                description=args.get("description", ""),
                time_zone=args.get("time_zone"),
            ))

        # ---- calendar_delete_calendar -------------------------------------
        elif name == "calendar_delete_calendar":
            svc = _get_calendar(args["account"])
            return _fmt(svc.delete_calendar(args["calendar_id"]))

        # ---- drive_search -------------------------------------------------
        elif name == "drive_search":
            query: str = args["query"]
            max_results: int = int(args.get("max_results", 20))
            account: str | None = args.get("account")

            if account:
                svc = _get_drive(account)
                data = svc.search_files(
                    query, max_results, page_token=args.get("page_token")
                )
                data["account"] = account
                data["email"] = _accounts[account].get("email", "")
                return _fmt(data)
            else:
                return _fmt(await _fan_out(
                    lambda acct: _get_drive(acct).search_files(query, max_results),
                    empty_key="files",
                ))

        # ---- drive_list_recent --------------------------------------------
        elif name == "drive_list_recent":
            svc = _get_drive(args["account"])
            return _fmt(svc.list_recent(
                int(args.get("max_results", 20)),
                page_token=args.get("page_token"),
            ))

        # ---- drive_get_file -----------------------------------------------
        elif name == "drive_get_file":
            svc = _get_drive(args["account"])
            return _fmt(svc.get_file(args["file_id"]))

        # ---- drive_read_content -------------------------------------------
        elif name == "drive_read_content":
            svc = _get_drive(args["account"])
            return _fmt(svc.read_content(
                args["file_id"],
                save_path=args.get("save_path"),
                export_mime=args.get("export_mime"),
            ))

        # ---- drive_upload -------------------------------------------------
        elif name == "drive_upload":
            svc = _get_drive(args["account"])
            result = svc.upload_file(
                name=args["name"],
                content=args.get("content", ""),
                mime_type=args.get("mime_type", "text/plain"),
                parent_folder_id=args.get("parent_folder_id"),
                source_path=args.get("source_path"),
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

        # ---- drive_copy ---------------------------------------------------
        elif name == "drive_copy":
            svc = _get_drive(args["account"])
            result = svc.copy_file(
                file_id=args["file_id"],
                name=args.get("name"),
                parent_folder_id=args.get("parent_folder_id"),
            )
            return _fmt({"status": "copied", **result})

        # ---- drive_share --------------------------------------------------
        elif name == "drive_share":
            svc = _get_drive(args["account"])
            return _fmt(svc.share_file(
                file_id=args["file_id"],
                role=args.get("role", "reader"),
                type=args.get("type", "user"),
                email=args.get("email"),
                domain=args.get("domain"),
                notify=bool(args.get("notify", True)),
                message=args.get("message"),
            ))

        # ---- drive_list_permissions ---------------------------------------
        elif name == "drive_list_permissions":
            svc = _get_drive(args["account"])
            return _fmt(svc.list_permissions(args["file_id"]))

        # ---- drive_remove_permission --------------------------------------
        elif name == "drive_remove_permission":
            svc = _get_drive(args["account"])
            return _fmt(svc.remove_permission(args["file_id"], args["permission_id"]))

        # ---- drive_export -------------------------------------------------
        elif name == "drive_export":
            svc = _get_drive(args["account"])
            return _fmt(svc.export_file(
                file_id=args["file_id"],
                mime_type=args["mime_type"],
                save_path=args.get("save_path"),
            ))

        # ---- drive_untrash ------------------------------------------------
        elif name == "drive_untrash":
            svc = _get_drive(args["account"])
            result = svc.untrash_file(args["file_id"])
            return _fmt({"status": "restored", **result})

        # ---- people_list_contacts -----------------------------------------
        elif name == "people_list_contacts":
            svc = _get_people(args["account"])
            return _fmt(svc.list_contacts(
                int(args.get("max_results", 50)),
                page_token=args.get("page_token"),
            ))

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
            emails = list(args.get("emails") or [])
            if args.get("email"):
                emails.insert(0, args["email"])
            phones = list(args.get("phones") or [])
            if args.get("phone"):
                phones.insert(0, args["phone"])
            result = svc.create_contact(
                given_name=args["given_name"],
                family_name=args.get("family_name", ""),
                middle_name=args.get("middle_name", ""),
                emails=emails or None,
                phones=phones or None,
                organization=args.get("organization", ""),
                title=args.get("title", ""),
                notes=args.get("notes", ""),
                birthday=args.get("birthday"),
                urls=args.get("urls"),
            )
            return _fmt({"status": "created", **result})

        # ---- people_update_contact ----------------------------------------
        elif name == "people_update_contact":
            svc = _get_people(args["account"])
            emails = args.get("emails")
            if emails is None and args.get("email") is not None:
                emails = [args["email"]]
            phones = args.get("phones")
            if phones is None and args.get("phone") is not None:
                phones = [args["phone"]]
            result = svc.update_contact(
                resource_name=args["resource_name"],
                given_name=args.get("given_name"),
                family_name=args.get("family_name"),
                middle_name=args.get("middle_name"),
                emails=emails,
                phones=phones,
                organization=args.get("organization"),
                title=args.get("title"),
                notes=args.get("notes"),
                birthday=args.get("birthday"),
                urls=args.get("urls"),
            )
            return _fmt({"status": "updated", **result})

        # ---- people_delete_contact ----------------------------------------
        elif name == "people_delete_contact":
            svc = _get_people(args["account"])
            return _fmt(svc.delete_contact(args["resource_name"]))

        # ---- people_list_other_contacts -----------------------------------
        elif name == "people_list_other_contacts":
            svc = _get_people(args["account"])
            return _fmt(svc.list_other_contacts(
                int(args.get("max_results", 50)),
                page_token=args.get("page_token"),
            ))

        # ---- people_list_groups -------------------------------------------
        elif name == "people_list_groups":
            svc = _get_people(args["account"])
            return _fmt(svc.list_contact_groups(int(args.get("max_results", 50))))

        # ---- people_create_group ------------------------------------------
        elif name == "people_create_group":
            svc = _get_people(args["account"])
            return _fmt(svc.create_contact_group(args["name"]))

        # ---- people_add_to_group ------------------------------------------
        elif name == "people_add_to_group":
            svc = _get_people(args["account"])
            return _fmt(svc.add_to_group(
                group_resource_name=args["group_resource_name"],
                contact_resource_names=args["contact_resource_names"],
            ))

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
                tab_id=args.get("tab_id"),
            ))

        # ---- docs_replace -------------------------------------------------
        elif name == "docs_replace":
            svc = _get_docs(args["account"])
            return _fmt(svc.replace_text(
                document_id=args["document_id"],
                find=args["find"],
                replace=args["replace"],
                match_case=bool(args.get("match_case", True)),
                tab_ids=args.get("tab_ids"),
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
                tab_id=args.get("tab_id"),
            ))

        # ---- docs_insert_table --------------------------------------------
        elif name == "docs_insert_table":
            svc = _get_docs(args["account"])
            return _fmt(svc.insert_table(
                document_id=args["document_id"],
                rows=int(args["rows"]),
                columns=int(args["columns"]),
                index=int(args.get("index", 1)),
                tab_id=args.get("tab_id"),
            ))

        # ---- docs_insert_image --------------------------------------------
        elif name == "docs_insert_image":
            svc = _get_docs(args["account"])
            return _fmt(svc.insert_image(
                document_id=args["document_id"],
                image_url=args["image_url"],
                index=int(args.get("index", 1)),
                width_pt=args.get("width_pt"),
                height_pt=args.get("height_pt"),
                tab_id=args.get("tab_id"),
            ))

        # ---- docs_insert_page_break ---------------------------------------
        elif name == "docs_insert_page_break":
            svc = _get_docs(args["account"])
            return _fmt(svc.insert_page_break(
                document_id=args["document_id"],
                index=int(args.get("index", 1)),
                tab_id=args.get("tab_id"),
            ))

        # ---- docs_create_bullets ------------------------------------------
        elif name == "docs_create_bullets":
            svc = _get_docs(args["account"])
            return _fmt(svc.create_bullets(
                document_id=args["document_id"],
                start_index=int(args["start_index"]),
                end_index=int(args["end_index"]),
                ordered=bool(args.get("ordered", False)),
                tab_id=args.get("tab_id"),
            ))

        # ---- docs_batch_update --------------------------------------------
        elif name == "docs_batch_update":
            svc = _get_docs(args["account"])
            return _fmt(svc.batch_update(
                document_id=args["document_id"],
                requests=args["requests"],
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

        # ---- sheets_format_cells ------------------------------------------
        elif name == "sheets_format_cells":
            svc = _get_sheets(args["account"])
            return _fmt(svc.format_cells(
                spreadsheet_id=args["spreadsheet_id"],
                sheet_id=int(args["sheet_id"]),
                start_row=int(args["start_row"]),
                end_row=int(args["end_row"]),
                start_col=int(args["start_col"]),
                end_col=int(args["end_col"]),
                bold=args.get("bold"),
                italic=args.get("italic"),
                font_size=int(args["font_size"]) if args.get("font_size") is not None else None,
                background_color=args.get("background_color"),
                text_color=args.get("text_color"),
                number_format=args.get("number_format"),
                horizontal_alignment=args.get("horizontal_alignment"),
            ))

        # ---- sheets_clear_range -------------------------------------------
        elif name == "sheets_clear_range":
            svc = _get_sheets(args["account"])
            return _fmt(svc.clear_range(
                spreadsheet_id=args["spreadsheet_id"],
                range=args["range"],
            ))

        # ---- sheets_delete_sheet ------------------------------------------
        elif name == "sheets_delete_sheet":
            svc = _get_sheets(args["account"])
            return _fmt(svc.delete_sheet(
                spreadsheet_id=args["spreadsheet_id"],
                sheet_id=int(args["sheet_id"]),
            ))

        # ---- sheets_rename_sheet ------------------------------------------
        elif name == "sheets_rename_sheet":
            svc = _get_sheets(args["account"])
            return _fmt(svc.rename_sheet(
                spreadsheet_id=args["spreadsheet_id"],
                sheet_id=int(args["sheet_id"]),
                title=args["title"],
            ))

        # ---- sheets_duplicate_sheet ---------------------------------------
        elif name == "sheets_duplicate_sheet":
            svc = _get_sheets(args["account"])
            return _fmt(svc.duplicate_sheet(
                spreadsheet_id=args["spreadsheet_id"],
                sheet_id=int(args["sheet_id"]),
                new_title=args.get("new_title"),
            ))

        # ---- sheets_batch_get ---------------------------------------------
        elif name == "sheets_batch_get":
            svc = _get_sheets(args["account"])
            return _fmt(svc.batch_get(
                spreadsheet_id=args["spreadsheet_id"],
                ranges=args["ranges"],
                value_render=args.get("value_render", "FORMATTED_VALUE"),
            ))

        # ---- sheets_freeze ------------------------------------------------
        elif name == "sheets_freeze":
            svc = _get_sheets(args["account"])
            return _fmt(svc.freeze(
                spreadsheet_id=args["spreadsheet_id"],
                sheet_id=int(args["sheet_id"]),
                rows=int(args.get("rows", 0)),
                cols=int(args.get("cols", 0)),
            ))

        # ---- sheets_merge_cells -------------------------------------------
        elif name == "sheets_merge_cells":
            svc = _get_sheets(args["account"])
            return _fmt(svc.merge_cells(
                spreadsheet_id=args["spreadsheet_id"],
                sheet_id=int(args["sheet_id"]),
                start_row=int(args["start_row"]),
                end_row=int(args["end_row"]),
                start_col=int(args["start_col"]),
                end_col=int(args["end_col"]),
                merge_type=args.get("merge_type", "MERGE_ALL"),
            ))

        # ---- sheets_batch_update ------------------------------------------
        elif name == "sheets_batch_update":
            svc = _get_sheets(args["account"])
            return _fmt(svc.batch_update(
                spreadsheet_id=args["spreadsheet_id"],
                requests=args["requests"],
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

        # ---- slides_create_textbox ----------------------------------------
        elif name == "slides_create_textbox":
            svc = _get_slides(args["account"])
            return _fmt(svc.create_textbox(
                presentation_id=args["presentation_id"],
                slide_object_id=args["slide_object_id"],
                text=args.get("text", ""),
                x=float(args.get("x", 100)),
                y=float(args.get("y", 100)),
                width=float(args.get("width", 300)),
                height=float(args.get("height", 100)),
            ))

        # ---- slides_create_image ------------------------------------------
        elif name == "slides_create_image":
            svc = _get_slides(args["account"])
            return _fmt(svc.create_image(
                presentation_id=args["presentation_id"],
                slide_object_id=args["slide_object_id"],
                image_url=args["image_url"],
                x=float(args.get("x", 100)),
                y=float(args.get("y", 100)),
                width=float(args.get("width", 300)),
                height=float(args.get("height", 200)),
            ))

        # ---- slides_delete_object -----------------------------------------
        elif name == "slides_delete_object":
            svc = _get_slides(args["account"])
            return _fmt(svc.delete_object(
                presentation_id=args["presentation_id"],
                object_id=args["object_id"],
            ))

        # ---- slides_duplicate_object --------------------------------------
        elif name == "slides_duplicate_object":
            svc = _get_slides(args["account"])
            return _fmt(svc.duplicate_object(
                presentation_id=args["presentation_id"],
                object_id=args["object_id"],
            ))

        # ---- slides_format_text -------------------------------------------
        elif name == "slides_format_text":
            svc = _get_slides(args["account"])
            return _fmt(svc.format_text(
                presentation_id=args["presentation_id"],
                object_id=args["object_id"],
                start_index=int(args["start_index"]) if args.get("start_index") is not None else None,
                end_index=int(args["end_index"]) if args.get("end_index") is not None else None,
                bold=args.get("bold"),
                italic=args.get("italic"),
                underline=args.get("underline"),
                font_size=int(args["font_size"]) if args.get("font_size") is not None else None,
                font_family=args.get("font_family"),
                color=args.get("color"),
            ))

        # ---- slides_set_speaker_notes -------------------------------------
        elif name == "slides_set_speaker_notes":
            svc = _get_slides(args["account"])
            return _fmt(svc.set_speaker_notes(
                presentation_id=args["presentation_id"],
                slide_object_id=args["slide_object_id"],
                text=args["text"],
            ))

        # ---- slides_batch_update ------------------------------------------
        elif name == "slides_batch_update":
            svc = _get_slides(args["account"])
            return _fmt(svc.batch_update(
                presentation_id=args["presentation_id"],
                requests=args["requests"],
            ))

        else:
            return _fmt(f"Unknown tool: {name}")

    except ValueError as exc:
        return _fmt(f"Error: {exc}")
    except Exception as exc:
        return _fmt(f"Error in '{name}': {_describe(exc)}")


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
