# Google Workspace Multi-Account MCP Server

A local [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that connects multiple Google Workspace accounts — **Gmail, Calendar, Drive, Contacts, Docs, Sheets, and Slides** — to Claude Desktop and Claude Code. 109 tools, full read+write, runs entirely on your machine.

> Forked from [DiegoMaldonadoRosas/gmail-mcp](https://github.com/DiegoMaldonadoRosas/gmail-mcp) with Drive, Contacts, Docs, Sheets, and Slides support added.

## Features

- **Multiple accounts** — connect as many Gmail or Google Workspace accounts as you need
- **Gmail** — cross-account search, read, send (HTML + attachments), threaded reply/reply-all, forward, drafts, label CRUD, batch label ops, mark read/unread, trash/untrash, filters, vacation responder
- **Google Calendar** — list/search/create/update (patch) events with recurrence (RRULE), reminders, Meet links; RSVP, quick-add, move between calendars, list recurring instances, free/busy + suggested slots, create/delete calendars
- **Google Drive** — cross-account search, read (binary-safe), upload from text or local file, export (PDF/etc.), copy, share & manage permissions, folders, move, rename, trash/untrash
- **Google Contacts** — list, search, create/update with multiple emails/phones + notes/birthday/URLs, delete, "other contacts", contact groups
- **Google Docs** — tab-aware read/write, create, insert/replace/format text, **tables, inline images, bullet/numbered lists, page breaks**, raw batchUpdate
- **Google Sheets** — read (CSV/JSON/raw, batch multi-range), create, write/append, **cell formatting, number formats, freeze, merge**, clear, add/delete/rename/duplicate sheets, raw batchUpdate
- **Google Slides** — read text/metadata, create, add slides, **create text boxes & images, format text, speaker notes, delete/duplicate objects**, find/replace, raw batchUpdate

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

> **Note:** If upgrading from a previous version, re-run `setup_auth.py` for **every account** to grant the newly added scopes — `gmail.labels`, `gmail.settings.basic` (filters + vacation responder), and `contacts.other.readonly` ("other contacts"). Existing tools keep working without it, but these specific features will fail until each account is re-authenticated.

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

All 109 tools will appear automatically.

## Available Tools (109)

### Gmail (28 tools)

| Tool | Description |
|------|-------------|
| `list_accounts` | List all configured accounts and their auth status |
| `gmail_get_profile` | Get account profile and mailbox stats |
| `gmail_search` | Search emails using Gmail query syntax (one or all accounts) |
| `gmail_read_message` | Read the full content of a message |
| `gmail_read_thread` | Read all messages in a thread |
| `gmail_send` | Send an email (plain + HTML body, attachments, threadId) |
| `gmail_reply` | Reply / reply-all, preserving the thread |
| `gmail_forward` | Forward a message, quoting the original |
| `gmail_create_draft` | Save an email as a draft (HTML + attachments) |
| `gmail_send_draft` | Send an existing draft |
| `gmail_list_drafts` | List drafts in an account |
| `gmail_list_labels` | List all labels and folders |
| `gmail_create_label` | Create a new label |
| `gmail_update_label` | Rename or change visibility of a label |
| `gmail_delete_label` | Delete a label |
| `gmail_modify_labels` | Add or remove labels on a message |
| `gmail_batch_modify` | Add/remove labels on many messages at once |
| `gmail_modify_thread_labels` | Add/remove labels on a whole thread |
| `gmail_mark_read` | Mark a message as read |
| `gmail_mark_unread` | Mark a message as unread |
| `gmail_trash` | Move a message to trash |
| `gmail_untrash` | Restore a message from trash |
| `gmail_list_attachments` | List all attachments on a message |
| `gmail_download_attachment` | Download attachment content (binary-safe; save to file) |
| `gmail_list_filters` | List filters (rules) |
| `gmail_create_filter` | Create a filter |
| `gmail_delete_filter` | Delete a filter |
| `gmail_get_vacation` / `gmail_set_vacation` | Read / set the vacation responder |

### Google Calendar (15 tools)

| Tool | Description |
|------|-------------|
| `calendar_list_calendars` | List all calendars for an account |
| `calendar_list_events` | List upcoming events, optionally filtered by date range |
| `calendar_search` | Search events by keyword |
| `calendar_get_event` | Get full details of a specific event |
| `calendar_create_event` | Create an event (attendees, Meet, all-day, recurrence, reminders) |
| `calendar_update_event` | Patch fields on an event (incl. recurrence, reminders) |
| `calendar_delete_event` | Delete an event |
| `calendar_respond` | Respond to an invitation (accept, decline, tentative) |
| `calendar_quick_add` | Create an event from natural language |
| `calendar_move_event` | Move an event to another calendar |
| `calendar_list_instances` | List instances of a recurring event |
| `calendar_find_free_time` | Query free/busy for a list of people |
| `calendar_suggest_slots` | Suggest open meeting slots across attendees |
| `calendar_create_calendar` | Create a new secondary calendar |
| `calendar_delete_calendar` | Delete a secondary calendar |

### Google Drive (16 tools)

| Tool | Description |
|------|-------------|
| `drive_search` | Search files using Drive query syntax (one or all accounts) |
| `drive_list_recent` | List recently modified files |
| `drive_get_file` | Get detailed metadata for a specific file |
| `drive_read_content` | Read file content (exports Workspace files; binary-safe) |
| `drive_upload` | Upload a new file from text or a local file path |
| `drive_update` | Update an existing file's content |
| `drive_export` | Export a Workspace file (PDF, CSV, etc.) |
| `drive_copy` | Copy a file |
| `drive_share` | Share a file/folder (grant a permission) |
| `drive_list_permissions` | List who has access |
| `drive_remove_permission` | Revoke an access grant |
| `drive_create_folder` | Create a new folder |
| `drive_move` | Move a file or folder to a different folder |
| `drive_rename` | Rename a file or folder |
| `drive_trash` | Move a file or folder to trash |
| `drive_untrash` | Restore a file or folder from trash |

### Google Contacts (10 tools)

| Tool | Description |
|------|-------------|
| `people_list_contacts` | List contacts, ordered by most recently modified |
| `people_search` | Search contacts by name, email, phone, etc. |
| `people_get_contact` | Get full details of a specific contact |
| `people_create_contact` | Create a contact (multiple emails/phones, notes, birthday, URLs) |
| `people_update_contact` | Update a contact (lists replace) |
| `people_delete_contact` | Delete a contact |
| `people_list_other_contacts` | List auto-collected "Other contacts" |
| `people_list_groups` | List contact groups (labels) |
| `people_create_group` | Create a contact group |
| `people_add_to_group` | Add contacts to a group |

### Google Docs (10 tools)

| Tool | Description |
|------|-------------|
| `docs_get` | Read the full text of a Doc, **including all tabs** |
| `docs_create` | Create a new Doc with optional initial text |
| `docs_write` | Insert text at a position (optional target tab) |
| `docs_replace` | Find and replace text throughout a Doc |
| `docs_format` | Format text (bold, italic, underline, headings, links, font size) |
| `docs_insert_table` | Insert a table |
| `docs_insert_image` | Insert an inline image from a URL |
| `docs_insert_page_break` | Insert a page break |
| `docs_create_bullets` | Turn paragraphs into a bulleted/numbered list |
| `docs_batch_update` | Raw Docs API batchUpdate passthrough |

### Google Sheets (16 tools)

| Tool | Description |
|------|-------------|
| `sheets_get_metadata` | Get spreadsheet metadata (title, tabs, row/col counts) |
| `sheets_get_range` | Read a specific range (A1 notation) |
| `sheets_get_data` | Read entire sheet as CSV, JSON, or raw values |
| `sheets_batch_get` | Read several ranges at once |
| `sheets_create` | Create a new spreadsheet |
| `sheets_update_range` | Write values to a range |
| `sheets_append_rows` | Append rows to the end of a sheet |
| `sheets_clear_range` | Clear values in a range |
| `sheets_format_cells` | Format cells (bold, colors, number formats, alignment) |
| `sheets_merge_cells` | Merge a block of cells |
| `sheets_freeze` | Freeze header rows/columns |
| `sheets_add_sheet` | Add a new sheet/tab |
| `sheets_delete_sheet` | Delete a sheet/tab |
| `sheets_rename_sheet` | Rename a sheet/tab |
| `sheets_duplicate_sheet` | Duplicate a sheet/tab |
| `sheets_batch_update` | Raw Sheets API batchUpdate passthrough |

### Google Slides (13 tools)

| Tool | Description |
|------|-------------|
| `slides_get_text` | Read all text from a presentation by slide |
| `slides_get_metadata` | Get metadata (title, slide count, speaker notes) |
| `slides_create` | Create a new presentation |
| `slides_add_slide` | Add a slide (BLANK, TITLE, TITLE_AND_BODY, etc.) |
| `slides_replace_text` | Find and replace text across all slides |
| `slides_insert_text` | Insert text into a specific shape/text box |
| `slides_create_textbox` | Create a text box (and optionally fill it) |
| `slides_create_image` | Place an image from a URL onto a slide |
| `slides_format_text` | Format text in a shape (bold, size, font, color) |
| `slides_set_speaker_notes` | Set a slide's speaker notes |
| `slides_delete_object` | Delete a shape, image, or slide |
| `slides_duplicate_object` | Duplicate a shape, image, or slide |
| `slides_batch_update` | Raw Slides API batchUpdate passthrough |

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
├── server.py           # MCP server — 109 tools
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
