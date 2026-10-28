# Career OS: How to use it

Plain-language notes on running and testing the app. New questions and answers get added at the bottom under **Q&A**. For what the app *is*, see [README.md](README.md).

## Where things stand

The app runs on your laptop only and works on **made-up demo data**. It cannot read your real Slack, Google, or git yet, and that is deliberate. It refuses any data folder that isn't marked as demo.

The demo story is a fake release called "October B": a spreadsheet row, some git merges, and a few traps. Here is what the app does with it:

1. **Imports** evidence in a controlled way. It refuses unapproved sources and refuses files carrying fields that weren't pre-approved.
2. **Connects** related items using explicit IDs like `DEMO-101`, never "it happened the same day". When an ID could belong to two releases, it only *suggests* a link and asks you.
3. **Drafts accomplishment statements** as small structured claims. Each claim points at the exact piece of source text behind it.
4. **Refuses to overclaim.** It blocks things like:
   - turning "team deployed 12 changes" into "I deployed 12 changes"
   - turning "target: 20%" into "achieved 20%"
   - inventing impact. It leaves impact blank and asks you.
5. **Waits for you.** Nothing counts until you click "Looks right". You then save it to your accomplishments, and it exports a Markdown file with a source reference on every claim.
6. **Can delete a source completely**: database, leftover files, and exports. Tests prove it.

## Start your notebook (the everyday way)

Your real, permanent notebook lives in `~/Library/Application Support/CareerOS`. It survives restarts. Open Terminal and run:

```
cd ~/Documents/career-os
uv run careeros serve
```

Open **http://127.0.0.1:8765** in a browser. Leave the terminal running. Press **Ctrl+C** in it to stop the app. If the page stops loading (for example after the Mac restarts), run the same command again. Your entries and wins are still there.

Don't add `--data-dir` to this command. That flag points the app at a different folder, such as the practice demo below.

## Start the practice demo (made-up data)

```
cd ~/Documents/career-os
uv run careeros demo seed --data-dir /tmp/cos-demo
uv run careeros serve --data-dir /tmp/cos-demo
```

`/tmp` is cleared when the Mac restarts. Just run `demo seed` again to rebuild the demo. To start fresh at any time, delete `/tmp/cos-demo` and seed again. Never put real notes here.

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

**Download promo case** writes a Markdown draft grouped by grade and topic. Each guide item lists the wins and entries behind it, with dates and why they mattered, and a **Not shown yet** list at the end shows what to aim for before you submit.

## Intake Review Queue: sorting everything that comes in

The **Intake Review Queue** (in the Menu) lists every record (calendar meetings, Google Tasks, Slack items, and what you typed) as rows, newest first, 100 to a page. Each row has one-click buttons:

