// A message arrives as ?msg=… in the address. Once it's on screen, drop it from the address so a refresh or a
// reload after a sync doesn't show a stale message again.
const url = new URL(location.href);
if (url.searchParams.has("msg")) {
  url.searchParams.delete("msg");
  history.replaceState(null, "", url.pathname + url.search + url.hash);
}

// A record card's action panels float over the list, so only one is open at a time; Escape closes it.
document.addEventListener("toggle", (ev) => {
  if (ev.target.matches?.("details.act") && ev.target.open) {
    document.querySelectorAll("details.act[open]").forEach((d) => { if (d !== ev.target) d.open = false; });
  }
}, true);
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") document.querySelectorAll("details.act[open]").forEach((d) => { d.open = false; });
});

// A citation like [3] points into the folded Sources list: open it so the browser can scroll to the source.
function openTarget() {
  const el = location.hash && document.getElementById(location.hash.slice(1));
  const box = el && el.closest("details");
  if (box && !box.open) { box.open = true; el.scrollIntoView({block: "center"}); }
}
window.addEventListener("hashchange", openTarget);
openTarget();
