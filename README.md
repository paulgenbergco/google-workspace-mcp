# Gmail Multi-Account MCP Server

A local [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that connects multiple Gmail accounts to Claude Desktop. Runs entirely on your machine — no cloud hosting required.

## Features

- **Multiple accounts** — connect as many Gmail or Google Workspace accounts as you need
- **Unified search** — search across all accounts simultaneously with Gmail's full query syntax
- **Full read access** — read individual messages and entire threads
- **Send & draft** — compose and send emails, or save drafts, from any account
- **Label management** — list labels, mark as read/unread, star messages
- **Trash** — move messages to trash from Claude

## Requirements

- macOS (tested on macOS 14+)
- Python 3.11+
- A Google Cloud project with the Gmail API enabled (free)
- Claude Desktop

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/DiegoMaldonadoRosas/gmail-mcp.git
cd gmail-mcp
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
2. Create a project and enable the **Gmail API**
3. Go to **APIs & Services → Credentials → + Create Credentials → OAuth 2.0 Client ID**
4. Choose **Desktop app** as the application type
5. Download the JSON file and save it as `credentials/client_secret.json`
6. Go to **APIs & Services → OAuth consent screen → Test users** and add every email address you configured in `config.json`

### 5. Authenticate your accounts

```bash
source .venv/bin/activate
python setup_auth.py
```

A browser window will open for each account. Sign in with the correct Google account. Tokens are saved locally and refreshed automatically — you only need to do this once per account.

### 6. Add the server to Claude Desktop

Open `~/Library/Application Support/Claude/claude_desktop_config.json` and add:

```json
{
  "mcpServers": {
    "gmail": {
      "command": "/absolute/path/to/gmail-mcp/.venv/bin/python",
      "args": ["/absolute/path/to/gmail-mcp/server.py"]
    }
  }
}
```

Replace `/absolute/path/to/gmail-mcp` with the actual path where you cloned the repo.

### 7. Restart Claude Desktop

The Gmail tools will appear automatically.

## Available Tools

| Tool | Description |
|------|-------------|
| `list_accounts` | List all configured accounts and their auth status |
| `gmail_search` | Search emails using Gmail query syntax (one or all accounts) |
| `gmail_read_message` | Read the full content of a message |
| `gmail_read_thread` | Read all messages in a thread |
| `gmail_send` | Send an email from a specific account |
| `gmail_create_draft` | Save an email as a draft |
| `gmail_list_drafts` | List drafts in an account |
| `gmail_list_labels` | List all labels and folders |
| `gmail_modify_labels` | Add or remove labels (mark read/unread, star, etc.) |
| `gmail_trash` | Move a message to trash |
| `gmail_get_profile` | Get account profile and mailbox stats |

## Usage Examples

Once connected, you can ask Claude things like:

- *"Do I have any unread emails in my work account?"*
- *"Search for invoices received in the last month across all my accounts"*
- *"Read the last email from John in my personal account"*
- *"Draft a reply to the budget email in my work account"*
- *"Mark all emails from newsletter@example.com as read"*

## Adding a New Account

1. Add the account to `config.json`
2. Add the email as a Test User in Google Cloud Console (OAuth consent screen)
3. Run `python setup_auth.py` — it will only prompt for the new account
4. Restart Claude Desktop

## Security

- OAuth tokens are stored locally in `credentials/tokens/` and are excluded from version control via `.gitignore`
- `config.json` (which contains your email addresses) is also excluded from version control
- Nothing is sent to any third-party server — all communication is directly between your Mac and Google's API
- To revoke access at any time, visit [myaccount.google.com/permissions](https://myaccount.google.com/permissions)

## Project Structure

```
gmail-mcp/
├── server.py           # MCP server — exposes 11 tools to Claude
├── auth.py             # OAuth2 token manager (per account)
├── gmail.py            # Gmail API wrapper
├── config.py           # Configuration loader
├── setup_auth.py       # One-time authentication script
├── setup.sh            # First-time installer
├── requirements.txt    # Python dependencies
├── config.json.example # Account configuration template
└── .gitignore          # Excludes credentials and config.json
```

## License

MIT
