import { useEffect, useMemo, useState } from "react";
import { adminApi } from "../api";
import type { SessionOut } from "../types";
import { TASKS, type MockTask } from "./tasks";
import { Viewer } from "./Viewer";

const KEY_STORE = "pb_api_key";

interface Active {
  task: MockTask;
  session: SessionOut;
}

/** A stand-in for a third-party admin panel. In a real panel the API call below happens on its server
 *  (the tenant API key must never reach a browser); here the key is pasted in for demo purposes. */
export function Admin() {
  const [key, setKey] = useState(() => sessionStorage.getItem(KEY_STORE) ?? "");
  const [tenant, setTenant] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [tab, setTab] = useState<"tasks" | "viewer">("tasks");
  const [fresh, setFresh] = useState(false);
  const [active, setActive] = useState<Active | null>(null);
  const [status, setStatus] = useState<Record<string, string>>({});
  const [viewerUser, setViewerUser] = useState("");
  const [toast, setToast] = useState<string | null>(null);
  const [launching, setLaunching] = useState<string | null>(null);

  const api = useMemo(() => adminApi(key), [key]);

  async function connect(k = key) {
    setConnecting(true);
    setError(null);
    try {
      const me = await adminApi(k).whoami();
      sessionStorage.setItem(KEY_STORE, k);
      setKey(k);
      setTenant(me.tenant_id);
    } catch (e) {
      setTenant(null);
      setError((e as Error).message);
    } finally {
      setConnecting(false);
    }
  }

  useEffect(() => {
    if (key) void connect(key); // reconnect after a reload
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The embedded chat tells us when the agent has saved the profile.
  useEffect(() => {
    function onMessage(e: MessageEvent) {
      if (e.origin !== window.location.origin || e.data?.type !== "profile-builder:saved") return;
      setStatus((s) => (active ? { ...s, [active.task.id]: "Profile updated" } : s));
      setToast(`Profile updated: ${e.data.saved} fact(s) saved${e.data.discarded ? `, ${e.data.discarded} discarded` : ""}.`);
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [active]);

  async function launch(task: MockTask) {
    if (!tenant) return;
    setLaunching(task.id);
    setError(null);
    setToast(null);
    try {
      const session = await api.createSession({
        // Same key = same session: clicking twice resumes instead of duplicating.
        idempotency_key: fresh ? `${task.id}-${Date.now()}` : task.id,
        tenant_id: tenant,
        agent: task.agent,
        end_user: task.end_user,
        task: {
          id: task.id, type: task.type, title: task.title, outcome: task.outcome, channel: task.channel,
          duration_sec: task.duration_sec, transcript_excerpt: task.transcript_excerpt,
        },
        locale: task.locale,
      });
      setActive({ task, session });
      setStatus((s) => ({ ...s, [task.id]: s[task.id] === "Profile updated" && !fresh ? s[task.id] : "Debrief open" }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLaunching(null);
    }
  }

  if (!tenant) {
    return (
      <main className="admin">
        <h1>Mock admin panel</h1>
        <p className="muted">Paste the tenant API key from the seed script to connect.</p>
        <form className="row" onSubmit={(e) => { e.preventDefault(); void connect(); }}>
          <input aria-label="API key" type="password" placeholder="pk_…" value={key} onChange={(e) => setKey(e.target.value)} />
          <button className="primary" disabled={connecting || !key}>{connecting ? "Connecting…" : "Connect"}</button>
        </form>
        {error && <p className="error" role="alert">{error}</p>}
      </main>
    );
  }

  return (
    <main className="admin">
      <header className="admin-head">
        <h1>Mock admin panel</h1>
        <span className="muted">Tenant {tenant}</span>
        <button className="link" onClick={() => { sessionStorage.removeItem(KEY_STORE); setKey(""); setTenant(null); setActive(null); }}>Disconnect</button>
      </header>
      <nav className="tabs">
        <button className={tab === "tasks" ? "tab on" : "tab"} onClick={() => setTab("tasks")}>Closed tasks</button>
        <button className={tab === "viewer" ? "tab on" : "tab"} onClick={() => setTab("viewer")}>Profile viewer</button>
      </nav>
      {error && <p className="error" role="alert">{error}</p>}
      {toast && <p className="notice" role="status">{toast}</p>}

      {tab === "tasks" ? (
        <div className="split">
          <section>
            <label className="check">
              <input type="checkbox" checked={fresh} onChange={(e) => setFresh(e.target.checked)} /> Start a fresh session each time
            </label>
            <ul className="tasks">
              {TASKS.map((t) => (
                <li key={t.id} className={active?.task.id === t.id ? "task on" : "task"}>
                  <div>
                    <strong>{t.title}</strong>
                    <div className="muted">{t.type.replace(/_/g, " ")} · {t.end_user.display_name} · {t.agent.name} · {t.channel}</div>
                    {status[t.id] && <span className="tag">{status[t.id]}</span>}
                  </div>
                  <div className="actions">
                    <button className="primary" disabled={launching !== null} onClick={() => void launch(t)}>
                      {launching === t.id ? "Opening…" : "Debrief"}
                    </button>
                    <button className="link" onClick={() => { setViewerUser(t.end_user.id); setTab("viewer"); }}>Profile</button>
                  </div>
                </li>
              ))}
            </ul>
          </section>
          <section className="embed">
            {active ? (
              <>
                <p className="muted">
                  {active.session.created ? "New session" : "Resumed existing session"} <code>{active.session.session_id}</code>
                </p>
                {/* allow="microphone": an embedded page may only record if the host page grants it */}
                <iframe title="Debrief chat" src={active.session.chat_url} allow="microphone" />
              </>
            ) : (
              <p className="muted">Pick a task and press Debrief to open the chat here.</p>
            )}
          </section>
        </div>
      ) : (
        <Viewer api={api} initialUser={viewerUser} />
      )}
    </main>
  );
}
