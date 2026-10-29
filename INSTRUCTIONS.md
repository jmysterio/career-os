# Career OS: How to use it

Plain-language notes on running and testing the app. New questions and answers get added at the bottom under **Q&A**. For what the app *is*, see [README.md](README.md).

## Where things stand

Career OS is your work notebook. It pulls in your Google Calendar meetings, Google Tasks, and Slack tracker items, has Claude sort each one and link it to the DevOps leveling guide, and keeps your wins so the Promo map and promo case reflect what you've actually done. Everything is stored on this laptop. The only things that send anything out are the Sync buttons and the Claude review (see the README for what Claude sees).

There's also a **practice notebook** of made-up data, for trying things out without touching your real one.

## Start your notebook (the everyday way)

Your real, permanent notebook lives in `~/Library/Application Support/CareerOS`. It survives restarts. Open Terminal and run:

```
cd ~/Documents/career-os
uv run careeros serve
```

Open **http://127.0.0.1:8765** in a browser. Leave the terminal running. Press **Ctrl+C** in it to stop the app. If the page stops loading (for example after the Mac restarts), run the same command again. Your entries and wins are still there.

Don't add `--data-dir` to this command. That flag points the app at a different folder, such as the practice demo below.

## Let it run on its own (recommended)

One command sets up three small macOS scheduled tasks, so you never start the app or press Sync yourself:

```
cd ~/Documents/career-os
uv run careeros schedule install
```

- **The app** starts when you log in and restarts by itself if it ever stops. It's always at http://127.0.0.1:8765. If you'd started it yourself in a Terminal, stop that one (Ctrl+C) first.
- **The sync** runs at 8:00 AM and 6:00 PM (after your 5 PM Slack automation), and once when you log in if a run was missed while the laptop was closed. Each run backs up the notebook first, then does exactly what the Sync Slack tracker and Sync Google buttons do, then pulls your GitHub pull requests. If nothing is due, it does nothing.
- **If something fails**, for example a connector's sign-in expired, a macOS notification says which sync and what to do (usually: open AI Suite > Settings > Connections and sign in again). Nothing is shown when everything works; the **Last pulled in** box shows the times.
- **The digest** shows a notification on Fridays at 12:00 PM (if the laptop was asleep, as soon as it wakes). See **Weekly digest** below.
- `uv run careeros schedule status` shows whether each is on and the last sync log line. Logs are in `logs/` in your notebook folder.
- `uv run careeros sync all --force` runs a sync right now from Terminal.
- `uv run careeros schedule uninstall` removes the three tasks and nothing else.

## Start the practice notebook (made-up data)

```
cd ~/Documents/career-os
uv run careeros demo seed --data-dir /tmp/cos-demo
uv run careeros serve --data-dir /tmp/cos-demo
```

It holds a week of made-up meetings, Slack items, tasks, and notes, two wins, and a tiny made-up leveling guide, so every page has something to show. It never syncs with Slack or Google. `/tmp` is cleared when the Mac restarts; just run `demo seed` again. Never put real notes here.

## Wins: your accomplishments for reviews, promotion, and your resume

The **Wins** tab is where accomplishments go, small to large, all year. You can add one in two ways:

- On the **Wins** tab, type what you did, why it mattered, how big it was, and a theme, then click **Save to my wins**.
- On any entry in the other tabs (a meeting, a finished task), open **Count this as a win**. It starts with the entry's text so you can reword it, and it remembers which entry it came from.

Tips:

- **What I did** is one line starting with a verb: "Led", "Fixed", "Mentored", "Automated".
- **Why it mattered** is the result: who it helped, what got faster, cheaper, or safer. Numbers help. You can leave it blank and fill it in later with **Edit**; the page reminds you which wins still need it.
- **Size** is your own call: small for a helpful fix, large for something you'd lead a promotion case with.
- **Theme** (Delivery, Leadership, Mentoring, and so on) groups wins in the export, which maps nicely onto promotion criteria.

## Leveling guide and Promo map

