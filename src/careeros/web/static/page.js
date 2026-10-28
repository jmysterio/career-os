// A message arrives as ?msg=… in the address. Once it's on screen, drop it from the address so a refresh or a
// reload after a sync doesn't show a stale message again.
const url = new URL(location.href);
if (url.searchParams.has("msg")) {
  url.searchParams.delete("msg");
  history.replaceState(null, "", url.pathname + url.search + url.hash);
}
