# Career OS: build plan

**Goal:** work data flows in on its own every day, gets sorted against the leveling guide, and turns into a written promotion case you only have to review and polish.

This plan covers nine pieces of work, in the order I'd build them. Each one says what you get, how it works in plain terms, what you need to decide, how big it is, and how we'll know it works. Edit anything: reorder, cut, change the answers to the questions, or add notes under a section. Lines starting with **Decide:** are open questions; answer them in place.

Sizes: **S** is about an hour, **M** is a few hours, **L** is most of a day.

---

## Phase 1: Make it run on its own

### 1. Automatic backups (S)

**You get:** a fresh copy of your notebook every day, without thinking about it. The last 30 days are kept, and older copies are deleted.

**How it works:** each evening, before the sync runs, the app copies the database into `backups/` in your notebook folder (a safe copy, even while the app is open). A **Restore from a backup** step goes into INSTRUCTIONS.

**Decide:** keep 30 daily copies, or also keep one per month for a year?

**Done when:** a backup appears daily, old ones roll off, and restoring one in a test gives back the same data.

### 2. Daily automatic syncs, and the app always running (M)

**You get:** you never press Sync or restart the app again. Each morning the app is open and up to date, and the Intake Review Queue holds only yesterday's new items.

**How it works:**
- A new `careeros sync all` command runs the same steps as the two Sync buttons (Google: Calendar, Tasks, notes summaries; Slack tracker; then Claude links new records to the guide) and writes a log.
- Two small macOS scheduled tasks (the same system macOS uses for its own background helpers):
  - **App:** starts the app when you log in, and restarts it if it ever stops.
  - **Sync:** runs `sync all` every evening after your 5 PM Slack automation, plus a catch-up run when you log in if the evening run was missed (laptop closed).
- If a sync fails, for example because a sign-in expired, you get a macOS notification saying which one and what to do. The **Last pulled in** box shows it too.
- `careeros schedule install`, `uninstall`, and `status` set this up and remove it, so nothing is hidden.

**Decide:**
- What time for the evening run? (Suggestion: 6:00 PM.)
- Also run a morning sync (say 8:00 AM) to catch the morning's calendar?
- Notifications only on failure, or also a one-liner on success ("Synced: 4 new items")?

**Done when:** with the laptop open, the evening sync runs by itself and the next morning shows green. If the app is killed, it comes back within a minute. Uninstall removes everything.

---

## Phase 2: Make the evidence accurate

### 3. Group duplicate records of the same work (M)

**You get:** one deployment that shows up as a calendar meeting, a Slack thread, and a Google task becomes **one accomplishment with three pieces of evidence**, not three thin ones. The Promo map stops counting the same work three times, and the promotion case reads stronger.

**How it works:**
- A new "work item" groups related records. When Claude reads new records, it also gets the last two weeks of work items and says "this belongs with item 42", or "this is new work".
- Guide links and wins attach to the work item. Points on the Promo map are counted once per work item.
- In the Intake Review Queue, grouped records show a small "part of: OCC 5.1.2 release" chip, with **Not the same work** to split one out and a way to merge two by hand.
- A one-time run groups everything already in the notebook, and you review the groups like any other Claude picks (marked AI).

**Decide:**
- How far back can records belong to the same work? (Suggestion: 14 days.)
- Should a group's date be its first day or its last day? (Suggestion: last, when the work finished.)

**Done when:** the three records of a known deployment group together, the Promo map counts it once, and splitting or merging works in the queue.

### 4. Impact numbers (M)

**You get:** real counts that sell impact, such as "led 31 deployments", "ran 9 sandbox refreshes", "reviewed 47 pull requests", "supported 6 teams". They're shown on the Promo map for this year, this half, and all time, and the promotion-case writer uses them.

**How it works:** when Claude reads a record, it also tags what kind of activity it was, from a short fixed list. The app then counts the tags, once per work item, so nothing is double-counted.
- deployment
- sandbox refresh
- release coordinated
- PR reviewed or approved
- incident or blocker resolved
- document written
- process change
- mentoring or teaching
- demo or presentation

**Decide:** is that the right list of activities? Add or remove any that matter for a DevOps release manager, such as "access request", "branch audit", or "change log".

**Done when:** counts match a hand check on a sample month, and every count can be clicked to show the records behind it.

---

## Phase 3: Write the case

### 5. Claude writes the promotion case (L)

**You get:** a **Write my promo case** button on the Promo map. Claude drafts a real narrative, not a list, organized by the leveling guide.

**What the draft contains:**
- **A summary:** a short opening, "Ready for Grade 6, already doing Grade 7 work in X and Y".
- **One section per guide area you've shown:** what you did, how big it was, what changed because of it, and the impact numbers.
- **A gaps section:** Grade 6 and 7 experiences without enough evidence yet, written honestly.

**How it works:**
- **Built from your evidence only:** Claude writes from your work items, wins, the "why it mattered" lines, and the counts. It gets nothing else, and it's told never to invent a number or an outcome.
- **Every sentence cites its sources:** a small [1] [2] links to the records behind it. The app checks each one; a sentence with no valid source is highlighted so you can fix or delete it.
- **Editable and versioned:** you edit the draft right in the app. Each saved draft is kept as a version, so you can compare this month's with last month's.
- **Section by section:** **Rewrite this section** redoes one area, for example after you add a big win.
- **Your own wording wins:** Claude never rewrites a section you've edited unless you ask.

