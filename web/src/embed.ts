/** Tell the host page (the admin panel that embeds us in an iframe) that something happened.
 *  The target origin comes from the referrer, so we never broadcast to an unknown page. */
export function notifyParent(message: { type: string; [k: string]: unknown }): void {
  if (window.parent === window) return;
  let origin: string;
  try {
    origin = new URL(document.referrer).origin;
  } catch {
    return; // no referrer: stay silent rather than post to "*"
  }
  window.parent.postMessage(message, origin);
}

export interface ChatLocation {
  sessionId: string;
  token: string | null;
}

/** /chat/<session id>?token=... The token is moved to sessionStorage so it can be removed from the URL
 *  (history, screenshots, referrers) yet survive a reload. */
export function readChatLocation(loc: Location, store: Storage, history: History): ChatLocation | null {
  const m = loc.pathname.match(/^\/chat\/([^/]+)\/?$/);
  if (!m) return null;
  const sessionId = decodeURIComponent(m[1]);
  const storeKey = `pb_token_${sessionId}`;
  const fromUrl = new URLSearchParams(loc.search).get("token");
  if (fromUrl) {
    store.setItem(storeKey, fromUrl);
    history.replaceState(null, "", loc.pathname);
  }
  return { sessionId, token: fromUrl ?? store.getItem(storeKey) };
}
