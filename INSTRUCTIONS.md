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
5. **Waits for you.** Nothing counts until you click approve. You then publish, and it exports a Markdown file with a source reference on every claim.
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

- A yellow **SYNTHETIC DATA** banner.
- Two release boxes: "October B release" and "October C release".
- In the B box, under *Linked activity*: two merges linked automatically, plus a "Share deploy script" item marked **suggested**. That means the app isn't sure.
- Claims in three groups:
  - **Observation:** what the source says.
  - **Attribution:** what *you* did.
  - **Interpretation:** why it mattered.
- Under every claim, its evidence quote and a reference like `cos://obs/5#status[0:8]`, with a "source" link where the source has a URL.
- Under *Open questions*: "Impact / why it mattered is unknown - add it yourself."

## Testing steps (about 10 minutes)

Do these in order.

1. Click **Approve** on a few claims. They turn "human_approved".
2. Type an impact in the box, for example "Fewer failed deployments reduced on-call load". Click **Add impact**, then **Approve** it. The app never writes impact for you.
3. Click **Publish approved claims**. A "v1 active" line appears.
4. Click **Unlink** on one of the merges. Claims drawn from it should disappear or show a blocked message. This shows the app respects your correction.
5. Simulate a source change. In a second Terminal window:
   ```
   cd ~/Documents/career-os
   uv run careeros demo edit --data-dir /tmp/cos-demo
   ```
   Refresh the page. A **"Needs review"** warning appears, because evidence changed after you approved it.
6. Export the result. In the seeded demo the "October B" release is number 5:
   ```
   uv run careeros export --anchor 5 --data-dir /tmp/cos-demo
   ```
   It prints the path of a Markdown file. Open it. Every claim shows its layer, its approval state, and where the evidence came from.
7. Test deletion:
   ```
   uv run careeros purge --source demo-sheet --reason test --data-dir /tmp/cos-demo
   ```
   It asks you to confirm. It then wipes everything that came from the demo spreadsheet, including derived claims and exports. The demo git data stays.

If something looks wrong or confusing, note what you clicked and what you saw. That feedback matters most right now.

## Running the automated tests

```
cd ~/Documents/career-os
uv run pytest
```

You should see `56 passed`. A failure means something broke. Don't use the app until it's fixed.

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

*(Add questions and answers here as they come up.)*
