# Google Workspace Multi-Account MCP Server

A local [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that connects multiple Google Workspace accounts — **Gmail, Calendar, and Drive** — to Claude Desktop and Claude Code. Runs entirely on your machine — no cloud hosting required.

> Forked from [DiegoMaldonadoRosas/gmail-mcp](https://github.com/DiegoMaldonadoRosas/gmail-mcp) with Google Drive support added.

## Features

- **Multiple accounts** — connect as many Gmail or Google Workspace accounts as you need
- **Unified email search** — search across all accounts simultaneously with Gmail's full query syntax
- **Full read access** — read individual messages and entire threads
- **Send & draft** — compose and send emails, or save drafts, from any account
- **Label management** — list labels, mark as read/unread, star messages
- **Google Calendar** — list calendars, browse upcoming events, search by keyword
- **Google Drive** — search, read, upload, update, organize, and trash files across all accounts

## Requirements

- macOS (tested on macOS 14+)
- Python 3.11+
- A Google Cloud project with the **Gmail API**, **Google Calendar API**, and **Google Drive API** enabled (free)
- Claude Desktop or Claude Code

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/paulgenbergco/google-workspace-mcp.git
cd google-workspace-mcp
```

### 2. Run the setup script

```bash
bash setup.sh
```

This creates a virtual environment and installs all Python dependencies.

### 3. Configure your accounts

Copy the example config and fill in your accounts:

```bash
cp config.json.example config.json
```

Edit `config.json`:

```json
{
  "accounts": {
    "personal": {
      "email": "you@gmail.com",
      "description": "Personal Gmail"
    },
    "work": {
      "email": "you@company.com",
      "description": "Work account"
    }
  },
  "credentials_dir": "./credentials"
}
```

The account keys (`personal`, `work`) are the names you'll use when asking Claude to interact with a specific account.

### 4. Get Google OAuth credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable the **Gmail API**, **Google Calendar API**, and **Google Drive API**
3. Go to **APIs & Services > Credentials > + Create Credentials > OAuth 2.0 Client ID**
4. Choose **Desktop app** as the application type
5. Download the JSON file and save it as `credentials/client_secret.json`
6. Go to **APIs & Services > OAuth consent screen > Test users** and add every email address you configured in `config.json`

### 5. Authenticate your accounts

```bash
source .venv/bin/activate
python setup_auth.py
```

A browser window will open for each account. Sign in with the correct Google account. Tokens are saved locally and refreshed automatically — you only need to do this once per account.

> **Note:** If you previously authenticated for Gmail/Calendar only, you must re-run `setup_auth.py` after upgrading so the tokens include the new Drive permissions.

### 6. Add the server to Claude

**Claude Code** (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "google-workspace": {
      "command": "/absolute/path/to/google-workspace-mcp/.venv/bin/python",
      "args": ["/absolute/path/to/google-workspace-mcp/server.py"]
    }
  }
}
```

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "google-workspace": {
      "command": "/absolute/path/to/google-workspace-mcp/.venv/bin/python",
      "args": ["/absolute/path/to/google-workspace-mcp/server.py"]
    }
  }
}
```

Replace `/absolute/path/to/google-workspace-mcp` with the actual path where you cloned the repo.

### 7. Restart Claude

All tools will appear automatically.

## Available Tools

### Gmail

| Tool | Description |
|------|-------------|
| `list_accounts` | List all configured accounts and their auth status |
| `gmail_get_profile` | Get account profile and mailbox stats |
| `gmail_search` | Search emails using Gmail query syntax (one or all accounts) |
| `gmail_read_message` | Read the full content of a message |
| `gmail_read_thread` | Read all messages in a thread |
| `gmail_send` | Send an email from a specific account |
| `gmail_create_draft` | Save an email as a draft |
| `gmail_list_drafts` | List drafts in an account |
| `gmail_list_labels` | List all labels and folders |
| `gmail_modify_labels` | Add or remove labels (mark read/unread, star, etc.) |
| `gmail_trash` | Move a message to trash |

### Google Calendar

| Tool | Description |
|------|-------------|
| `calendar_list_calendars` | List all calendars for an account (primary, work, shared, etc.) |
| `calendar_list_events` | List upcoming events, optionally filtered by date range |
| `calendar_search` | Search events by keyword (title, description, location, attendees) |
| `calendar_get_event` | Get full details of a specific event |

### Google Drive

| Tool | Description |
|------|-------------|
| `drive_search` | Search files using Drive query syntax (one or all accounts) |
| `drive_list_recent` | List recently modified files |
| `drive_get_file` | Get detailed metadata for a specific file |
| `drive_read_content` | Read file content (exports Docs/Sheets/Slides to text) |
| `drive_upload` | Upload a new file with text content |
| `drive_update` | Update an existing file's content |
| `drive_create_folder` | Create a new folder |
| `drive_move` | Move a file or folder to a different folder |
| `drive_rename` | Rename a file or folder |
| `drive_trash` | Move a file or folder to trash |

## Usage Examples

Once connected, you can ask Claude things like:

**Email:**
- *"Do I have any unread emails in my work account?"*
- *"Search for invoices received in the last month across all my accounts"*
- *"Read the last email from John in my personal account"*
- *"Draft a reply to the budget email in my work account"*
- *"Mark all emails from newsletter@example.com as read"*

**Calendar:**
- *"What meetings do I have this week in my work account?"*
- *"Search for events related to 'product launch' in my personal calendar"*
- *"List all my calendars in my work account"*
- *"What are the details of tomorrow's standup?"*

**Drive:**
- *"Search for files named 'quarterly report' across all my accounts"*
- *"Read the content of the budget spreadsheet in my work account"*
- *"Upload these meeting notes to my work Drive"*
- *"Create a new folder called 'Q2 Reports' in my work account"*
- *"What files were recently modified in my personal Drive?"*

## Adding a New Account

1. Add the account to `config.json`
2. Add the email as a Test User in Google Cloud Console (OAuth consent screen)
3. Run `python setup_auth.py` — it will only prompt for the new account
4. Restart Claude

## Security

- OAuth tokens are stored locally in `credentials/tokens/` and are excluded from version control via `.gitignore`
- `config.json` (which contains your email addresses) is also excluded from version control
- Nothing is sent to any third-party server — all communication is directly between your Mac and Google's APIs
- To revoke access at any time, visit [myaccount.google.com/permissions](https://myaccount.google.com/permissions)

## Project Structure

```
google-workspace-mcp/
├── server.py           # MCP server — exposes 25 tools to Claude
├── auth.py             # OAuth2 token manager (per account)
├── gmail.py            # Gmail API wrapper
├── gcalendar.py        # Google Calendar API wrapper
├── gdrive.py           # Google Drive API wrapper
├── config.py           # Configuration loader
├── setup_auth.py       # One-time authentication script
├── setup.sh            # First-time installer
├── requirements.txt    # Python dependencies
├── config.json.example # Account configuration template
└── .gitignore          # Excludes credentials and config.json
```

## License

MIT
