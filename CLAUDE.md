# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local stdio MCP server that exposes **110 tools** across Gmail, Calendar, Drive, Contacts, Docs, Sheets, and Slides for **multiple Google accounts at once**. It exists to work around Claude's built-in connectors being single-account: every tool takes an `account` argument naming a key in `config.json`, and each account has its own OAuth token file.

Forked from `DiegoMaldonadoRosas/gmail-mcp` (`upstream` remote); Drive, Contacts, Docs, Sheets, Slides were added here.

## Commands

```bash
bash setup.sh                      # first-time: venv + deps + credentials dirs + config.json
source .venv/bin/activate
python setup_auth.py               # OAuth browser flow per account; prompts 'Re-authenticate? [y/N]'
                                   # on ones that already have a token
pre-commit run --all-files         # whitespace/EOF/YAML/JSON/large-file/Python-AST checks
                                   # (not installed by setup.sh: pip install pre-commit first)
```

There is no test suite. Use these instead:

```bash
# Does the server import and declare all tools?
.venv/bin/python -c "import asyncio, server; print(len(asyncio.run(server.list_tools())))"

# Live sanity check without mutating anything (prints per-account auth status)
.venv/bin/python -c "import asyncio, server; print(asyncio.run(server.call_tool('list_accounts', {}))[0].text)"

# Declaration/dispatch parity — catches a tool declared in list_tools() with no
# matching branch in call_tool(), which otherwise fails only at call time
.venv/bin/python - <<'PY'
import asyncio, re, server
declared = {t.name for t in asyncio.run(server.list_tools())}
src = open("server.py").read().split("async def call_tool")[1]
dispatched = set(re.findall(r'name == "([a-z_]+)"', src))
print("missing dispatch:", sorted(declared - dispatched))
print("orphan dispatch:", sorted(dispatched - declared))
PY
```

Running `python server.py` directly just blocks on stdin waiting for MCP frames — it's only useful to confirm it doesn't crash at startup.

## Architecture

Three layers, and a change to any tool almost always touches all three:

0. **`gapi.py`** — shared `RETRIES` constant and `describe_http_error()`. Every `.execute()` in the wrappers passes `num_retries=RETRIES`, which is what makes googleapiclient back off on 429/5xx instead of failing the call.
1. **`auth.py`** — `AuthManager` holds the single `SCOPES` list for all seven APIs and reads/writes one token JSON per account in `credentials/tokens/<account>.json`. Expired tokens refresh silently and are re-saved; a failed refresh returns `None` rather than raising, which surfaces as "not authenticated" in `list_accounts`.
2. **`g*.py` service wrappers** — one class per Google API (`GmailService`, `CalendarService`, `DriveService`, `PeopleService`, `DocsService`, `SheetsService`, `SlidesService`). All share the same shape: `__init__(credentials, account_name)` calls `build(...)`, and every public method returns plain dicts/lists ready for JSON. No MCP types leak into this layer.
3. **`server.py`** (~3000 lines) — the entire MCP surface. `list_tools()` returns 110 hand-written `types.Tool` schemas wrapped in `_annotate()`; `call_tool()` is one long `if/elif` chain on tool name that unpacks `args`, builds a service via the `_get_*(account)` helpers, and wraps the result with `_fmt()`. Both halves are alphabetically grouped by app with `# ---- tool_name ----` comment banners.

### Adding or changing a tool

1. Add/modify the method on the relevant `g*.py` service class.
2. Add a `types.Tool(...)` entry in `list_tools()` in the matching app section.
3. Add the `elif name == "...":` branch in `call_tool()` in the same relative position.
4. Classify it in `_READ_ONLY_TOOLS` / `_DESTRUCTIVE_TOOLS` above `list_tools()`. Anything in neither set is annotated as an additive write, which is the right default but is a silent one — a destructive tool left unclassified will not prompt.

Miss step 2 or 3 and nothing errors at import — the parity check above is the fastest way to catch it. Numeric args come off the wire as strings or floats, so branches cast explicitly (`int(args["x"]) if args.get("x") is not None else None`); follow that pattern.

Errors are never raised out of `call_tool()`. `ValueError` (unknown account, unauthenticated account) returns `"Error: ..."`; anything else goes through `_describe()`, which renders a Google `HttpError` as `HTTP 400: invalidArgument: Invalid id value` rather than googleapiclient's URI-heavy default. Either way it comes back as ordinary text content, so a failing tool looks like a normal response to the client.

### Cross-account behavior

Only `gmail_search` and `drive_search` accept an omitted `account`. Both go through `_fan_out(call, empty_key)`, which runs one `asyncio.to_thread` per account and gathers them concurrently — about 3x faster than the serial loop it replaced across five accounts. Every failure is caught per account and reported inline as `{"account": ..., "error": ..., <empty_key>: []}`, so one unauthenticated or throttled account cannot sink the whole search. Every other tool requires `account`.

`page_token` is only wired into the single-account path of those two tools: page tokens are per-account and cannot be reused across a fan-out.

## Account model

`config.json` (gitignored) maps a short account key to an email and description. The key, not the email, is what tools take as `account`. Keys in use: `genberg`, `alai`, `lvlon`, `cloe` on the laptop, plus `banks` on the Clawdette deployment (a separate Mac mini running the banks daemon, which needs that account's access). Each machine's `config.json` carries only the accounts it uses, so a key absent from one machine is not retired. `credentials/` is gitignored in full, including `credentials/tokens_bak/` (manual backups kept before re-auth).

## Gotchas

- **Changing `SCOPES` in `auth.py` requires re-running `setup_auth.py` for every account.** Existing tokens keep working for old scopes and fail at call time on the new ones. When adding a scope, say so in the README's upgrade note.
- **Editing `server.py` or any wrapper needs a Claude restart**, not just a file save — the client spawns the stdio server once per session, so a running Claude holds the old code.
- **Binary payloads never come back as base64 by default.** `gmail_download_attachment` and `drive_read_content` write to `save_path` if given; otherwise text-ish MIME types decode to `content` and true binaries go to a temp file whose path is returned as `file_path`. Preserve that when touching either — the point is to keep base64 blobs out of the model's context.
- **Gmail label arguments accept names or IDs.** `GmailService._resolve_label_ids` maps names to IDs, passes system labels through, and auto-creates unknown names on *adds* only (removes silently no-op). Tool schemas should describe labels as names.
- **Docs tools are tab-aware.** `docs_get` walks nested `childTabs` and flattens them; write/format/replace take an optional `tab_id` threaded into the API `location`/`tabsCriteria`. A Docs change that ignores tabs will silently hit the first tab only.
- **Sending from an alias needs a verified send-as entry.** `from_alias` on `gmail_send` / `gmail_create_draft` / `gmail_reply` / `gmail_forward` sets the From header, but Gmail rejects any address that is not a verified send-as on that account. `gmail_list_send_as` reports which are usable. No extra scope is needed — `gmail.settings.basic` already covers it.
- **`list_accounts` reports the configured email, not the token's.** The `email` field comes straight out of `config.json` and is not evidence of who the stored token signs in as. Editing an account's email without re-running `setup_auth.py` leaves it reading `ready` while every call still runs as the previous account. Pass `verify: true` to check each authenticated token against Google (`getProfile`, one call per account, concurrent) and flag any that disagrees — use it after changing an email or re-authenticating.
- **The three `*_batch_update` tools are raw API passthroughs** (Docs/Sheets/Slides). Prefer adding a typed tool over telling callers to hand-write request JSON.
