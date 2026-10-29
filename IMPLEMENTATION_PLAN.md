# Career OS: implementation plan

Companion to `PLAN.md`. `PLAN.md` says what and why; this says how, file by file. Edit freely. Anything under **Answer first** blocks the work until you answer it (type your answer right after the question).

## How every feature ships

- One branch and one pull request per feature, named `feature/NN-short-name` (for example `feature/01-backups`). Item 7 is split into three PRs (7a, 7b, 7c) because it is the biggest.
- Branch from `main`. If a feature needs an earlier one that isn't merged yet, base the PR on that earlier branch and say so at the top of the PR body ("Stacked on #N"). Merge in order, and GitHub retargets the next PR to `main` by itself.
- Inside each PR: test first, then the change, then a run on a **copy** of your notebook (`cp -R` the data folder), never the real one. Run `uv run --offline pytest -q` before pushing.
- PR body: what changed in two or three lines, how it was tested, what is not covered. End with the Claude Code line.
- When a PR is up, you run `/ponytail:ponytail-review the pr #N`. Fix the findings as extra commits on the same branch, then merge.
- Each PR adds a short note to `INSTRUCTIONS.md` for anything you'll use by hand.
- Each PR that adds or changes something you'd notice also updates `README.md`: keep its tone (short, plain, a little funny, about not spending your time justifying your paycheck), keep "What's next" current, and refresh a screenshot in `docs/img/` when a screen changes a lot. Screenshots come from the practice notebook only, never the real one; the repo is public.
- No PRs exist yet. They get opened as each feature is built.

## Facts about the code that shape the plan

- Schema changes: new **tables** appear automatically (`Base.metadata.create_all` in `storage/db.py`). New **columns** on existing tables must be added to the `added` dict in `init_db`, or old notebooks won't get them. There is no Alembic (removed).
- Sync steps live in `web/syncs.py` (`run_google`, `run_slack`) and report into a `Job`. The Claude record review is `guide/ai_review.py` (`review`, `_apply`, `read_batch`). The Promo map is `guide/service.py` (`promo_map`).
- Every Claude call goes through `claude_cli.py` (`ask`, `call_tool`, `call_tools`) with built-in tools off. New connectors reuse these. Don't add another `subprocess` call.
- Two processes can write the notebook at once (the running app and a scheduled sync). SQLite handles it (WAL, 5 second wait), but keep write transactions short.
- A launchd job has a bare environment: no shell `PATH`. Use absolute paths to `uv` and `claude` (`claude_cli._claude()` already falls back to `~/.local/bin/claude`).

## Order, and one change I suggest

Build in your order **except** consider doing item 10 first. It deletes code (claims, correlate, ingest, purge, the old demo) and items 3, 4 and 5 all touch the models and the Promo map, so deleting first means fewer conflicts and less to read. Your call: **Answer first:** 10 first, or last as written? **Answer: 10 first.**

