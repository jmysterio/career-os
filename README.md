# Career OS

A local work notebook for building a promotion case. It pulls in your meetings, tasks, and Slack activity, has Claude sort each record and link it to your leveling guide, keeps your wins, and shows on a Promo map where you're strong and where the gaps are. The app and its database run only on your laptop (loopback address, no accounts).

**Your data and Claude:** the Sync buttons and the Claude review run the `claude` command on your computer. That sends the text it reads (Slack tracker canvas, calendar events, meeting notes, tasks, your records) to Claude, with built-in tools turned off. Nothing is sent unless you press one of those buttons.

**Status:** it works with your personal notebook through Google and Slack connectors: notebook entries, wins, the leveling-guide Promo map, and the Intake Review Queue. A practice notebook of made-up data (a folder marked `.demo`) stays offline. What's next is in [PLAN.md](PLAN.md) and [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

To run it, test it, or read your notes on usage, see [INSTRUCTIONS.md](INSTRUCTIONS.md).

## Principles

- Claude's picks (types, guide links, drafted wins) are marked AI until you check them, and everything it picked can be undone.
- Impact is yours: "why it mattered" comes from you or from your own Slack tracker, never invented.
- Syncs never delete a record you built on (a win, a guide link, or your check), and removed records stay removed.
- Nothing leaves the laptop except through the Sync buttons and the Claude review.

## Layout

| Folder | What it does |
|---|---|
| `web/` | The local pages (loopback only), the background Sync jobs, and the Intake Review Queue |
| `google/` | Google Calendar, Google Tasks, and meeting-note summaries through Claude Code's Google Workspace connector |
| `slack/` | Reading the Slack tracker canvas, sorting its items, and importing them |
| `guide/` | The leveling guide, links from your work to it, the Promo map, and Claude's read-through |
| `export/` | Downloads: wins and promo case as Markdown, and everything as CSV |
| `claude_cli.py` | Runs Claude Code headless for one narrow job, with built-in tools off |
| `fixtures/` | The practice notebook's made-up records, wins, and leveling guide |
| `storage/` | Database tables, removed-record and skip-rule bookkeeping, and the sync log |

Stack: Python 3.12, FastAPI, SQLAlchemy, SQLite, Jinja2, Typer.

The backdrop photos in `web/static/img/` were AI-generated for this project, each in a light and a dark version: the latte (`latte-*.jpg`, top-left), the pothos vine along the top (`vine-top-*.jpg`), and the pothos, snake plant, and fern down the right side (`plants-right-*.jpg`). Each is shot against a plain wall that drops out against the page, so only the cup and leaves show. To swap one, keep its file name, keep the subject where it is now with plain wall around it (off-white for light, charcoal for dark), and stay around 1500 px on the long side.
