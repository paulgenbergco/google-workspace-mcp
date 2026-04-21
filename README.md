# Google Workspace Multi-Account MCP Server

A local [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that connects multiple Google Workspace accounts — **Gmail, Calendar, Drive, Contacts, Docs, Sheets, and Slides** — to Claude Desktop and Claude Code. 57 tools, full read+write, runs entirely on your machine.

> Forked from [DiegoMaldonadoRosas/gmail-mcp](https://github.com/DiegoMaldonadoRosas/gmail-mcp) with Drive, Contacts, Docs, Sheets, and Slides support added.

## Features

- **Multiple accounts** — connect as many Gmail or Google Workspace accounts as you need
- **Gmail** — search (cross-account), read messages/threads, send, draft, labels, attachments, trash
- **Google Calendar** — list, search, create/update/delete events, RSVP, find free time
- **Google Drive** — search (cross-account), read/upload/update files, folders, move, rename, trash
- **Google Contacts** — list, search, create, update, delete contacts
- **Google Docs** — read text, create, insert/replace text, format (bold, italic, headings, links)
- **Google Sheets** — read data (CSV/JSON/raw), create, write/append ranges, manage tabs
- **Google Slides** — read text/metadata, create, add slides, find/replace and insert text

## Requirements

- macOS (tested on macOS 14+)
- Python 3.11+
- A Google Cloud project with **Gmail, Calendar, Drive, People, Docs, Sheets, and Slides APIs** enabled (free)
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

### 3. Configure your accounts

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

### 4. Get Google OAuth credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable: **Gmail API, Calendar API, Drive API, People API, Docs API, Sheets API, Slides API**
3. Go to **APIs & Services > Credentials > + Create Credentials > OAuth 2.0 Client ID**
4. Choose **Desktop app** as the application type
5. Download the JSON file and save it as `credentials/client_secret.json`
6. Go to **APIs & Services > OAuth consent screen > Test users** and add every email address you configured in `config.json`

### 5. Authenticate your accounts

```bash
source .venv/bin/activate
python setup_auth.py
```

> **Note:** If upgrading from a previous version, re-run `setup_auth.py` to grant newly added scopes (Calendar write, Contacts, Docs, Sheets, Slides).

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

### 7. Restart Claude

All 57 tools will appear automatically.

## Available Tools (57)

### Gmail (14 tools)

| Tool | Description |
|------|-------------|
| `list_accounts` | List all configured accounts and their auth status |
| `gmail_get_profile` | Get account profile and mailbox stats |
| `gmail_search` | Search emails using Gmail query syntax (one or all accounts) |
| `gmail_read_message` | Read the full content of a message |
| `gmail_read_thread` | Read all messages in a thread |
| `gmail_send` | Send an email from a specific account |
| `gmail_create_draft` | Save an email as a draft |
| `gmail_send_draft` | Send an existing draft |
| `gmail_list_drafts` | List drafts in an account |
| `gmail_list_labels` | List all labels and folders |
| `gmail_modify_labels` | Add or remove labels (mark read/unread, star, etc.) |
| `gmail_trash` | Move a message to trash |
| `gmail_list_attachments` | List all attachments on a message |
| `gmail_download_attachment` | Download attachment content |

### Google Calendar (9 tools)

| Tool | Description |
|------|-------------|
| `calendar_list_calendars` | List all calendars for an account |
| `calendar_list_events` | List upcoming events, optionally filtered by date range |
| `calendar_search` | Search events by keyword |
| `calendar_get_event` | Get full details of a specific event |
| `calendar_create_event` | Create a new event (with attendees, Meet link, all-day support) |
| `calendar_update_event` | Update fields on an existing event |
| `calendar_delete_event` | Delete an event |
| `calendar_respond` | Respond to an invitation (accept, decline, tentative) |
| `calendar_find_free_time` | Query free/busy for a list of people |

### Google Drive (10 tools)

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

### Google Contacts (6 tools)

| Tool | Description |
|------|-------------|
| `people_list_contacts` | List contacts, ordered by most recently modified |
| `people_search` | Search contacts by name, email, phone, etc. |
| `people_get_contact` | Get full details of a specific contact |
| `people_create_contact` | Create a new contact |
| `people_update_contact` | Update an existing contact |
| `people_delete_contact` | Delete a contact |

### Google Docs (5 tools)

| Tool | Description |
|------|-------------|
| `docs_get` | Read the full text content of a Google Doc |
| `docs_create` | Create a new Doc with optional initial text |
| `docs_write` | Insert text at a specific position |
| `docs_replace` | Find and replace text throughout a Doc |
| `docs_format` | Format text (bold, italic, underline, headings, links, font size) |

### Google Sheets (7 tools)

| Tool | Description |
|------|-------------|
| `sheets_get_metadata` | Get spreadsheet metadata (title, tabs, row/col counts) |
| `sheets_get_range` | Read a specific range (A1 notation) |
| `sheets_get_data` | Read entire sheet as CSV, JSON, or raw values |
| `sheets_create` | Create a new spreadsheet |
| `sheets_update_range` | Write values to a range |
| `sheets_append_rows` | Append rows to the end of a sheet |
| `sheets_add_sheet` | Add a new sheet/tab |

### Google Slides (6 tools)

| Tool | Description |
|------|-------------|
| `slides_get_text` | Read all text from a presentation by slide |
| `slides_get_metadata` | Get metadata (title, slide count, speaker notes) |
| `slides_create` | Create a new presentation |
| `slides_add_slide` | Add a slide (BLANK, TITLE, TITLE_AND_BODY, etc.) |
| `slides_replace_text` | Find and replace text across all slides |
| `slides_insert_text` | Insert text into a specific shape/text box |

## Usage Examples

**Email:** *"Search for invoices across all my accounts"* · *"Send a draft I wrote earlier"* · *"Download the attachment from that email"*

**Calendar:** *"Create a meeting with Alice tomorrow at 2pm with a Meet link"* · *"Accept the invite for Friday's standup"* · *"When is everyone free next week?"*

**Drive:** *"Upload these meeting notes to my work Drive"* · *"Read the budget spreadsheet"* · *"Create a Q2 Reports folder"*

**Contacts:** *"Find John's phone number"* · *"Add a new contact for the vendor"* · *"Update Sarah's email address"*

**Docs:** *"Read the project proposal doc"* · *"Create a new doc with these notes"* · *"Replace all instances of 'Q1' with 'Q2'"*

**Sheets:** *"Read the sales data as CSV"* · *"Append these rows to the tracker"* · *"Create a new spreadsheet with 'Revenue' and 'Expenses' tabs"*

**Slides:** *"Read all the text from the investor deck"* · *"Add a new blank slide"* · *"Replace '[Company]' with 'ALAi' in all slides"*

## Adding a New Account

1. Add the account to `config.json`
2. Add the email as a Test User in Google Cloud Console (OAuth consent screen)
3. Run `python setup_auth.py` — it will only prompt for the new account
4. Restart Claude

## Security

- OAuth tokens are stored locally in `credentials/tokens/` and are excluded from version control
- `config.json` is also excluded from version control
- Nothing is sent to any third-party server — all communication is directly between your Mac and Google's APIs
- To revoke access: [myaccount.google.com/permissions](https://myaccount.google.com/permissions)

## Project Structure

```
google-workspace-mcp/
├── server.py           # MCP server — 57 tools
├── auth.py             # OAuth2 token manager (per account)
├── gmail.py            # Gmail API wrapper
├── gcalendar.py        # Google Calendar API wrapper
├── gdrive.py           # Google Drive API wrapper
├── gpeople.py          # People/Contacts API wrapper
├── gdocs.py            # Google Docs API wrapper
├── gsheets.py          # Google Sheets API wrapper
├── gslides.py          # Google Slides API wrapper
├── config.py           # Configuration loader
├── setup_auth.py       # One-time authentication script
├── setup.sh            # First-time installer
├── requirements.txt    # Python dependencies
├── config.json.example # Account configuration template
└── .gitignore          # Excludes credentials and config.json
```

## License

MIT