The app knows the DevOps leveling guide, so your work can be lined up against what Grade 6 and Grade 7 ask for. You're Grade 5, aiming at 6, with Grade 7 evidence where the work is already at that level.

**Loading the guide.** The guide lives at `guides/Leveling Guides - DevOps.csv`. That folder is ignored by git, so the guide never goes to GitHub. It's already loaded. When a new version comes out, save it over that file and run:

```
cd ~/Documents/career-os
uv run careeros guide import "guides/Leveling Guides - DevOps.csv"
```

Links you've made are kept. Anything the new guide drops leaves the map but stays on the wins that pointed to it.

**Linking your work.** Each time you save a win, the app asks **Which parts of the leveling guide does this show?** It ticks the items that look related based on your words, such as "sandbox", "deploy", "merge", or "demo". Untick what doesn't fit, tick what it missed, and click **Save**, or choose **Skip for now**. Nothing is linked until you save. Notebook entries can be linked too. Entries that look related show a dashed **Might show** label with a link, and linked ones show **Shows:** with the items.

**The Promo map tab.** It shows:

- A progress bar for Grade 6 and for Grade 7 (how many key experiences you've shown).
- **Aim for next**: one concrete step per topic. Topics you've started come first, and a topic moves to its Grade 7 step once Grade 6 is shown.
- The 12 topics, each with the Grade 6 experiences beside the Grade 7 ones. Each is colored **Not yet**, **Started**, **Shown**, or **Strong**, with **Ideas to get here** underneath.
- The skills whose bar rises from Grade 6 to Grade 7, with your evidence for each.

Colors come from points. A linked entry is worth 1, and a small, medium, or large win is worth 2, 3, or 4. One point makes an item Started, 3 make it Shown, and 6 make it Strong. So one large win shows an experience, and a large win plus a medium one makes it strong. An entry and the win made from it only count once.

**Write my promo case** (on the Promo map, or at http://127.0.0.1:8765/promo/case) has Claude draft the case itself. Pick who it's about (your first name, remembered for next time) and the window (the last 12 months by default), then press the button; it takes a minute or two, with progress per section. The draft has five sections: **Summary, Key accomplishments, Impact, Behaviors & values, Growth areas**, written in the third person. Claude writes them only from your notebook: wins and why they mattered, pieces of work, linked records, the impact numbers, and the Promo map's gaps and next steps, all dated inside the window. Every sentence ends with small [numbers] that jump to its sources, listed at the bottom as they were when the draft was written. The app then checks each sentence itself: one with no source, or with a number that doesn't appear in its evidence, is marked **Check this** with the reason. The check catches invented numbers and missing sources, not every wrong word, so read the draft before you use it. Every draft is kept. From Terminal: `uv run careeros promo write` (with `--start`, `--end`, `--name`).

**Editing and rewriting a draft.** Under each section, **Edit** opens it as plain text, one sentence per line, with its sources as [numbers] at the end of the line: keep a number to keep that source, and your wording is checked the same way as Claude's. **Rewrite this section** has Claude redo just that section from the same evidence; if you've edited it, tick **Replace my edits** first. Either way the result is saved as a **new draft**, so nothing is ever overwritten. **All drafts and compare** lists every draft with what changed ("Edited Impact", "Rewrote Growth areas") and shows any two side by side: struck-through sentences are only in the first, underlined ones only in the second. Viewing an older draft shows a link to the newest.

**Sending a draft to Google Docs.** On a draft, **Send to Google Docs** makes two Docs in My Drive: one with the [numbers], the **Check this** notes, and a Sources list (for you), and a clean copy without them (for sharing). Fix any **Check this** sentences first if you're sharing, since the clean copy includes them without the warning. The draft passes through the AI tool on its way to Google (the Google connector can't read files on this laptop), so the app reads each new Doc back and compares its words with the draft: a step that doesn't match shows an error, and its link is still saved so you can look. Links to both Docs appear on the draft, and a copy of what was sent is kept in `exports/` in the notebook folder.

**Download evidence (Markdown)** writes the evidence behind the Promo map grouped by grade and topic. Each guide item lists the wins and entries behind it, with dates and why they mattered, and a **Not shown yet** list at the end shows what to aim for before you submit.

## Intake Review Queue: sorting everything that comes in

The **Intake Review Queue** (in the Menu) lists every record (calendar meetings, Google Tasks, Slack items, and what you typed) as rows, newest first, 100 to a page. Each row has one-click buttons:

- **Type**: Meeting, Convo, Doc, Task, or Other. The lit one is the current type.
- **Leveling guide**: the guide items the record shows. Click &times; to remove one, or **edit**/**link** to pick items yourself.
- **Win**: **S**, **M**, or **L** makes the record a small, medium, or large win (or resizes it), and &times; removes the win. Click the win's title to see why it mattered, then **Edit on Wins** to reword it.
- **Looks right** marks the row checked. Whatever Claude picked for it becomes yours, and the row leaves the **Not checked yet** list, so you can work down the list until it's empty.
- **Remove** (under Looks right) takes a record out for good, for example a meeting you didn't attend. Its pasted notes, guide links, and any win Claude drafted from it go too; wins you made or edited stay. Calendar, Tasks, and Slack syncs skip removed records so they don't come back. Choose **Removed** in the Show menu to see them and **Restore** one if you change your mind.

**Is everything pulled in?** The **Last pulled in** box at the top of the queue (and a line under each Sync button on Today & this week) shows when each source was last pulled, how many new items came in, and the date of the newest item. A green dot means up to date: Slack was pulled after 5:30 PM on the latest evening (the tracker automation runs at 5 PM), and Calendar was synced today. An orange dot says what's missing; press that Sync button. "(about)" means the time is estimated from when items were added, before the app kept a sync history.

**One piece of work, counted once.** A deployment often shows up three times: a calendar meeting, a Slack thread, and a Google task. Claude groups records like that into one piece of work, and the Promo map counts the piece once, at its strongest evidence (a large win made from one of them beats a plain record). A grouped row shows **Part of: OCC 5.1.2 release · 3 records** (marked AI until you check the row). **Not the same work** takes a row out of its group, and **Group with…** puts it in a nearby group or starts a new one you name. Claude never regroups a row you grouped, split, or marked **Looks right**. A piece of work runs at most 30 days from its first record, and a record joins only work that's had activity in the last 14 days, so groups don't snowball. New records are grouped after every sync. To group everything already in the notebook (it shows what it would do first with `--dry-run`):

```
uv run careeros guide group --dry-run
uv run careeros guide group
```

**Impact numbers.** Claude tags each record with the one activity it shows, from a fixed list: deployment, sandbox refresh, release coordinated, PR reviewed or approved, incident or blocker resolved, document written, process change, mentoring or teaching, demo or presentation, access request handled, branch audit, hotfix, and training or certification. Routine meetings and status pings get nothing, and a meeting *about* a deploy isn't a deployment. The Promo map's **By the numbers** table counts each activity for this half (calendar halves), this year, and all time. A piece of work counts once per day it was done: three records of the same deploy on the same day count once, and a release deployed to lab on Monday and to UAT on Thursday counts twice. Open tasks don't count. Click a number to see the records behind it. In the Intake Review Queue, **Counts as** shows each record's activity (marked AI until you set it) and lets you change it; Claude never changes one you set. New records are tagged after every sync. To tag everything already in the notebook: `uv run careeros guide activities`. The promo case download includes the table.

**Skipping a recurring meeting for good.** To keep a meeting you don't attend out of the notebook, including future ones, add a skip rule. It removes the ones already here and Calendar sync skips any meeting whose title contains the text (any capitalization):

```
uv run careeros calendar skip "IRS Sustainment DSU"
uv run careeros calendar skip                          # list the rules
uv run careeros calendar unskip "IRS Sustainment DSU"  # stop skipping
```

Buttons in the queue save without reloading the page: a row you check or remove fades out, and a row you change redraws in place.

Purple **AI** marks are Claude's picks: guide links, drafted wins, and type changes ("AI, was Other"). They count on the Promo map straight away, and the Promo map says how many are still unchecked. Use the **Show** menu for **Changed by Claude**, **Not linked**, **Wins**, or **Checked**.

**Claude's read-through.** Claude has read every record against the Grade 6 and 7 key experiences and skills. It linked each one to the guide items it shows (none for routine standups and status pings), drafted wins for the stand-out ones, and fixed obvious type mix-ups (only for Slack and typed records; calendar items stay meetings and Google Tasks stay tasks). When new records come in, the queue shows a **Have Claude read the N records it hasn't read** button. You can also run it in Terminal:

```
cd ~/Documents/career-os
uv run careeros guide review
```

It never touches rows you've marked checked or guide links you picked yourself. Because Claude takes a few minutes, it looks at each record again just before saving: a record you removed or checked in the meantime is skipped, and a record you retyped keeps your type. You can keep clicking around the app while it runs. Record text, attached notes, and the leveling guide pass through the AI tool, with Claude's built-in tools (files, shell, web) turned off. Calendar and Tasks syncs never delete a record that has a win, guide links, or your check on it.

## Slack: your Work Activity Tracker canvas

Your Slack Work Activity Tracker canvas (the one Slackbot fills in every day) comes into the notebook as entries. Claude reads each work item and decides whether it was a meeting, a conversation, a document, or a task. Anything it can't place goes to **Other**. Every entry from Slack has a **from Slack** label, the tracker's notes underneath (marked as written by Slack's AI), and a link back to the Slack thread. Items that are already in the notebook are skipped, so syncing again is safe. Tasks from Slack come in as done. When the tracker says why something mattered, the entry gets a dashed **suggested win** label and the **Count this as a win** form is pre-filled with that reason, so you can edit it into your own words and save.

**The Sync Slack tracker button** on the Today page reads the canvas through Claude Code's Slack connector, sorts the new items, and has Claude link them to the leveling guide, with a progress bar under the button. It only works while Slack is signed in for Claude Code; if the sign-in has expired the progress box says so, and you sign Slack in again from the AI Expert Suite and retry. The tracker canvas is large (over 250 KB), so the connector hands it over as a saved file, which the app reads back. The canvas is already connected. To connect a different one, run:

```
cd ~/Documents/career-os
uv run careeros slack connect <canvas link>
```

**Importing a saved canvas** (for example one of your old Weekly Contributions canvases): save its text to a file, then run `uv run careeros slack import <file>`. The 2025 Weekly Contributions canvases are already imported.

## Weekly digest

**Weekly digest** in the Menu shows the last seven days: how many records came in (and from where), the wins and kudos, the leveling guide items that gained evidence, and the week's activity counts next to this half's totals. **Week before** and **Week after** step through earlier weeks.

At the top are **nudges**, each with a link to where to act:

- **Aim for next:** the top two suggestions from the Promo map.
- **Big wins without "why it mattered":** medium and large wins with no impact sentence, which the promo case can't use well.
- **Quiet areas:** a Promo map area with evidence before but nothing in the last 60 days (unless it's already an Aim for next).
- **The queue:** 25 or more records in the Intake Review Queue not checked yet.

When nothing needs you, it says so. The page is worked out when you open it, from the notebook only: no Claude, nothing stored.

On Fridays at 12:00 PM the schedule shows a macOS notification like "This week: 13 wins, 54 records, 3 nudges. Open http://127.0.0.1:8765/digest". macOS doesn't open links from these notifications, so open the page from the Menu. To see it now: `uv run careeros digest notify`.

## Kudos: recognition from other people

**Sync Slack tracker** (and the scheduled sync) also looks for kudos: messages that mention you and recognize your work, in your **public and private Slack channels**. **DMs and group DMs are never searched.**

- It searches your @-mentions a week at a time (the first pull goes back a year) and leaves out your own messages and bots.
- **Before Claude sees anything**, messages without a word of praise (thanks, great, shout-out, congrats, appreciate, and so on) are dropped. In your first pull that was 2,155 mentions, of which only the ones with praise words were sent on.
- Claude then keeps only real recognition: praise, a shout-out, or thanks that says what you did. A bare "thanks!", thanks for an invite, requests, FYIs, and announcements that just list you among many people are dropped. When unsure, Claude drops it.

Each kept message becomes a **Kudos** record with a short **word-for-word quote** and who said it, like `Steph Rau: "really nice work on that alignment meeting with the PMs!!!"`, with a link to the message. If Claude's quote isn't exactly in the message, the message's own words are used instead. On the Promo map, a kudos record **counts like a medium win**, and the promo case quotes it exactly.

You can also mark any record as kudos yourself: press **Kudos** in its row of the Intake Review Queue. Everything recognition-related is on the **Kudos** tab.

What to expect: the first pull found 38 kudos in a year and took about 10 minutes; after that each sync only looks at the last couple of days. A week with more than 200 mentions (big release weeks) is read newest first, and the step says how many weeks were cut short.

Messages from private channels pass through Claude Code to be checked (only ones with praise words, and only their text, sender, and channel name). Your Slack user id and name are looked up once and saved in `slack_user.json` in the notebook folder. Kudos' last pull shows as the **Kudos** pill on Today and in **Last pulled in**.

## Google Docs, Sheets and Slides you wrote

**Sync Google** (and the scheduled sync) also brings in the Google Docs, Sheets and Slides you worked on:

- **Files you own** that changed since the last pull.
- **Files someone else owns** where you were the **last person to edit** when the sync looked. Google Drive doesn't say how much each person edited, only who edited last, so this is the stand-in for "edited heavily". Since the sync runs twice a day, it catches most of your editing sessions.
- **Gemini meeting notes are left out**, and so is any file already linked to a meeting: those come in with the meeting.

Each file comes in as a **document** record like "Wrote doc: Release Manager Runbook" (or "Edited sheet: ..." for someone else's file), with a link, and Claude adds a two-line **AI summary** of what the file is and what it covers. If the same file changes again in a later week, a short "Updated doc: ..." record is added, which Claude groups with the first. A summary that fails is retried on the next sync, and the record stays meanwhile.

The **first pull goes back a year**, which took about 12 minutes on your Drive (96 files). After that it's quick. Docs' last pull shows as the **Docs** pill on Today and in the **Last pulled in** box.

To keep files out by title (Drive's search doesn't show folders, so skipping is by title text):

```
cd ~/Documents/career-os
uv run careeros docs skip "Untitled"
uv run careeros docs skip               # list the rules
uv run careeros docs unskip "Untitled"
```

Adding a rule also removes matching records already in the notebook, and **Remove** in the Intake Review Queue keeps a file out for good, including later updates.

The file's text passes through Claude Code to write the summary. Claude has no tools while it summarizes, and only the two lines are saved, not the file.

## GitHub: pull requests you merged or reviewed

The scheduled sync (8 AM and 6 PM) also reads your GitHub pull requests on github.com, through the `gh` command already signed in as `jtetzelSFDC`. No Claude is involved in reading them; only the title, repo, date, and link are kept.

- **PRs you wrote and merged** come in one record each, like "Merged PR: Add Cherry-Pick Report (irs-github-automations#12)", with a link to the PR.
- **PRs you reviewed** come in as **one record per repo per week**, like "Reviewed 31 pull requests in ccirsgov-org, week of Oct 19", with the list of PRs attached. You review close to a thousand a year, nearly all routine branch PRs, so one record each would bury the Intake Review Queue. A week's record grows as more reviews arrive.
- The **first pull goes back a year**; after that each pull starts two days before the last one. Nothing is ever deleted by a sync.
- Then Claude links the new records to the leveling guide, like every other source. GitHub's last pull shows in the Intake Review Queue's **Last pulled in** box.

To pull right away instead of waiting for the schedule:

```
cd ~/Documents/career-os
uv run careeros github sync
```

To keep a repo (or any title text) out, for example this app's own PRs:

```
uv run careeros github skip jmysterio/career-os
uv run careeros github skip                    # list the rules
uv run careeros github unskip jmysterio/career-os
```

Adding a rule also removes the matching records already in the notebook. **Remove** in the Intake Review Queue works too, and a removed week stays removed.

If `gh` isn't signed in, the sync says so; run `gh auth login`.

## Year-end exports

At year end, pick the year on the Wins tab and click **Download as Markdown**. The file opens with your large wins as highlights, then lists everything by theme with its date and why it mattered. Paste it into a promotion doc or use it to pick resume bullets. Removing a notebook entry never removes a win made from it.

## What you should see

The app has these pages, opened from the three-bar **Menu** at the top left (Today & this week, Wins, Promo map, Intake Review Queue, then Meetings, Conversations, Documents, Tasks, Other). The name of the page you're on sits next to the Menu button:

- **Today & this week** (the home page): your daily notebook. Pick what kind of thing it was, type a few words, and click **Add**. Clicking into the row folds out tips and an optional **Paste notes, a link, or a transcript** box. Below it are the Sync buttons, then your entries grouped by day for the last 7 days, with a small tally at the bottom. Every entry can hold several pasted pieces (**Add more to this**), and **Remove** deletes an entry.
- **Wins**, **Promo map**, and the **Intake Review Queue**: described in their own sections above.
- **Meetings / Conversations / Documents / Tasks / Other**: one tab per kind of entry, newest first, with everything saved under it. On **Tasks**, anything still open is listed at the top, and finished tasks are grouped by the day you completed them.

The page opens in **dark mode**; **Switch to light** (top right) changes it, and the app remembers your choice.

## Testing steps (about 5 minutes, in the practice notebook)

1. Start the practice notebook (above) and open http://127.0.0.1:8765. A note at the top says it's a practice notebook.
2. On **Today & this week**, add an entry ("Paired with Sam on the release", kind "Had a conversation") and check it appears under Today.
3. Open **Wins**: two made-up wins are there. Use **Count this as a win** on your new entry, pick a size, and save; it asks which leveling guide items it shows.
4. Open **Promo map**: the made-up guide shows a few experiences as started or shown.
5. Open the **Intake Review Queue**, pick **Everything** in the first menu, and try **Looks right**, a type button, and **Remove** on a row. Rows update without the page reloading.
6. Search for "rollback" with the box at the top.

If something looks wrong or confusing, note what you clicked and what you saw.

## Running the automated tests

```
cd ~/Documents/career-os
uv run pytest
```

You should see `145 passed`. A failure means something broke. Don't use the app until it's fixed.

## What comes next

Your personal notebook is connected to Google Calendar, Google Tasks, Google Docs, the Slack tracker canvas, Slack kudos, and GitHub, and Claude links what comes in to the leveling guide. Ideas still open:

1. **Fill in older history.** The notebook mostly covers July to October 2026. Older Google Calendar history needs a little setup: the Claude connector reaches back 14 days at most (`uv run careeros calendar pull --days 14`), while connecting the calendar's private iCal address (`calendar connect`) lets `calendar sync --days 60` go back two months at a time. Older Slack work could be found by searching your messages, then read by Claude like everything else.
2. **Keep the approvals questions in mind:**
   - Do the owners of the IRS-related channels and repos mind a personal tool keeping titles and short notes from them?
   - Is Claude, through Claude Code, approved for this kind of work content?
   - Is the notebook folder backed up (Time Machine) and kept out of synced folders (iCloud, Dropbox)?
3. **More sources and automation** are planned in `PLAN.md` and `IMPLEMENTATION_PLAN.md`: daily automatic syncs, grouping duplicate records, impact counts, a Claude-written promo case, GitHub, Google Docs as a source, kudos, and a weekly digest.
4. **At year end,** download the promo case from the Promo map and your wins from the Wins tab.

Keep real data out of `/tmp/cos-demo`; the practice notebook never syncs with Slack or Google.

## Q&A

**Every button showed `{"error":"bad origin"}`. Was that expected?**
No, it was a bug on my side. The page told the browser not to send any referrer, and Chrome then labels form submissions with an origin of "null", which the app's safety check rejects. I fixed it, and a real Chrome click-through now works. The app still rejects "null" and foreign origins on purpose, and a test guards both.

**Is there a dark mode?**
Yes, it is the default. Use the button at the top right to switch. The choice is stored in a cookie in your browser.

**Can one entry hold several pieces, like a link plus notes plus a transcript?**
Yes. An entry is the thing you did ("Rollout sync with Sam"). Under it you can attach any number of pieces, each with a type (meeting notes, transcript, link, Slack canvas, prompt, other text) and an optional name. Removing the entry removes its pieces. Pasted text is shown as plain text only, and links are never opened or fetched by the app. Each piece is limited to about 200,000 characters.

**How do I start a real notebook?**
Run this once (Terminal, in `~/Documents/career-os`):
```
uv run careeros notebook init
uv run careeros serve
```
`init` creates `~/Library/Application Support/CareerOS` with owner-only permissions, tells Spotlight not to index it, and refuses any folder under iCloud, Dropbox, Google Drive, or OneDrive. After that, plain `uv run careeros serve` opens your real notebook (the practice one needs `--data-dir /tmp/cos-demo`). It never mixes with practice data, and `demo seed` refuses to write into it.

**How do I search?**
Use the search box at the top of any page. It looks through your entry headlines, pasted text, and names, and every word you type must appear somewhere in the entry. It is not case-sensitive and the match is highlighted. `%` and `_` are searched as ordinary characters.

**Is my real notebook backed up?**
Yes, on this laptop. `uv run careeros backup now` copies the notebook into `backups/` in the notebook folder, safely even while the app is running, and the daily automatic sync does it too. It keeps the last 30 days plus the first copy of each of the last 12 months, and deletes older ones. `uv run careeros backup list` shows them. These copies sit next to the notebook, so they protect against mistakes, not against losing the laptop: for that you'd also need Time Machine (no destination is set up on this Mac yet) or a copy somewhere else.

**How do I restore from a backup?**
1. Stop the app (Ctrl+C in its Terminal window).
2. In `~/Library/Application Support/CareerOS`, move `careeros.db`, `careeros.db-wal`, and `careeros.db-shm` into a spare folder (don't delete them yet).
3. Copy the backup you want from `backups/` (for example `careeros-2026-10-28.db`) into the notebook folder and rename it `careeros.db`.
4. Start the app again with `uv run careeros serve` and check your entries. Once you're happy, the moved files can go.

**How do I pull in my Google Calendar meetings?**
This uses your calendar's private address, so no Google Cloud setup or admin sign-off is needed, and the data never passes through an AI tool. One-time setup:
1. In Google Calendar on the web, open Settings, pick your calendar under "Settings for my calendars", and scroll to **Integrate calendar**.
2. Copy the **Secret address in iCal format**. Treat it like a password: anyone with it can read that calendar.
3. In Terminal (in `~/Documents/career-os`): `uv run careeros calendar connect`, paste it (nothing shows as you paste), and press Enter.
4. `uv run careeros calendar sync` pulls the last 14 days (`--days 30` for more, max 60).

Meetings show on the Today page as "Had a meeting" with a "from calendar" tag. Only the **title and time** are kept; attendees, descriptions, locations, and video links are dropped before anything is saved. All-day items and cancelled meetings are skipped. Running sync again never duplicates; a renamed or moved meeting is updated, and a meeting that disappeared is removed unless you've attached notes to it. Anything you typed yourself is never touched. The address is stored in `calendar.url` in your notebook folder, readable only by you. If you ever reset the secret address in Google, run `connect` again.

Before using it on a work calendar, check that titles of meetings (which can name other people or IRS-related topics) are okay to keep on this laptop. This iCal route isn't part of the scheduled sync; the scheduled sync uses the Sync Google route below.

**Can I sync my calendar without the secret iCal address?**
Yes. On the Today page, press **Sync Google** (or run `uv run careeros calendar pull` for the calendar part only). Sync Google does Calendar, the Google Docs you wrote (see that section), Google Tasks (from the task lists changed since the last pull; a task you finished in Google is marked done here, and a task list that couldn't be read is reported, never treated as deleted; the pull then isn't counted, so the next Sync Google looks back to the same point and picks up what was missed), and meeting-note summaries in one go, then has Claude link the new records to the leveling guide. Only meetings that have ended come in: a meeting later today shows up on the first sync after it's over, by which time its Gemini notes are usually attached (the 8 AM sync then catches notes that arrived overnight). A progress bar under the button ticks through each step and shows any error in plain words; you can keep using the app while it runs. If the calendar connector answers with an error (for example an expired Google sign-in), that step stops with the message instead of reading it as an empty calendar, so no meetings are removed. For the calendar part, it starts Claude Code in the background with permission to use only the calendar tool, fetches yesterday's and today's meetings through the Google Workspace connector, and saves title, time, and Google file links (Gemini notes, recordings). Declined meetings and all-day items are skipped. It then reads the Google Docs attached to each meeting (Gemini notes, shared notes) and saves a short "AI summary" under the meeting, with the notes linked beside it; meetings without notes say so. Expect a few minutes when there are many meetings. Nothing duplicates, and a failed summary is retried the next time you press the button. Recordings and chat files aren't read. Meeting titles, times, and attendee details pass through the AI tool on the way, so it only runs when you press it or when the schedule you installed runs it. It needs Claude Code installed and the Google Workspace connector signed in. `careeros calendar pull --days 7` reaches further back (max 14).

**How were my calendar and tasks pulled in?**
Through the Google Workspace connector in a Claude Code session, not by a script on its own. Meeting titles/times, the files attached to each meeting (Gemini notes, recordings, chat), and task titles and notes pass through the AI tool on the way in. Asking Claude to refresh pulls new ones without duplicating. Meetings you declined are dropped, and so are ones that vanished from the calendar, unless you attached your own notes. Open tasks stay off the Today page and live on the Tasks tab. Links to Google files are only links: the app never opens or reads the file. You need to be signed in to Google to open them.

**Where is my information stored, and is it backed up?**
Everything (entries, pasted notes, wins) is in one file: `~/Library/Application Support/CareerOS/careeros.db`, on this laptop only. It is not in iCloud or any synced folder, and the app refuses to keep a real notebook in one. Time Machine backs it up if Time Machine is on. Daily copies go into `backups/` next to it (see "Is my real notebook backed up?" below). A few one-off copies from October 2026 also sit in the notebook folder as `careeros-backup-2026-10-*.db`.

**Can I export everything, not just wins?**
Yes. Click **Download everything (CSV)** at the bottom of any page. You get one zip with four spreadsheets: `entries.csv` (every meeting, task, and note), `pasted_notes.csv` (everything pasted under them, with the entry it belongs to), `wins.csv`, and `guide_links.csv` (which wins and entries you linked to which leveling guide items). They open in Excel, Numbers, or Google Sheets, so the data stays readable even without this app. It's a snapshot of that moment; download a fresh one whenever you like, for example at year end. The zip holds everything you pasted, so keep it somewhere as safe as this laptop, and remember that removing something in the app doesn't remove it from zips you already downloaded. Text that starts with `=`, `+`, `-`, or `@` gets a leading `'` so a spreadsheet shows it instead of running it as a formula.

**After a restart the app opened with demo data and my entries were missing. Were they lost?**
No. The app had been started with `--data-dir /tmp/cos-demo`, which opens the practice folder instead of your notebook. Run `uv run careeros serve` with no `--data-dir` and your notebook comes back.
