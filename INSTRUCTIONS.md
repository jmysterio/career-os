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

## Start the demo

Open Terminal. (Inside a Claude Code session, put `!` in front of each command.)

```
cd ~/Documents/career-os
uv run careeros demo seed --data-dir /tmp/cos-demo
uv run careeros serve --data-dir /tmp/cos-demo
```

Open **http://127.0.0.1:8765** in a browser. Leave the terminal running. Press **Ctrl+C** in it to stop the app.

`/tmp` is cleared when the Mac restarts. Just run `demo seed` again to rebuild the demo. To start fresh at any time, delete `/tmp/cos-demo` and seed again.

## What you should see

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

You should see `60 passed`. A failure means something broke. Don't use the app until it's fixed.

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
Not yet. Today the app only knows the demo release sheet and git. Calendar and Docs come with the Google connector, and Slack after that. Quick manual entries ("had a meeting with X", "wrote 3 docs") and a Today / This week view are planned and can be moved earlier, since they need no approvals.
