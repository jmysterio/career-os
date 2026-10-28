# Career OS

A local, evidence-backed work journal. It gathers traces of your work, connects the related ones, and drafts accomplishment statements that you review and approve. The app and its database run only on your laptop (loopback address, no accounts).

**Your data and Claude:** the Sync buttons and the Claude review run the `claude` command on your computer. That sends the text it reads (Slack tracker canvas, calendar events, meeting notes, tasks, your records) to Claude, with built-in tools turned off. Nothing is sent unless you press one of those buttons.

**Status:** it works with your personal notebook through Google and Slack connectors. The demo data folder (marked `.demo`) stays offline, and a real source needs a written approval record first.

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
| `web/` | The local review page (loopback only) |
| `fixtures/` | The synthetic demo story and its built-in traps |
| `storage/` | Database tables |

Stack: Python 3.12, FastAPI, SQLAlchemy, SQLite, Jinja2, Typer.