**Decide:**
- **Format:** does your org use a specific template (for example: summary, key accomplishments, impact, behaviors or values, growth areas)? If so, paste the headings here and the writer will follow them.
- **Time window:** the last 12 months, or a range you pick each time?
- **Voice:** first person ("I led…") or third person ("Jordan led…")?

**Done when:** a draft from your real notebook reads like a promotion case, every sentence's sources open the right records, no number appears that isn't in your data, and editing and versions work.

### 6. Export the promotion case to a Google Doc (S)

**You get:** **Send to Google Docs** creates a nicely formatted Doc in your Drive (headings, bullets, and source links turned into footnotes or a sources table at the end), ready to share with your manager.

**How it works:** the same way the Sync buttons reach Google, with Claude Code allowed to use only the create-a-document tool. The draft text goes to your Google Drive, nowhere else. You get the link back.

**Decide:**
- Should the Doc keep the [1] [2] source markers (good for you), or should there be a clean copy without them (good for sharing)? Or both?
- Which Drive folder?

**Done when:** the Doc opens with the right formatting and the link is saved next to that draft version.

---

## Phase 4: Fill the picture with stronger sources

### 7. New sources: GitHub, Google Docs you wrote, the release sheet (L)

**You get:** hard evidence of outcomes, added automatically by the daily sync.

- **GitHub pull requests:** the ones you merged, reviewed, or approved, with title, repo, date, and link. This is direct proof for "deployments" and "version control" in the guide. It uses your existing GitHub sign-in (`jtetzelSFDC`) and talks to GitHub directly, without Claude, so only titles and links are stored.
- **Google Docs you own or edited:** runbooks, SOPs, refresh plans, release notes. Each gets title, date, and link, plus a two-line Claude summary of what the doc is. This feeds the documentation and knowledge-sharing parts of the guide.
- **Release schedule sheet:** each release row (name, date, status) becomes a record, so the case can say "coordinated 14 releases, all shipped on schedule".

Every new record goes through the same steps as the others: Claude sorting, the Intake Review Queue, guide links, work-item grouping, and counts. Skip rules and Remove work the same way.

**Decide:**
- **GitHub:** which repos or orgs count? Is any of this on GitHub Enterprise rather than github.com?
- **Docs:** only docs you own, or also ones you edited heavily? Any folders to skip?
- **Release sheet:** which sheet (paste the link), and which columns mean release name, date, and status?
- **Approvals:** confirm it's fine for IRS-related repo and doc titles to be kept in this notebook and summarized by Claude.

**Done when:** a test sync brings in last month's PRs, docs, and releases without duplicates, and they show up correctly on the Promo map.

### 8. Capture kudos and recognition (M)

**You get:** a new **Recognition** kind of record, with its own tab, for when other people credit you: Slack thank-yous, shout-outs, "great job on the refresh", and manager praise. Recognition is some of the strongest promotion evidence, and the writer quotes it, briefly and with the source.

**How it works:** the daily Slack sync also searches Slack for messages that mention you alongside words of thanks or credit. Claude keeps only real recognition (not "thanks for the invite"). Each one is saved with who said it, when, a short quote, and a link. You can also mark any record as recognition by hand.

**Decide:**
- Only public channels, or DMs too? (DMs are more personal; your call.)
- Quote the praise word for word in the promotion case, or paraphrase it?
- Should recognition count more than a plain record on the Promo map? (Suggestion: same as a medium win.)

**Done when:** a known kudos message from the past month is found and a "thanks for the invite" is not.

---

## Phase 5: Keep you on track

### 9. Friday digest with nudges (S to M)

**You get:** every Friday afternoon, a short summary in the app plus a macOS notification that links to it.
- This week: new wins, guide areas you moved forward, and the counts that went up.
- Nudges, for example:
  - "2 large wins have no 'why it mattered' yet."
  - "No Grade 7 mentoring evidence in 60 days. Idea: run a knowledge-transfer session."
  - "14 records waiting in the Intake Review Queue."

**How it works:** the same scheduled task runs a digest step on Fridays. The nudges come from the Promo map's existing "Aim for next" logic, plus simple checks.

**Decide:**
- **Day and time:** Friday 3 PM?
- **Channel:** in-app plus notification only, or also a Slack DM to yourself? (That would send the digest text to Slack.)

**Done when:** the digest appears on Fridays, its counts match the week, and each nudge links to the place to act on it.

---

## Phase 6: Simplify

### 10. Retire the old demo pipeline (M)

**You get:** a simpler app that's easier to maintain, with nothing you use removed.

**What goes:** the first prototype's parts that your real notebook never uses: the Releases page, the import-file system, the claims checker, and the demo story built on them.

**What stays:** the practice notebook is kept as a small fake notebook (fake meetings, Slack items, and wins) for trying things out safely.

**Decide:** fine to remove the Releases page and the `demo`, `import`, `export --anchor`, and `purge` commands? Or keep the demo exactly as it is?

**Done when:** the tests pass, the app behaves the same for your real notebook, and the README and INSTRUCTIONS describe only what exists.

---

## Not in this plan (on purpose)

- **Backfilling older history** (Slack messages from the past two years, older calendar). It's worth doing for this year's case. Once pieces 3 and 8 exist it's mostly a one-time run, so it's easy to add as a step at the end.

## How I'll build it

One phase at a time: tests first, then the change, then a check on a copy of your notebook before it touches the real one. Each phase gets a backup, notes in INSTRUCTIONS, and its own pull request for you to review.
