import { StrictMode, useMemo } from "react";
import { createRoot } from "react-dom/client";
import { chatApi } from "./api";
import { Admin } from "./admin/Admin";
import { Chat } from "./chat/Chat";
import { readChatLocation } from "./embed";
import "./styles.css";

function ChatPage() {
  const loc = useMemo(() => readChatLocation(window.location, sessionStorage, window.history), []);
  const api = useMemo(() => (loc?.token ? chatApi(loc.token) : null), [loc]);
  if (!loc || !api) {
    return (
      <main className="chat">
        <p className="error center" role="alert">This link is missing its access token. Please reopen the debrief from the admin panel.</p>
      </main>
    );
  }
  return <Chat sessionId={loc.sessionId} api={api} />;
}

function App() {
  const path = window.location.pathname;
  if (path.startsWith("/chat/")) return <ChatPage />;
  if (path === "/admin" || path === "/admin/") return <Admin />;
  return (
    <main className="admin">
      <h1>Profile Builder</h1>
      <p><a href="/admin">Mock admin panel</a> · <a href="/docs">API docs</a></p>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
