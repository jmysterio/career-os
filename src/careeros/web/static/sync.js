// Sync buttons start a background sync; this shows its progress step by step until it finishes.
const ICON = { pending: "○", running: "◐", done: "✓", error: "✕", skipped: "–" };

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

function render(name, job) {
  const box = document.querySelector(`.job[data-job="${name}"]`);
  if (!box) return;
  const form = document.querySelector(`form[data-sync="${name}"]`);
  const button = form && form.querySelector("button");
  const running = job.state === "running";
  if (button) {
    button.disabled = running;
    button.textContent = running ? "Syncing…" : button.dataset.label;
  }
  box.hidden = false;
  box.className = `job ${job.state}`;
  box.replaceChildren();
  const bar = el("div", "jbar");
  const fill = el("span");
  fill.style.width = `${job.pct}%`;
  bar.append(fill);
  box.append(bar);
  const list = el("ul", "jsteps");
  for (const st of job.steps) {
    const li = el("li", `js-${st.state}`);
    li.append(el("span", "jicon", ICON[st.state] || "○"), el("span", "jlabel", st.label));
    if (st.detail) li.append(el("span", "jdetail", st.detail));
    list.append(li);
  }
  box.append(list);
  if (!running) {
    const end = el("p", "jmsg", job.message);
    const again = el("button", "", "Show the new items");
    again.type = "button";
    again.addEventListener("click", () => location.assign(location.pathname));
    end.append(" ", again);
    box.append(end);
  } else {
    box.append(el("p", "jmsg", `Started at ${job.started}. You can keep using the app; this updates by itself.`));
  }
}

async function poll() {
  let status;
  try {
    status = await (await fetch("/sync/status", { cache: "no-store" })).json();
  } catch (e) {
    setTimeout(poll, 4000);
    return;
  }
  let running = false;
  for (const [name, job] of Object.entries(status)) {
    if (job) {
      render(name, job);
      running = running || job.state === "running";
    }
  }
  if (running) setTimeout(poll, 1500);
}

document.addEventListener("submit", async (ev) => {
  const form = ev.target;
  if (!form.dataset.sync) return;
  ev.preventDefault();
  document.querySelectorAll(".note.flash").forEach((n) => n.remove());
  const button = form.querySelector("button");
  button.disabled = true;
  button.textContent = "Starting…";
  try {
    const resp = await fetch(form.action, { method: "POST", body: new FormData(form), headers: { "X-Sync": "1" } });
    if (!resp.ok) throw new Error(resp.status);
  } catch (e) {
    button.disabled = false;
    button.textContent = button.dataset.label;
    const box = document.querySelector(`.job[data-job="${form.dataset.sync}"]`);
    box.hidden = false;
    box.className = "job error";
    box.replaceChildren(el("p", "jmsg", "Couldn't start the sync. Is the app still running? Refresh and try again."));
    return;
  }
  poll();
});

poll();
