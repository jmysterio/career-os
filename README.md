# Career OS

A local, evidence-backed work journal. It gathers traces of your work, connects the related ones, and drafts accomplishment statements that you review and approve. It runs only on your laptop.

**Status:** milestone 1, a prototype that runs on synthetic demo data only. Every command refuses a data folder without a `.demo` marker. A real source needs a written approval record first.

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
