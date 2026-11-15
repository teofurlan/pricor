/** The group a tester's link names (`/?g=<id>`), kept for this browser session only. */

const KEY = "pricor_group";
const VALID = /^[a-z0-9_-]{1,40}$/;

export function storedGroup(): string | null {
  try {
    const value = window.sessionStorage.getItem(KEY);
    return value !== null && VALID.test(value) ? value : null;
  } catch {
    return null;
  }
}

/**
 * Reads `g` from the URL, keeps it when valid and removes it from the address at once
 * (path, other query values and the `#w=` fragment stay). Safe to call twice.
 */
export function captureGroup(): string | null {
  if (typeof window === "undefined") return null;
  const params = new URLSearchParams(window.location.search);
  if (!params.has("g")) return storedGroup();
  const value = params.get("g") ?? "";
  params.delete("g");
  window.history.replaceState(window.history.state, "", location(params));
  if (!VALID.test(value)) return storedGroup();
  try {
    window.sessionStorage.setItem(KEY, value);
  } catch {
    // Storage may be blocked; this page load still reports the group.
  }
  return value;
}

function location(params: URLSearchParams): string {
  const query = params.toString();
  return window.location.pathname + (query ? `?${query}` : "") + window.location.hash;
}
