// Intake Review Queue buttons save in the background: the row fades out when it leaves the current view, else redraws in place.
// Without this script the same forms still work as normal page loads.
document.addEventListener("submit", async (ev) => {
  const form = ev.target;
  const row = form.closest("table.sheet tr[id^='r']");
  if (!row) return;
  ev.preventDefault();
  const data = new FormData(form);
  if (ev.submitter && ev.submitter.name) data.append(ev.submitter.name, ev.submitter.value);
  row.classList.add("busy");
  let resp;
  try {
    resp = await fetch(form.action, { method: "POST", body: data, headers: { "X-Sheet": "1" }, credentials: "same-origin" });
  } catch (e) {
    location.reload();
    return;
  }
  if (!resp.ok) {
    location.reload();
    return;
  }
  if (resp.headers.get("X-Row") === "gone") {
    row.classList.add("gone");
    const count = document.getElementById("rowcount");
    if (count) count.textContent = Math.max(0, parseInt(count.textContent, 10) - 1);
    setTimeout(() => row.remove(), 400);
    return;
  }
  const tpl = document.createElement("template");
  tpl.innerHTML = (await resp.text()).trim();
  const fresh = tpl.content.querySelector("tr");
  if (fresh) row.replaceWith(fresh);
  else location.reload();
});