Dependencies: 2 needs 1. 4 needs 3. 5 needs 3 and 4. 6 needs 5. 9 needs 2 (and uses 4 and 5's data). 7 and 8 need 2 and plug into 3 and 4.

---

## 1. Automatic backups (S) — `feature/01-backups`

**Answer first:** 30 daily copies only, or also one per month for a year? (Suggestion: also monthly. It costs a few extra files and protects against a mistake you notice late.) **Answer: 30 daily plus one per month for 12 months.**

**Change**
- New `src/careeros/backup.py`, about 25 lines:
  - `make_backup(dd)` uses Python's built-in `sqlite3.Connection.backup()`. This is the safe copy while the app is open and the database is in WAL mode. Don't copy the file with `cp`.
  - Writes `dd.root / "backups" / "careeros-YYYY-MM-DD.db"`. If today's exists, overwrite it.
  - `prune(dd, daily=30, monthly=12)` keeps the newest 30 files plus the first file of each of the last 12 months.
- `DataDir` gets a `backups` property. `create()` makes the folder with mode `0o700`, like the others.
- CLI: `careeros backup now` and `careeros backup list`. Item 2's `sync all` calls `make_backup` first.
- `INSTRUCTIONS.md`: "Restore from a backup" — stop the app, move `careeros.db` and the `-wal` and `-shm` files aside, copy the backup in as `careeros.db`, start the app.

**Tests** (`tests/test_backup.py`)
- Make a notebook with a few rows, back it up, and open the backup: same rows.
- Create 40 fake daily files and check that pruning keeps 30 plus the monthly ones.
- Backup runs while another connection holds an open write: it still produces a readable copy.

**Risks:** the backup contains all your data, so keep the `0o700` folder mode. Backups sit next to the live database, so they don't protect against losing the laptop. Say so in INSTRUCTIONS; copying to iCloud is a later decision.

---

## 2. Daily automatic syncs and the app always running (M) — `feature/02-scheduler` (stacked on 1)

**Answer first**
- Evening run time? (Suggestion: 6:00 PM.) **Answer: 6:00 PM.**
- Also a morning run at 8:00 AM? **Answer: yes, 8:00 AM.**
- Notify only on failure, or also on success? **Answer: failures only.**

**Change**
- `careeros sync all` in a new `src/careeros/sync_all.py` plus a CLI command:
  1. `make_backup` (item 1).
  2. Run `syncs.run_slack` then `syncs.run_google`, the same functions the buttons use. They need a `Job` and a lock. Check `web/jobs.py` first: if `Job` can't be built outside the web app, pass a small stand-in object with the same methods that prints to the log. Don't copy the sync steps.
  3. Write a line per step to `logs/sync-YYYY-MM-DD.log` in the data folder, and keep a `SyncRun` row as the buttons already do.
  4. Exit non-zero if any step failed.
- Failure notification: `osascript -e 'display notification ...'` through `subprocess` with a list argument (no shell string). The text comes from the step's error message, which already says what to do ("sign in again"). Escape quotes. Success notification only if you chose it.
- `careeros schedule install | uninstall | status` in `src/careeros/schedule.py`. It writes two launchd agent files into `~/Library/LaunchAgents/` using `plistlib` (standard library), then runs `launchctl bootstrap gui/<uid>` and `bootout`.
  - **App agent** (`com.careeros.app`): `RunAtLoad`, `KeepAlive`, runs `<absolute uv> run careeros serve`. Set `WorkingDirectory` to the repo. Log to `logs/app.log`.
  - **Sync agent** (`com.careeros.sync`): `StartCalendarInterval` for the evening (and morning) time, and `RunAtLoad` for the catch-up. The catch-up must be a no-op if a successful run already happened today: `sync all` checks `SyncRun` and exits quickly. Add `--force` for manual runs.
  - `status` shows whether each is loaded, the last run time, and the last log line.
  - `uninstall` removes both files and unloads them. Nothing else is created.
- Two writers at once: the sync agent is a separate process from the app, so the app's in-process write lock doesn't cover it. That is fine because each write commits quickly. Add a test that proves `sync all` finishes while the app's session is open.

**Tests**
- `sync all` with the connectors patched (as `test_sync_google_runs_every_step` does): calls backup, both syncs, writes the log, returns the right exit code on failure.
- Catch-up is a no-op after a same-day success.
- Plist generation: assert the dict contents (paths, intervals, `KeepAlive`) without calling `launchctl`. Keep `launchctl` calls behind one tiny function that tests replace.
- Manual check, listed in the PR: install, kill the app and watch it return within a minute, uninstall, confirm nothing is left.

**Risks:** this is the item most likely to break in a way the tests can't see. launchd runs with a bare environment, and Claude Code's connector sign-in must work from a background agent (it should, since it is your login session, but verify with one real run and say so in the PR). If the laptop sleeps through the run, the login catch-up covers it, but not a laptop that stays open and asleep at 6 PM; launchd runs missed calendar jobs on wake, which is fine.

---

## 3. Group duplicate records of the same work (M) — `feature/03-work-items`

**Answer first**
- How far back can records join the same work? (Suggestion: 14 days.) **Answer: 14 days.**
- Group date = first day or last day? (Suggestion: last.) **Answer: last day.**

**Design choice that keeps this small:** don't move guide links and wins onto the work item. That means migrating links and changing every query that reads them. Instead, give each record a `work_item_id`, and have the Promo map count **distinct work items** (a record with no group counts as its own item). Links stay on records. One extra column, one new table, one changed count.

**Change**
- `storage/models.py`: new `WorkItem(id, title, day, by_ai, created_at)`. `JournalEntry` gets `work_item_id` (nullable foreign key). Add `("work_item_id", "INTEGER REFERENCES work_item(id)")` to `init_db`'s `added`.
- `guide/ai_review.py`:
  - `_context` also sends the last N days of work items (id, title, day).
  - The reader's answer gets one new field per record: `work: {"join": <id>}` or `{"new": "<title>"}` or null. Validate it: `join` must be an id that was sent. Anything else is ignored.
  - `_apply` sets `work_item_id` or creates a `WorkItem`. Respect the existing rule that a record the user checked (`reviewed`) is never touched, and the re-check added in the audit PR (a record changed while Claude reads is skipped).
  - Update the prompt in `read_batch` and its tests.
- `guide/service.py` (`promo_map`, `ai_counts`): count `COUNT(DISTINCT COALESCE('w'||work_item_id, 'e'||id))` per guide item instead of per record. Do this in one helper so item 4 reuses it.
- Review queue UI (`templates/review.html`, `_sheet_row.html`, `app.py`):
  - A "part of: <title>" chip on grouped records.
  - **Not the same work** (sets `work_item_id` to null) and **Merge into…** (pick another item). Both take the write lock and check CSRF like the other sheet routes. Delete a work item when it has no records left.
- One-time grouping of existing records: `careeros guide group` (batches through the same reader, marked AI). Dry-run flag that prints the proposed groups without saving.

**Tests**
- Three records that Claude's fake reader groups: Promo map counts one.
- Invalid `join` id is ignored. Split and merge routes work. A record you split stays split on the next review (set a flag, or rely on `reviewed`; decide in the PR and test it).
- Existing notebook without the new column gets it on open.

**Risks:** the quality of grouping is Claude's judgment, so it ships marked AI and reviewable, and the backfill has a dry run. A wrong merge inflates or deflates the Promo map; that's why the split button matters.

---

## 4. Impact numbers (M) — `feature/04-impact-counts` (stacked on 3)

**Answer first:** is the activity list right? Add or remove (for example "access request", "branch audit", "change log"). **Answer: the nine from PLAN.md plus access request handled, branch audit, hotfix, and training or certification completed (13 total).**

**Change**
- `guide/activities.py`: the fixed list as one constant (key, label), starting with your nine. This is the only place the list lives; the prompt, the validation and the page all read it.
- `JournalEntry.activity` (nullable string, added in `init_db`).
- Reader output gets `activity`; `_apply` stores it only if it is in the constant list.
- Counting reuses item 3's distinct-work-item helper: one count per work item per activity. **Changed when built: one count per work item per day** (you chose this after seeing 14 vs 28 vs 36 deployments on your data).
- Promo map shows the counts for this year, this half, and all time. Each count links to a list of the records behind it (`/impact/<activity>?window=...`), grouped by work item.
- Backfill: `careeros guide review --redo` already re-reads records; check that it fills `activity` without wiping your edits, or add an `--activities-only` pass. Mention the cost in the PR (it re-reads every record).

**Tests:** counts on a fixture month, checked by hand in the test; a work item with three records counts once; unknown activity is dropped; half-year boundaries (Jan 1, Jul 1, last day of the year).

**Risks:** "this half" depends on what your org calls a half. Calendar halves are assumed; say so on the page.

---

## 5. Claude writes the promotion case (L) — `feature/05-promo-writer` (stacked on 4)

If it gets too big, split it into 5a (generate and show a draft with citations) and 5b (edit, versions, per-section rewrite). The plan below is written so the split is clean.

**Answer first**
- Org template headings (paste them), or use summary / accomplishments / impact / behaviors / growth? **Answer: the default headings: Summary, Key accomplishments, Impact, Behaviors & values, Growth areas.** (The guide-area evidence and gaps feed these sections.)
- Time window: last 12 months, or pick each time? **Answer: last 12 months by default, editable each time.**
- Voice: first person or third person? **Answer: third person ("Jordan led…").**

**Change (5a)**
- New tables: `PromoVersion(id, created_at, window_start, window_end, voice, google_doc_url)` and `PromoSection(id, version_id, key, heading, body, edited)`. `body` stores sentences as JSON: `[{"text": "...", "sources": [12, 15]}]`.
- `promo/evidence.py`: builds the input for one section from the database only: work items, wins, "why it mattered", counts, recognition. Each piece gets a number. Nothing else goes to Claude.
- `promo/write.py`:
  - One `claude_cli.ask` call per guide area plus one for the summary and one for gaps. Run them with the same 3-worker pattern as `ai_review`. Input goes on stdin, and the prompt says: use only this evidence, never invent a number or outcome, cite every sentence by evidence number, return JSON.
  - **Check the answer in code, not just in the prompt:**
    - every cited number must exist in the evidence sent for that section;
    - every digit sequence in a sentence must appear in the evidence or the counts for that section;
    - a sentence that fails either check is saved with `valid: false`.
  - Runs as a background `Job` (it takes minutes), like the syncs, with a progress step per section.
- UI: **Write my promo case** on the Promo map, a draft page that renders `[1] [2]` as links to the records, and highlights invalid sentences in a clearly different style (not colour alone).

**Change (5b)**
- Edit a section in place (a plain text area; save sets `edited = True`).
- Version list and a side-by-side compare of two versions (plain text diff using `difflib` from the standard library).
- **Rewrite this section** re-runs one section. Skip any section with `edited = True` unless you confirm.

**Tests:** fake reader returns a sentence with a bad citation and one with an invented number: both flagged. Edited sections survive a regenerate. Versions are kept. The evidence builder never includes records outside the window.

**Risks:** the number check is a safeguard, not a proof, so the draft is always yours to review. Everything in the draft is sent to Claude, so it only contains what you've already put in the notebook. Cost grows with the number of sections; show the count before starting.

---

## 6. Export the promotion case to a Google Doc (S) — `feature/06-docs-export` (stacked on 5)

**Answer first:** keep `[1] [2]` markers, a clean copy, or both? Which Drive folder (paste the link)? **Answer: both (a sourced version and a clean copy); My Drive root.**

**Change**
- `google/docs_export.py`: formats a version as Markdown/plain text with a sources table at the end (title, date, link per cited record), then calls `claude_cli.call_tools` allowing only `mcp__plugin_google-workspace_google-workspace__create_doc` (the folder is passed in the prompt). Parse the Doc link from the tool's answer; fail with a clear message if there isn't one. Save it in `PromoVersion.google_doc_url`.
- **Changed when built:** the Google connector can't read local files (`file_path` returns "Path does not exist" for any path on this laptop), so the Markdown goes to Claude on stdin and into `import_to_google_doc`'s `content`; the app then reads the Doc back with `get_doc_as_markdown` and compares words (98% must match) to catch any change on the way.
- Long text: `call_tools` currently takes the prompt as a command-line argument, and macOS limits that to about 1 MB total. Add an optional `stdin` argument to `call_tools` (`ask` already does this) so a long draft doesn't hit the limit.
- Button on the draft page: **Send to Google Docs**; shows the link afterwards.
- Run it behind the same "personal notebook only" check as the syncs.

**Tests:** fake connector returns a Doc link: saved on the version. Reply without a link: error, nothing saved. The "clean copy" option has no `[n]` markers.

**Risks:** the draft text goes to Google Drive through Claude, as the plan says. The Doc formatting depends on what `create_doc` supports; check one real run on a throwaway folder before merging.

---

## 7. New sources (L) — three PRs

All three add records with `source` set to `github`, `docs` or `releases`, an `external_id` for dedupe, then go through the normal path (Claude read, review queue, guide links, work items, counts). Skip rules and Remove must work; reuse `storage/removal.py`.

**Answer first (all three)**
- Confirm it's fine to keep IRS-related repo and doc titles in this notebook and have Claude summarize them. **Answer: yes.**

### 7a. GitHub — `feature/07a-github`
**Answer first:** which repos or orgs count? Any GitHub Enterprise host? **Answer: all PRs on github.com for the `jtetzelSFDC` account; no Enterprise host.**
- `github/connector.py` runs `gh search prs` through `subprocess` (list arguments) with `--json` for: PRs you authored and merged, and PRs you reviewed. No Claude involved. Fields kept: title, repo, date, URL, role (author / reviewer). Use `--hostname` for Enterprise.
- `external_id = "gh:<repo>#<number>:<role>"`. Import is idempotent.
- **Changed when built:** a real pull found about 1,000 reviewed PRs a year (mostly routine branch PRs), so reviews come in as one record per repo per week (`gh:reviews:<repo>:<monday>`) with the PR list attached, growing as the week fills; merged PRs stay one record each. Reviews are searched a month at a time (one search tops out at 1,000) with a short pause between searches (GitHub's secondary rate limit). Skip rules match title or repo (`careeros github skip`).
- Fits item 2's `sync all` as another step; add a step label in `syncs.py`.
- Tests: canned JSON, no duplicates on a second import, role handled, org filter applied.
- Risk: `gh` is logged in as `jtetzelSFDC` and your personal repo is under `jmysterio`. Decide in this PR which account the sync uses, and fail clearly if `gh` isn't signed in.

### 7b. Google Docs you wrote — `feature/07b-docs`
**Answer first:** only docs you own, or also ones you edited heavily? Folders to skip? **Answer: docs owned plus ones edited heavily; no folders skipped yet (keep the skip setting).**
- Search Drive through `call_tool` with the Drive search tool, owner = you, modified since the last run. Reuse the `summaries.py` pattern for the two-line summary (the Read-only-saved-files setup is already there).
- Store title, date, link, and the summary as an attachment labelled AI-written.
- **Changed when built:** Drive's search shows only the last editor, so "edited heavily" = files others own where you were the last editor when the sync looked. Files are searched a month at a time (100 per search), Gemini notes and files already linked to a meeting are left out, and Sheets and Slides count too. One record per file per week it changed ("Wrote"/"Edited", then "Updated"). Summaries read the file with `get_drive_file_content`, then `ask` (no tools) trims to two lines. Folder skipping isn't possible from the search results, so skip rules match titles (`careeros docs skip`). It runs as a step of Sync Google. Real run: 96 files and 96 summaries in 12 minutes, then 37 drafted wins.
- Skip folders: a small config file in the data folder, like the Slack canvas id.
- Tests: canned Drive listing, skipped folder, summary failure keeps the record without a summary.
- Risk: the Drive result format is unknown. First commit in the PR is capturing one real sample into a test fixture.

### 7c. Release schedule sheet — `feature/07c-releases`
**Answer first:** the sheet link and which columns are release name, date, and status. (Your notes mention an existing "CRM Release Dates" tab; confirm that's the one.) **Answer: skip 7c for now.**
- Read the sheet through `call_tool` with the sheet-read tool. The column mapping lives in a small config file in the data folder (set once with `careeros releases connect <link> --name B --date C --status F`).
- One record per release row; update status when it changes (like Tasks updating done state); never delete.
- Tests: parse a canned range, a status change updates instead of duplicating, a row with no date is skipped and reported.

---

## 8. Capture kudos and recognition (M) — `feature/08-recognition`

**Answer first**
- Public channels only, or DMs too? **Answer: public channels only.**
- Quote word for word or paraphrase in the case? **Answer: short word-for-word quotes, with who said it.**
- Weight on the Promo map? (Suggestion: same as a medium win.) **Answer: same as a medium win.**

**Change**
- New record kind `recognition`. Find where kinds are listed (`web/app.py`, templates, `slack/classify.py`) and add it; add its tab.
- `slack/kudos.py`: Slack search through `call_tool` (`slack_search_public`, or `slack_search_public_and_private` only if you choose DMs). Your Slack user id comes from the profile tool once and is stored in the data folder.
- Claude filter step with `ask`: given each candidate message, keep only real recognition and return who, a short quote, and the permalink. Anything else is dropped.
- `external_id` = the message permalink, so reruns don't duplicate.
- A "Mark as recognition" action on any record (sets the kind; follows the existing kind-change code, including `kind_was`).
- Promo map and item 5's evidence builder include recognition with the chosen weight, quote kept as stored.
- Added to `sync all` as a step.

**Tests:** fake search results containing a real kudos and "thanks for the invite": only the first is kept; rerun adds nothing; manual marking works.

**Changed when built:** searching your mention together with a praise word fuzzy-matches the name ("Tetzel" finds "Wetzel"), so the search is your mention alone, a month at a time, following extra pages (cursor) up to 5 per month. Your own messages and bots are dropped before Claude. Quotes show mentions as @Name and must appear word for word in the message, or the message's own words are used. It runs as a step of the Slack sync (not a separate `sync all` step). Real run: 68 mentions in a year of public channels, 0 kudos.

**Risks:** the Slack search tool's output format is unknown, so capture a real sample first, as in 7b. DM search sends private messages to Claude; that is why it's your decision, and the default is public only.

---

## 9. Friday digest with nudges (S to M) — `feature/09-digest` (stacked on 2)

**Answer first:** Friday 3 PM? In-app plus notification only (suggestion), or also a Slack DM to yourself? **Answer: Friday 12:00 PM, in-app plus notification (no Slack DM).**

**Change**
- `digest.py`: `build(s, week_end)` returns new wins, guide items that gained links this week, activity counts that rose (item 4), and the nudges. Nudges reuse the existing "Aim for next" logic in `guide/service.py` plus three simple checks (large wins missing "why it mattered", an area with no evidence in 60 days, queue size). Each nudge carries a link to where to act.
- Computed when the page loads: `/digest` shows the current week. No new table. (If you later want history, add one then.)
- `careeros digest notify`: builds it and shows a macOS notification that opens `http://127.0.0.1:8765/digest`. The notification text is generated by code, not Claude.
- `schedule install` (item 2) gets a third agent entry for Friday at the chosen time.
- Slack DM: leave out unless you ask. It sends your work summary to Slack.

**Tests:** a fixture week gives the expected counts and nudges; no nudges when nothing is wrong; every nudge link resolves to a real route.

**Risks:** the page depends on item 4's data; if 4 isn't merged, leave that section out.

---

## 10. Retire the old demo pipeline (M) — `feature/10-retire-prototype`

**Answer first:** remove the Releases page and the `demo`, `import`, `export --anchor`, and `purge` commands? Or keep the demo as is? **Answer: remove them; keep `demo seed` as a small fake practice notebook. Build this first.**

**Change**
- Before deleting, list every user of each piece (`rg` for the names, including tests, templates, CLI and strings). Delete a package only when nothing in the real notebook path imports it.
- Candidates: `claims/`, `correlate/`, `ingest/`, `lifecycle/` (purge), the Releases page and routes in `web/app.py`, and the old pieces of `export/` (keep what the real notebook export uses: the zip, wins and promo exports).
- `fixtures/demo.py` becomes a small practice notebook of fake meetings, Slack items and wins (no releases, no envelopes). `careeros demo seed` stays; the other demo commands go.
- Tables for the removed features stay in existing databases (empty and harmless). Don't write a migration that drops them; dropping data is not worth the risk. Remove the model classes only if nothing reads them.
- Update README and INSTRUCTIONS so they describe only what exists.

**Tests:** the full suite passes with the removed tests deleted; add one test that the real notebook opens and works without the removed tables' code; the demo seeds and renders every page.

**Risks:** a deleted module that something imports lazily inside a function (this codebase does that a lot) won't fail until runtime. Use `rg` for every name and open each page in the demo afterwards.

---

## Not in this plan

Backfilling older Slack and calendar history. Add it after 3 and 8, as a one-time `sync all --since <date>` run.
