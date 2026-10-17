import { useCallback, useEffect, useState } from "react";
import { ApiError, type AdminApi } from "../api";
import { confidenceLabel, humanize, valueToText } from "../chat/decisions";
import type { ContextOut, Fact, History, Profile } from "../types";

interface Loaded {
  profile: Profile;
  history: History;
  context: ContextOut;
}

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "");

export function Viewer({ api, initialUser }: { api: AdminApi; initialUser: string }) {
  const [userId, setUserId] = useState(initialUser);
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(
    async (id: string) => {
      if (!id.trim()) return;
      setLoading(true);
      setError(null);
      try {
        const [profile, history, context] = await Promise.all([api.profile(id), api.history(id), api.context(id)]);
        setData({ profile, history, context });
      } catch (e) {
        setData(null);
        setError(e instanceof ApiError && e.status === 404 ? "No profile for that end user yet." : (e as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [api],
  );

  useEffect(() => {
    setUserId(initialUser);
    if (initialUser) void load(initialUser);
  }, [initialUser, load]);

  const sessionTitle = (sid: string) => {
    const s = data?.history.sessions.find((x) => x.session_id === sid);
    return s ? `${s.task_title ?? s.task_type ?? "task"} (${s.task_id})` : sid;
  };
  const edited = (f: Fact) => f.provenance?.agent_edited === true;

  return (
    <section className="viewer">
      <form className="row" onSubmit={(e) => { e.preventDefault(); void load(userId); }}>
        <input aria-label="End user id" placeholder="End user id, e.g. eu_55021" value={userId} onChange={(e) => setUserId(e.target.value)} />
        <button className="primary" disabled={loading}>{loading ? "Loading…" : "Load profile"}</button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {data && (
        <>
          <h3>
            {data.profile.display_name || data.profile.end_user_id} <span className="muted">({data.profile.end_user_id})</span>
          </h3>
          <p className="muted">Version {data.profile.profile_version} · updated {fmt(data.profile.updated_at)}</p>

          <h4>Current facts</h4>
          {data.profile.facts.length === 0 ? <p className="muted">No facts yet.</p> : (
            <div className="scroll">
              <table>
                <thead><tr><th>Fact</th><th>Value</th><th>Confidence</th><th>Evidence</th><th>Source</th></tr></thead>
                <tbody>
                  {data.profile.facts.map((f) => (
                    <tr key={f.id}>
                      <td>{humanize(f.category)} · {humanize(f.key)}</td>
                      <td>{valueToText(f.value)}{edited(f) && <span className="tag">edited by agent</span>}</td>
                      <td><span className={`badge ${confidenceLabel(f.confidence).toLowerCase()}`}>{confidenceLabel(f.confidence)}</span> {f.confidence}</td>
                      <td className="evidence">{f.evidence ? `“${f.evidence}”` : ""}</td>
                      <td>{sessionTitle(f.source_session_id)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h4>History</h4>
          {data.history.history.map((h) => (
            <details key={`${h.category}.${h.key}`}>
              <summary>{humanize(h.category)} · {humanize(h.key)} <span className="muted">({h.versions.length} version{h.versions.length === 1 ? "" : "s"})</span></summary>
              <ul>
                {h.versions.map((v) => (
                  <li key={v.id} className={v.is_current ? "" : "old"}>
                    {valueToText(v.value)} {v.is_current ? <span className="tag">current</span> : <span className="tag">superseded</span>}
                    <span className="muted"> · {fmt(v.captured_at)} · {sessionTitle(v.source_session_id)}</span>
                  </li>
                ))}
              </ul>
            </details>
          ))}

          <h4>LLM-ready context</h4>
          <pre className="context">{data.context.context}</pre>
        </>
      )}
    </section>
  );
}
