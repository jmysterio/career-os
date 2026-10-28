"""Long syncs run in a background thread; the page polls their step-by-step progress."""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Callable

SHOW_FINISHED_SECONDS = 15 * 60


class Job:
    def __init__(self, steps: list[str]):
        self.steps = [dict(label=label, state="pending", detail="") for label in steps]
        self.state, self.message = "running", ""
        self.started, self.finished = datetime.now(), None
        self.cur, self.frac = -1, 0.0
        self._lock = threading.Lock()

    def start(self, i: int, detail: str = "") -> None:
        with self._lock:
            self.cur, self.frac = i, 0.0
            self.steps[i].update(state="running", detail=detail)

    def sub(self, done: int, total: int) -> None:
        with self._lock:
            if self.cur >= 0 and total:
                self.frac = min(1.0, done / total)
                self.steps[self.cur]["detail"] = f"{done} of {total}"

    def done(self, i: int, detail: str = "") -> None:
        with self._lock:
            self.steps[i].update(state="done", detail=detail)

    def fail(self, i: int, detail: str) -> None:
        with self._lock:
            self.steps[i].update(state="error", detail=detail)

    def skip(self, i: int, detail: str = "") -> None:
        with self._lock:
            self.steps[i].update(state="skipped", detail=detail)

    def finish(self, message: str) -> None:
        with self._lock:
            states = [st["state"] for st in self.steps]
            self.state = ("error" if "done" not in states else "partial" if "error" in states else "done")
            self.message, self.finished = message, datetime.now()

    def as_dict(self) -> dict:
        with self._lock:
            n = len(self.steps)
            settled = sum(1 for st in self.steps if st["state"] in ("done", "error", "skipped"))
            running = 1 if any(st["state"] == "running" for st in self.steps) else 0
            pct = 100 if self.finished else int(100 * (settled + running * self.frac) / n)
            return dict(state=self.state, message=self.message, pct=pct, steps=[dict(st) for st in self.steps],
                        started=self.started.strftime("%I:%M %p").lstrip("0"))


class Jobs:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, name: str, steps: list[str], fn: Callable[[Job], None]) -> bool:
        """False if that sync is already running."""
        with self._lock:
            cur = self._jobs.get(name)
            if cur and cur.state == "running":
                return False
            job = self._jobs[name] = Job(steps)

        def run():
            try:
                fn(job)
            except Exception as exc:  # anything unexpected still ends the job with a readable message
                for i, st in enumerate(job.steps):
                    if st["state"] == "running":
                        job.fail(i, f"Something went wrong: {exc}")
                    elif st["state"] == "pending":
                        job.skip(i)
                job.finish("The sync stopped early. Try again; if it keeps failing, the message above says why.")
            else:
                if job.state == "running":
                    job.finish("Finished.")

        threading.Thread(target=run, daemon=True, name=f"sync-{name}").start()
        return True

    def status(self) -> dict[str, dict | None]:
        out = {}
        for name, job in self._jobs.items():
            if job.finished and (datetime.now() - job.finished).total_seconds() > SHOW_FINISHED_SECONDS:
                continue
            out[name] = job.as_dict()
        return out
