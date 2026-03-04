"""
Gmail Multi-Account MCP Server
-------------------------------
Exposes Gmail operations for multiple Google accounts via the
Model Context Protocol (MCP) stdio transport.

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
from gmail import GmailService

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


def _get_service(account_name: str) -> GmailService:
    """Return an authenticated GmailService or raise ValueError."""
    if account_name not in _accounts:
        available = list(_accounts.keys())
        raise ValueError(
            f"Unknown account '{account_name}'. Available: {available}"
        )
    creds = _auth.get_credentials(account_name)
    if creds is None:
        email = _accounts[account_name].get("email", account_name)
        raise ValueError(
            f"Account '{account_name}' ({email}) is not authenticated. "
            "Run 'python setup_auth.py' to authenticate."
        )
    return GmailService(creds, account_name)


def _fmt(data: Any) -> list[types.TextContent]:
    if isinstance(data, str):
        return [types.TextContent(type="text", text=data)]
    return [types.TextContent(type="text", text=json.dumps(data, indent=2, ensure_ascii=False))]


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

server = Server("gmail-multi-account")


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
