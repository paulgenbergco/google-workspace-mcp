#!/usr/bin/env python3
"""
One-time authentication setup for all Google Workspace accounts in config.json.

Run this BEFORE starting the MCP server:
    python setup_auth.py

A browser window will open for each account so you can sign in with
the correct Google account. Tokens are saved locally and refreshed
automatically by the server — you only need to run this once per account.
"""

import sys
from pathlib import Path

from config import (
    get_accounts,
    get_client_secret_path,
    get_credentials_dir,
    load_config,
)
from auth import AuthManager


HELP_CLOUD_CONSOLE = """
How to get your client_secret.json
───────────────────────────────────
1. Go to https://console.cloud.google.com/
2. Create (or select) a project
3. Enable the Gmail API, Calendar API, and Drive API:
   APIs & Services → Library → search each API → Enable
4. Create OAuth 2.0 credentials:
   APIs & Services → Credentials → + Create Credentials → OAuth client ID
   Application type: Desktop app
5. Click "Download JSON" and save the file as:
   {path}
6. Re-run this script.
"""


def main() -> None:
    # ---- load config -------------------------------------------------------
    try:
        config = load_config()
    except FileNotFoundError as exc:
        print(f"Error: {exc}\n")
        print("Copy config.json.example to config.json and fill in your accounts.")
        sys.exit(1)

    accounts = get_accounts(config)
    credentials_dir = get_credentials_dir(config)
    client_secret_path = get_client_secret_path(config)

    if not accounts:
        print("No accounts found in config.json. Add at least one account and re-run.")
        sys.exit(1)

    # ---- check client_secret.json ------------------------------------------
    if not client_secret_path.exists():
        print(f"client_secret.json not found at:\n  {client_secret_path}")
        print(HELP_CLOUD_CONSOLE.format(path=client_secret_path))
        sys.exit(1)

    auth = AuthManager(credentials_dir, client_secret_path)

    print(f"Google Workspace MCP — Authentication Setup")
    print(f"{'─' * 50}")
    print(f"Found {len(accounts)} account(s) in config.json.\n")

    # ---- authenticate each account ----------------------------------------
    for account_name, info in accounts.items():
        email = info.get("email", account_name)
        description = info.get("description", "")

        print(f"Account : {account_name}")
        print(f"Email   : {email}")
        if description:
            print(f"Note    : {description}")

        if auth.is_authenticated(account_name):
            print("Status  : already authenticated")
            answer = input("Re-authenticate? [y/N] ").strip().lower()
            if answer != "y":
                print("Skipped.\n")
                continue

        print(f"\nOpening browser — please sign in as {email} ...")
        print("(If the wrong account is selected, use 'Switch account' in the browser.)\n")

        try:
            auth.authenticate(account_name, email=email)
            print(f"✓ '{account_name}' authenticated successfully.\n")
        except Exception as exc:
            print(f"✗ Failed to authenticate '{account_name}': {exc}\n")

    # ---- summary -----------------------------------------------------------
    print("─" * 50)
    print("Summary:")
    for account_name, info in accounts.items():
        email = info.get("email", account_name)
        status = "✓ ready" if auth.is_authenticated(account_name) else "✗ not authenticated"
        print(f"  {account_name:20s} ({email})  {status}")

    print()
    not_ready = [a for a in accounts if not auth.is_authenticated(a)]
    if not_ready:
        print(f"Re-run this script to authenticate the remaining accounts: {not_ready}")
    else:
        print("All accounts authenticated. Start the server with:  python server.py")


if __name__ == "__main__":
    main()