- **Type**: Meeting, Convo, Doc, Task, or Other. The lit one is the current type.
- **Leveling guide**: the guide items the record shows. Click &times; to remove one, or **edit**/**link** to pick items yourself.
- **Win**: **S**, **M**, or **L** makes the record a small, medium, or large win (or resizes it), and &times; removes the win. Click the win's title to see why it mattered, then **Edit on Wins** to reword it.
- **Looks right** marks the row checked. Whatever Claude picked for it becomes yours, and the row leaves the **Not checked yet** list, so you can work down the list until it's empty.
- **Remove** (under Looks right) takes a record out for good, for example a meeting you didn't attend. Its pasted notes, guide links, and any win Claude drafted from it go too; wins you made or edited stay. Calendar, Tasks, and Slack syncs skip removed records so they don't come back. Choose **Removed** in the Show menu to see them and **Restore** one if you change your mind.

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

It never touches rows you've marked checked or guide links you picked yourself. Record text, attached notes, and the leveling guide pass through the AI tool. Calendar and Tasks syncs never delete a record that has a win, guide links, or your check on it.

## Slack: your Work Activity Tracker canvas

Your Slack Work Activity Tracker canvas (the one Slackbot fills in every day) comes into the notebook as entries. Claude reads each work item and decides whether it was a meeting, a conversation, a document, or a task. Anything it can't place goes to **Other**. Every entry from Slack has a **from Slack** label, the tracker's notes underneath (marked as written by Slack's AI), and a link back to the Slack thread. Items that are already in the notebook are skipped, so syncing again is safe. Tasks from Slack come in as done. When the tracker says why something mattered, the entry gets a dashed **suggested win** label and the **Count this as a win** form is pre-filled with that reason, so you can edit it into your own words and save.

**The Sync Slack tracker button** on the Today page reads the canvas through Claude Code's Slack connector. It only works once Slack is signed in for Claude Code. If it says it couldn't reach the connector, sign Slack in again from the AI Expert Suite and retry. The canvas is already connected. To connect a different one, run:

```
cd ~/Documents/career-os
uv run careeros slack connect <canvas link>
```

**Importing a saved canvas** (for example one of your old Weekly Contributions canvases): save its text to a file, then run `uv run careeros slack import <file>`. The 2025 Weekly Contributions canvases are already imported.

## Year-end exports

At year end, pick the year on the Wins tab and click **Download as Markdown**. The file opens with your large wins as highlights, then lists everything by theme with its date and why it mattered. Paste it into a promotion doc or use it to pick resume bullets. Removing a notebook entry never removes a win made from it.

## What you should see

The app has these pages, switched by the tabs at the top (Today, Meetings, Conversations, Documents, Tasks, Other, and Releases in the practice folder):

- **Meetings / Conversations / Documents / Tasks / Other**: one tab per kind of entry, newest first, with everything saved under it. On **Tasks**, anything still open is listed at the top, and finished tasks are grouped by the day you completed them.


- **Today & this week** (the home page): your daily notebook. Pick what kind of thing it was (a meeting, a conversation, a document, or something else), type a few words, and click **Add to notebook**. Entries are grouped by day for the last 7 days, with a small tally at the bottom. Under the line there is an optional **Paste notes, a link, or a transcript** box for long text (meeting notes, a Gemini transcript, a Slack canvas, a prompt you wrote, or a URL). Every entry can hold several of these, and **Add more to this** attaches another later. Use the date box to log something from an earlier day, and **Remove** to delete an entry. These are your own notes, so nothing needs approval and nothing is checked.
- **Releases**: the release cards described below.

On the Releases page:

- A greeting ("Good morning") and a note saying this is a practice notebook with made-up data.
- The page opens in **dark mode**. The **Switch to light** button (top right) changes it, and the app remembers your choice.
- Two release cards: "October B release" and "October C release".
- In the B card, under **Connected work**: two merges marked *connected*, plus a "Share deploy script" item marked *maybe related*. That means the app isn't sure and is asking you.
- Three groups of notes:
  - **What happened:** what the records show.
  - **What I did:** your part in it.
  - **Why it mattered:** in your words only.
- Under every note, a collapsed **Where this came from** with the quote from the source. Open it to see it.
- Under **Questions for you**: "Why did this matter? Add it in your own words. I won't guess."

## Testing steps (about 10 minutes)

Do these in order.

1. Click **Looks right** on a few notes. They turn *confirmed*.
2. In the box at the bottom, type why it mattered, for example "Fewer failed deployments reduced on-call load", and click **Add**. Then click **Looks right** on it. The app never writes this part for you.
3. Click **Save to my accomplishments**. A "Saved as version 1 (current)" line appears.
4. Click **This isn't part of it** on one of the merges. Notes drawn from it go away or show a "Needs your attention" message. This shows the app respects your correction.
5. Simulate a source change. In a second Terminal window:
   ```
   cd ~/Documents/career-os
   uv run careeros demo edit --data-dir /tmp/cos-demo
   ```
   Refresh the page. A "Heads up" message appears, because something you confirmed has changed.
6. Export the result. In the seeded demo the "October B" release is number 5:
   ```
   uv run careeros export --anchor 5 --data-dir /tmp/cos-demo
   ```
   If you haven't saved yet, it tells you to do that first. Otherwise it prints the path of a Markdown file. Open it. Every note shows where its evidence came from.
7. Test deletion:
   ```
   uv run careeros purge --source demo-sheet --reason test --data-dir /tmp/cos-demo
   ```
   It asks you to confirm. It then wipes everything that came from the demo spreadsheet, including derived notes and exports. The demo git data stays.

If something looks wrong or confusing, note what you clicked and what you saw. That feedback matters most right now.

## Running the automated tests

```
cd ~/Documents/career-os
uv run pytest
```

You should see `108 passed`. A failure means something broke. Don't use the app until it's fixed.

## What comes next

1. **Use the demo and judge the feel.** Is reviewing claims light, or does it feel like homework? If it's heavy, fix the design before connecting anything real.
2. **Start the approvals conversation now.** It is the slowest step and is not code:
   - Who owns the release schedule sheet and the IRS-related repos, and are they okay with a personal tool keeping titles and timestamps from them?
   - Is there an approved AI model for work content? Until then the app stays rule-based.
   - Is the laptop folder backed up or synced anywhere (Time Machine, iCloud)?
3. **Connect one real source first: your local git repos.** They need no logins or admin approval and they hold real work. Start with a non-IRS repo if you have one, or use only commit titles and dates.
4. **Then the release schedule sheet** (it holds the real outcomes), **then Google Calendar, then Slack** (noisiest, most likely to need admin approval).
5. **After 3-4 real weeks of use,** consider AI-written drafts, the annual self-review, and career goals.

Keep real data out of `/tmp/cos-demo`. The app refuses anything not marked demo until we deliberately open that door.

## Q&A

**I ran `demo seed` and saw `duplicate: 3`. Is that an error?**
No. It means the demo data was already loaded and the app recognized the files and skipped them. That is the "importing twice changes nothing" safety working.

**Every button showed `{"error":"bad origin"}`. Was that expected?**
No, it was a bug on my side. The page told the browser not to send any referrer, and Chrome then labels form submissions with an origin of "null", which the app's safety check rejects. I fixed it, and a real Chrome click-through now works. The app still rejects "null" and foreign origins on purpose, and a test guards both.

**Why "What happened / What I did / Why it mattered" and not "Tasks I completed"?**
The first layer includes things the records say about the team, such as "Team deployed 12 changes". Under "Tasks I completed" those would read as yours. Keeping them separate is how the app avoids overclaiming for you. The wording is meant to feel like a notebook, not a courtroom. Tell me if you want different words.

**Is there a dark mode?**
Yes, it is the default. Use the button at the top right to switch. The choice is stored in a cookie in your browser.

**Where do meetings, Slack conversations, and documents I created show up?**
Type them into the **Today & this week** page. That is built now. Automatic pulling from Google Calendar, Docs, and Slack comes later with their connectors, and those do need approvals. Your own typed notes do not.

**Does the Today page need approvals?**
No. It is only what you type, stored on your laptop. The approval step (Gate 0) is for data pulled in from work systems. Note that the app still only runs on a folder marked as demo for now, so the notes you enter in the practice notebook live in `/tmp/cos-demo`. Say the word when you want a real notebook folder for the daily page.

**Can one entry hold several pieces, like a link plus notes plus a transcript?**
Yes. An entry is the thing you did ("Rollout sync with Sam"). Under it you can attach any number of pieces, each with a type (meeting notes, transcript, link, Slack canvas, prompt, other text) and an optional name. Removing the entry removes its pieces. Pasted text is shown as plain text only, and links are never opened or fetched by the app. Each piece is limited to about 200,000 characters.

**Is it okay to paste real meeting notes or transcripts?**
Not into the practice folder for anything real, since that folder is for made-up data and lives in `/tmp`. Before real pasting, we need a permanent notebook folder with the right protections, and you should decide whether that content is allowed to sit on this laptop (some work content, like IRS-related material, has handling rules).

**How do I start a real notebook?**
Run this once (Terminal, in `~/Documents/career-os`):
```
uv run careeros notebook init
uv run careeros serve
```
`init` creates `~/Library/Application Support/CareerOS` with owner-only permissions, tells Spotlight not to index it, and refuses any folder under iCloud, Dropbox, Google Drive, or OneDrive. After that, plain `uv run careeros serve` opens your real notebook (the practice one needs `--data-dir /tmp/cos-demo`). The real notebook is journal-only: no Releases tab, and importing work data stays switched off until a source is approved. It never mixes with demo data, and `demo seed` refuses to write into it.

**How do I search?**
Use the search box at the top of any page. It looks through your entry headlines, pasted text, and names, and every word you type must appear somewhere in the entry. It is not case-sensitive and the match is highlighted. `%` and `_` are searched as ordinary characters.

**Is my real notebook backed up?**
Not yet. Time Machine has no destination configured on this Mac, so if the laptop's disk is lost, so is the notebook. A backup or "save a copy as a Markdown file" command is the next thing worth adding.

**How do I pull in my Google Calendar meetings?**
This uses your calendar's private address, so no Google Cloud setup or admin sign-off is needed, and the data never passes through an AI tool. One-time setup:
1. In Google Calendar on the web, open Settings, pick your calendar under "Settings for my calendars", and scroll to **Integrate calendar**.
2. Copy the **Secret address in iCal format**. Treat it like a password: anyone with it can read that calendar.
3. In Terminal (in `~/Documents/career-os`): `uv run careeros calendar connect`, paste it (nothing shows as you paste), and press Enter.
4. `uv run careeros calendar sync` pulls the last 14 days (`--days 30` for more, max 60).

Meetings show on the Today page as "Had a meeting" with a "from calendar" tag. Only the **title and time** are kept; attendees, descriptions, locations, and video links are dropped before anything is saved. All-day items and cancelled meetings are skipped. Running sync again never duplicates; a renamed or moved meeting is updated, and a meeting that disappeared is removed unless you've attached notes to it. Anything you typed yourself is never touched. The address is stored in `calendar.url` in your notebook folder, readable only by you. If you ever reset the secret address in Google, run `connect` again.

Before using it on a work calendar, check that titles of meetings (which can name other people or IRS-related topics) are okay to keep on this laptop. Syncing is manual for now; it does not run by itself.

**Can I sync my calendar without the secret iCal address?**
Yes. On the Today page, press **Sync calendar** (or run `uv run careeros calendar pull`). It starts Claude Code in the background with permission to use only the calendar tool, fetches yesterday's and today's meetings through the Google Workspace connector, and saves title, time, and Google file links (Gemini notes, recordings). Declined meetings and all-day items are skipped. It then reads the Google Docs attached to each meeting (Gemini notes, shared notes) and saves a short "AI summary" under the meeting, with the notes linked beside it; meetings without notes say so. Expect a few minutes when there are many meetings. Nothing duplicates, and a failed summary is retried the next time you press the button. Recordings and chat files aren't read. Meeting titles, times, and attendee details pass through the AI tool on the way, so it only runs when you press it. It needs Claude Code installed and the Google Workspace connector signed in. `careeros calendar pull --days 7` reaches further back (max 14).

**How were my calendar and tasks pulled in?**
Through the Google Workspace connector in a Claude Code session, not by a script on its own. Meeting titles/times, the files attached to each meeting (Gemini notes, recordings, chat), and task titles and notes pass through the AI tool on the way in. Asking Claude to refresh pulls new ones without duplicating. Meetings you declined are dropped, and so are ones that vanished from the calendar, unless you attached your own notes. Open tasks stay off the Today page and live on the Tasks tab. Links to Google files are only links: the app never opens or reads the file. You need to be signed in to Google to open them.

**Where is my information stored, and is it backed up?**
Everything (entries, pasted notes, wins) is in one file: `~/Library/Application Support/CareerOS/careeros.db`, on this laptop only. It is not in iCloud or any synced folder, and the app refuses to keep a real notebook in one. Time Machine backs it up if Time Machine is on. To make a manual copy, stop the app and copy that file somewhere safe; a copy taken on Oct 27, 2026 is already there as `careeros-backup-2026-10-27.db`.

**Can I export everything, not just wins?**
Yes. Click **Download everything (CSV)** at the bottom of any page. You get one zip with four spreadsheets: `entries.csv` (every meeting, task, and note), `pasted_notes.csv` (everything pasted under them, with the entry it belongs to), `wins.csv`, and `guide_links.csv` (which wins and entries you linked to which leveling guide items). They open in Excel, Numbers, or Google Sheets, so the data stays readable even without this app. It's a snapshot of that moment; download a fresh one whenever you like, for example at year end. The zip holds everything you pasted, so keep it somewhere as safe as this laptop, and remember that removing something in the app doesn't remove it from zips you already downloaded. Text that starts with `=`, `+`, `-`, or `@` gets a leading `'` so a spreadsheet shows it instead of running it as a formula.

**After a restart the app opened with demo data and my entries were missing. Were they lost?**
No. The app had been started with `--data-dir /tmp/cos-demo`, which opens the practice folder instead of your notebook. Run `uv run careeros serve` with no `--data-dir` and your notebook comes back.
