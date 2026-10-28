# Career OS

A local, evidence-backed work journal. It gathers traces of your work, connects the related ones, and drafts accomplishment statements that you review and approve. The app and its database run only on your laptop (loopback address, no accounts).

**Your data and Claude:** the Sync buttons and the Claude review run the `claude` command on your computer. That sends the text it reads (Slack tracker canvas, calendar events, meeting notes, tasks, your records) to Claude, with built-in tools turned off. Nothing is sent unless you press one of those buttons.

**Status:** it works with your personal notebook through Google and Slack connectors: notebook entries, wins, the leveling-guide Promo map, and the Intake Review Queue. The demo data folder (marked `.demo`) stays offline. The older evidence pipeline behind the demo's Releases page (`ingest/` through `lifecycle/`) still refuses any source without a written approval record.

To run it, test it, or read your notes on usage, see [INSTRUCTIONS.md](INSTRUCTIONS.md).

## Principles

- Every claim links to the exact source text behind it.
- Facts the sources state, your role in them, and why they mattered are kept as separate layers.
- Nothing is approved without you. Impact is never invented; the app asks you for it.
- Unapproved sources and unapproved fields are refused at import.
- Content can be fully deleted, and the tests check it.

## Layout

| Folder | What it does |
|---|---|
| `ingest/` | Import envelope format, importer, and the inbox file handoff |
| `correlate/` | Turns imported records into activities and groups them into episodes by explicit key |
| `claims/` | Rule checks, the template drafter, approval, and accomplishment versions |
| `export/` | Markdown export with a source reference on every claim |
| `lifecycle/` | Purge: removes a source's content everywhere |
| `web/` | The local pages (loopback only), the background Sync jobs, and the Intake Review Queue |
| `google/` | Google Calendar, Google Tasks, and meeting-note summaries through Claude Code's Google Workspace connector |
| `slack/` | Reading the Slack tracker canvas, sorting its items, and importing them |
| `guide/` | The leveling guide, links from your work to it, the Promo map, and Claude's read-through |
| `claude_cli.py` | Runs Claude Code headless for one narrow job, with built-in tools off |
| `fixtures/` | The synthetic demo story and its built-in traps |
| `storage/` | Database tables, removed-record and skip-rule bookkeeping, and the sync log |

Stack: Python 3.12, FastAPI, SQLAlchemy, SQLite, Jinja2, Typer.
