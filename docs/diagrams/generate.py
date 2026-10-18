"""Rebuild the two diagrams (SVG + PNG) in this folder.

    pip install matplotlib
    python docs/diagrams/generate.py

Everything is drawn from the coordinates below, so a diagram change is a small, reviewable text diff.
The facts shown here come from app/models.py, migrations/ and app/*.py; update both together.
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).parent
FONT = "DejaVu Sans"
plt.rcParams["font.family"] = FONT
plt.rcParams["svg.fonttype"] = "none"

INK, MUTED = "#1A202C", "#4A5568"
BLUE, GREEN, AMBER, RED = "#2B6CB0", "#2F855A", "#B7791F", "#C53030"


def canvas(w, h):
    fig = plt.figure(figsize=(w / 100, h / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)  # y grows downward, like a page
    ax.axis("off")
    return fig, ax


def frame(ax, x, y, w, h, label=None, fc="none", ec=MUTED, dashed=False, lw=1.3, sub=None):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=12", fc=fc, ec=ec, lw=lw,
                                ls=(0, (5, 4)) if dashed else "-", zorder=1))
    if label:
        ax.text(x + 14, y + 20, label, fontsize=10.5, fontweight="bold", color=INK, va="center", zorder=5)
    if sub:
        ax.text(x + 14, y + 38, sub, fontsize=8.5, color=MUTED, va="center", zorder=5)


def box(ax, x, y, w, h, title, body=(), fc="#FFFFFF", ec=MUTED, lw=1.3, dashed=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=9", fc=fc, ec=ec, lw=lw,
                                ls=(0, (5, 4)) if dashed else "-", zorder=3))
    lines = [(title, True)] + [(b, False) for b in body]
    step = 15.5
    top = y + h / 2 - step * (len(lines) - 1) / 2
    for i, (t, bold) in enumerate(lines):
        ax.text(x + w / 2, top + i * step, t, ha="center", va="center", zorder=5, color=INK,
                fontsize=9.6 if bold else 8.6, fontweight="bold" if bold else "normal")


def arrow(ax, p, q, color=MUTED, lw=1.3, dashed=False, rad=0.0, both=False):
    ax.annotate("", xy=q, xytext=p, zorder=4, arrowprops=dict(
        arrowstyle="<|-|>" if both else "-|>", color=color, lw=lw, ls=(0, (4, 3)) if dashed else "-",
        shrinkA=0, shrinkB=0, mutation_scale=13, connectionstyle=f"arc3,rad={rad}"))


def label(ax, x, y, text, color=MUTED, size=8.3, ha="center", bold=False):
    ax.text(x, y, text, ha=ha, va="center", fontsize=size, color=color, zorder=6, fontweight="bold" if bold else "normal",
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.95))


def badge(ax, x, y, n, color=BLUE):
    ax.text(x, y, str(n), ha="center", va="center", fontsize=9, fontweight="bold", color="white", zorder=8,
            bbox=dict(boxstyle="circle,pad=0.28", fc=color, ec="white", lw=1.2))


# =============================================================================================
# 1. Architecture and request flow
# =============================================================================================
def architecture():
    W, H = 1800, 1130
    fig, ax = canvas(W, H)
    ax.text(30, 34, "Profile Builder: architecture and debrief request flow", fontsize=15, fontweight="bold", color=INK)
    ax.text(30, 58, "Numbers 1 to 8 follow one debrief from the admin panel call to the saved profile and its read-back. "
                    "Dashed boxes are outside this system.", fontsize=9.5, color=MUTED)

    # --- admin panel (third party)
    frame(ax, 30, 100, 290, 400, "Third-party admin panel", dashed=True, sub="the mock panel at /admin plays this role")
    box(ax, 48, 160, 254, 100, "Admin panel server", ["holds the tenant API key", "calls the API when a task closes"], "#EDF2F7")
    box(ax, 48, 340, 254, 130, "Admin panel page", ["task list and profile viewer", "embeds the chat in an iframe", '<iframe allow="microphone">'], "#EDF2F7")

    # --- browser
    frame(ax, 405, 290, 340, 250, "Agent's browser")
    box(ax, 425, 335, 300, 185, "React chat  /chat/<session>",
        ["holds only the signed session token", "text answers, or record up to 60 s", "editable transcript",
         "review: keep / edit / discard", "then Save"], "#E6FFFA", ec="#2C7A7B")

    # --- service
    frame(ax, 830, 100, 640, 760, "Profile Builder service", fc="#F7FAFC", ec=BLUE, lw=1.8,
          sub="one FastAPI container (Docker on Render): serves the API and the built React app")
    box(ax, 860, 160, 270, 110, "api.py  (thin routes)", ["/v1/sessions  /debrief  /voice", "/extraction  /profiles"], "#EBF8FF")
    box(ax, 1170, 160, 270, 110, "deps.py  (auth)", ["API key: sha256 lookup, or", "signed token bound to ONE session", "result: ScopedRepo(tenant)"], "#EBF8FF")
    box(ax, 860, 370, 270, 130, "Rules: code owns flow control",
        ["planner, debrief state machine,", "interpreter, extraction check,", "voice job. Question cap,", "one follow-up, stale answer = 409"], "#EBF8FF")
    box(ax, 1170, 370, 270, 130, "Background tasks (in-process)",
        ["precompute_plan, run_extraction,", "run_transcription. State is saved", "in the database, so a restart", "re-runs the job, not loses it"], "#EBF8FF")
    box(ax, 860, 575, 270, 100, "services.apply_facts()", ["the ONE write path for facts", "conflict rule v1, one transaction"], "#FEFCBF", ec=AMBER, lw=1.8)
    box(ax, 1170, 575, 270, 100, "Provider interfaces", ["llm/: validate + 1 repair retry", "stt/: Transcriber", "prompts/*_v1.md (versioned files)"], "#EBF8FF")
    box(ax, 860, 735, 580, 95, "repo.py  ScopedRepo  (only code that queries tenant data)",
        ["built from the tenant resolved by auth; no method takes a tenant argument", "every query goes through _select(), which adds the tenant filter"],
        "#FEFCBF", ec=AMBER, lw=1.8)

    # --- data and providers
    box(ax, 1540, 700, 230, 150, "PostgreSQL (Neon)", ["12 tables", "composite foreign keys", "(tenant_id, id)", "audio kept until transcribed"], "#FED7D7", ec=RED, lw=1.8)
    frame(ax, 1540, 300, 230, 330, "External providers", dashed=True)
    box(ax, 1558, 350, 194, 120, "Gemini  (text)", ["question planning", "per-answer interpretation", "fact extraction"], "#FAF5FF", ec="#6B46C1")
    box(ax, 1558, 490, 194, 100, "Gemini  (audio input)", ["speech to text"], "#FAF5FF", ec="#6B46C1")

    box(ax, 30, 700, 310, 120, "Downstream AI systems", ["read the profile as JSON, as history,", "or as an LLM-ready text block", "(no LLM call on the read path)"], "#EDF2F7", dashed=True)

    # --- flow arrows
    arrow(ax, (302, 205), (860, 195), BLUE, 2.0)
    badge(ax, 590, 205, 1)
    label(ax, 590, 175, "POST /v1/sessions  (X-API-Key + idempotency_key)", BLUE)
    label(ax, 590, 233, "201 new / 200 repeat, returns session_id + chat_url", BLUE, 8)

    arrow(ax, (302, 395), (425, 395), BLUE, 2.0)
    badge(ax, 363, 372, 3)
    label(ax, 363, 417, "iframe src =\nchat_url", BLUE, 7.6)
    arrow(ax, (425, 470), (302, 470), MUTED, 1.2, dashed=True)
    label(ax, 363, 492, "postMessage:\nfacts saved", MUTED, 7.6)

    arrow(ax, (725, 400), (860, 245), BLUE, 2.0, rad=-0.05)
    badge(ax, 785, 330, 4)
    label(ax, 575, 585, "chat to api.py, header X-Session-Token\n4 debrief/start, /answer     5 /voice upload, poll\n7 /extraction, /extraction/confirm", BLUE, 7.8)

    arrow(ax, (995, 270), (995, 370), MUTED, 1.3)
    label(ax, 1040, 320, "ScopedRepo", MUTED, 7.8)
    arrow(ax, (1130, 215), (1170, 215), MUTED, 1.3)
    arrow(ax, (1130, 262), (1230, 370), BLUE, 1.6)
    badge(ax, 1186, 316, 2)
    label(ax, 1290, 322, "2 plan at intake\n6 extract when debrief ends\n5 transcribe voice", BLUE, 7.6, ha="left")
    arrow(ax, (1170, 435), (1130, 435), MUTED, 1.3)
    label(ax, 1150, 410, "runs", MUTED, 7.6)

    arrow(ax, (995, 500), (995, 575), BLUE, 2.0)
    badge(ax, 995, 538, 7)
    label(ax, 1075, 545, "only confirmed facts", BLUE, 7.8)
    arrow(ax, (1130, 480), (1230, 575), MUTED, 1.3)
    label(ax, 1215, 535, "LLM / STT calls", MUTED, 7.6)
    arrow(ax, (995, 675), (995, 735), MUTED, 1.3)

    arrow(ax, (1440, 610), (1558, 410), MUTED, 1.3, rad=0.0)
    label(ax, 1498, 470, "plan 8 s\nturn 4 s\nextract 20 s", MUTED, 7.4)
    arrow(ax, (1440, 640), (1558, 560), MUTED, 1.3)
    label(ax, 1498, 590, "30 s", MUTED, 7.4)
    arrow(ax, (1440, 782), (1540, 782), RED, 1.8, both=True)
    label(ax, 1490, 760, "SQL", RED, 7.8)

    arrow(ax, (340, 760), (860, 782), GREEN, 2.0)
    badge(ax, 600, 771, 8, GREEN)
    label(ax, 600, 742, "GET /v1/profiles/{id}   /context   /history   (X-API-Key)", GREEN, 8)

    # --- step list
    frame(ax, 30, 890, 1740, 215, "Request flow", fc="#FFFFFF")
    steps = [
        ("1", "Task closes. The admin panel's server posts the task context. Intake is idempotent on (tenant_id, idempotency_key) and scoped by tenant, agent and end user."),
        ("2", "In the background the planner asks the LLM for 3 to 7 task-aware questions. If the LLM is missing or fails, a fixed task-aware template plan is used."),
        ("3", "The admin page opens chat_url in an iframe. The chat keeps only the signed token, never the tenant API key."),
        ("4", "Each answer gets one small LLM call (clear or ambiguous, which later questions are covered). Code enforces the cap, skip, end and stale-answer checks."),
        ("5", "Voice: raw audio is uploaded, a transcription job is saved, the chat polls, the agent edits the transcript. Audio is deleted once transcribed."),
        ("6", "When the debrief ends, extraction runs once. Every fact must quote the agent's own words, and code verifies the quote."),
        ("7", "The agent keeps, edits or discards each fact. Confirm saves them through apply_facts in one transaction; older values stay as history."),
        ("8", "Downstream systems read the merged profile, the history or the context block with a tenant API key. No LLM is involved."),
    ]
    for i, (n, text) in enumerate(steps):
        col, row = divmod(i, 4)
        x, y = 55 + col * 865, 945 + row * 38
        badge(ax, x, y, n, GREEN if n == "8" else BLUE)
        import textwrap
        ax.text(x + 22, y, "\n".join(textwrap.wrap(text, 118)), fontsize=8.1, color=INK, va="center", zorder=6, linespacing=1.25)

    for ext in ("svg", "png"):
        fig.savefig(OUT / f"architecture.{ext}", dpi=130 if ext == "png" else None, facecolor="white")
    plt.close(fig)


# =============================================================================================
# 2. Data model
# =============================================================================================
ROW = 17.0
TABLES = {
    # name: (columns, notes)   column = (name, type/flags)
    "tenants": ([("id", "PK"), ("name", ""), ("created_at", "")], []),
    "end_users": ([("tenant_id", "PK FK"), ("id", "PK"), ("display_name", ""), ("profile_version", "int, +1 per change"),
                   ("updated_at", "")], ["the profile root: one per end user per tenant"]),
    "agents": ([("tenant_id", "PK FK"), ("id", "PK"), ("name", "")], []),
    "api_keys": ([("id", "PK"), ("tenant_id", "FK"), ("prefix", "UQ"), ("key_hash", "sha256 only"), ("revoked_at", ""),
                  ("created_at", "")], []),
    "sessions": ([("id", "PK"), ("tenant_id", "FK"), ("agent_id", "FK"), ("end_user_id", "FK"), ("idempotency_key", ""),
                  ("task_id", ""), ("task_context", "JSON"), ("locale", ""), ("status", "created, in_progress,"),
                  ("", "debrief_complete, profile_saved"), ("created_at", "")],
                 ["UQ (tenant_id, idempotency_key): idempotent intake", "UQ (tenant_id, id): target of composite FKs"]),
    "profile_facts": ([("id", "PK"), ("tenant_id", "FK"), ("end_user_id", "FK"), ("source_session_id", "FK"), ("category", ""),
                       ("key", ""), ("value", "JSON"), ("confidence", "float 0..1"), ("evidence", "agent's quote"),
                       ("is_current", "bool"), ("superseded_by", "soft ref"), ("superseded_at", ""), ("captured_at", ""),
                       ("provenance", "JSON: prompt, model, edit")],
                      ["partial UQ (tenant_id, end_user_id, category, key)", "WHERE is_current: one current row per key"]),
    "debriefs": ([("tenant_id", "PK FK"), ("session_id", "PK FK"), ("state", "active | complete"), ("end_reason", ""),
                  ("plan_source", "llm | fallback"), ("prompt_version", ""), ("model", ""), ("plan_latency_ms", ""),
                  ("plan_error", ""), ("completed_at", "")], ["row lock here serialises the turns of one session"]),
    "debrief_questions": ([("id", "PK"), ("tenant_id", "FK"), ("session_id", "FK"), ("seq", ""), ("category", ""), ("text", ""),
                           ("why", ""), ("kind", "planned | follow_up"), ("parent_id", "soft ref"),
                           ("status", "pending ... dropped")], ["UQ (tenant_id, session_id, seq)"]),
    "debrief_messages": ([("id", "PK"), ("tenant_id", "FK"), ("session_id", "FK"), ("seq", ""), ("role", "ai | agent"),
                          ("text", ""), ("question_id", "soft ref"), ("action", "answer | skip | end"),
                          ("meta", "JSON: interpretation, model")], ["UQ (tenant_id, session_id, seq)"]),
    "voice_notes": ([("id", "PK"), ("tenant_id", "FK"), ("session_id", "FK"), ("question_id", "soft ref"),
                     ("status", "queued | running | done | failed"), ("attempt", "max 3"), ("mime_type", "sniffed"),
                     ("size_bytes", ""), ("duration_ms", ""), ("audio", "BLOB, private, cleared after use"),
                     ("transcript", "draft for the agent"), ("error", ""), ("provider, model", ""),
                     ("created / started / finished / used_at", "")], ["never served by any endpoint"]),
    "extractions": ([("tenant_id", "PK FK"), ("session_id", "PK FK"), ("status", "running | ready | confirmed | failed"),
                     ("attempt", ""), ("source", "llm | fallback | none"), ("prompt_version", ""), ("model", ""),
                     ("error", ""), ("llm_input", "exact prompt sent"), ("llm_output", "JSON: model's reply"),
                     ("dropped", "JSON: rejected + reason"), ("started / finished / confirmed_at", "")],
                    ["answers: why was this fact proposed"]),
    "extracted_facts": ([("id", "PK"), ("tenant_id", "FK"), ("session_id", "FK"), ("category", ""), ("key", ""), ("value", "JSON"),
                         ("confidence", ""), ("evidence", "verified quote"), ("status", "proposed | saved | discarded"),
                         ("edited", "bool"), ("original_value", ""), ("saved_fact_id", "soft ref")], []),
}
HEADER = {"tenants": "#E2E8F0", "end_users": "#FEFCBF", "agents": "#E2E8F0", "api_keys": "#E2E8F0", "sessions": "#BEE3F8",
          "profile_facts": "#FEFCBF", "debriefs": "#C6F6D5", "debrief_questions": "#C6F6D5", "debrief_messages": "#C6F6D5",
          "voice_notes": "#C6F6D5", "extractions": "#E9D8FD", "extracted_facts": "#E9D8FD"}


def table_h(name):
    cols, notes = TABLES[name]
    return 30 + len(cols) * ROW + 10 + (len(notes) * 14 + 6 if notes else 0)


def table(ax, name, x, y, w=340):
    cols, notes = TABLES[name]
    h = table_h(name)
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=7", fc="white", ec=MUTED, lw=1.3, zorder=3))
    ax.add_patch(FancyBboxPatch((x, y), w, 26, boxstyle="round,pad=0,rounding_size=7", fc=HEADER[name], ec=MUTED, lw=1.3, zorder=4))
    ax.text(x + 12, y + 13, name, fontsize=10.5, fontweight="bold", color=INK, va="center", zorder=6)
    for i, (c, t) in enumerate(cols):
        cy = y + 38 + i * ROW
        is_t = c == "tenant_id"
        ax.text(x + 12, cy, c, fontsize=8.6, color=BLUE if is_t else INK, fontweight="bold" if ("PK" in t or is_t) else "normal",
                va="center", zorder=6, family="DejaVu Sans Mono")
        ax.text(x + w - 10, cy, t, fontsize=7.6, color=MUTED, va="center", ha="right", zorder=6)
    for j, n in enumerate(notes):
        ax.text(x + 12, y + 30 + len(cols) * ROW + 14 + j * 14, n, fontsize=7.6, color=AMBER, va="center", zorder=6, style="italic")
    return dict(x=x, y=y, w=w, h=h)


def datamodel():
    TW, GAP, TOP = 340, 95, 100
    cx = [40 + i * (TW + GAP) for i in range(4)]
    pos = {}

    def stack(col, names, y0, gap=38):
        y = y0
        for n in names:
            pos[n] = (cx[col], y)
            y += table_h(n) + gap
        return y

    stack(0, ["tenants", "end_users", "agents", "api_keys"], TOP)
    y_sessions = pos_y = TOP + table_h("profile_facts") + 85
    pos["profile_facts"] = (cx[1], TOP)
    pos["sessions"] = (cx[1], y_sessions)
    pos["debriefs"] = (cx[2], y_sessions + 20)
    pos["extractions"] = (cx[2], pos["debriefs"][1] + table_h("debriefs") + 85)
    bottom = stack(3, ["debrief_questions", "debrief_messages", "voice_notes", "extracted_facts"], TOP)
    guide_y = y_sessions + table_h("sessions") + 45
    H = int(max(bottom, pos["extractions"][1] + table_h("extractions"), guide_y + 300) + 20)
    W = cx[3] + TW + 40

    fig, ax = canvas(W, H)
    ax.text(30, 34, "Profile Builder: data model", fontsize=15, fontweight="bold", color=INK)
    ax.text(30, 58, "12 tables. The blue tenant_id column is in every table. Every foreign key between tenant data is composite "
                    "(tenant_id, id), so a row can never point across tenants.", fontsize=9.5, color=MUTED)

    t = {n: table(ax, n, *pos[n], w=TW) for n in pos}

    def row_y(n, col):
        cols = [c for c, _ in TABLES[n][0]]
        return t[n]["y"] + 38 + cols.index(col) * ROW

    def R(n, col): return (t[n]["x"] + t[n]["w"], row_y(n, col))
    def L(n, col): return (t[n]["x"], row_y(n, col))
    def bottom_(n): return (t[n]["x"] + t[n]["w"] / 2, t[n]["y"] + t[n]["h"])
    def top_(n): return (t[n]["x"] + t[n]["w"] / 2, t[n]["y"])

    # tenant bus down the left margin
    bus_x = 24
    last = t["api_keys"]["y"] + 45
    ax.plot([bus_x, bus_x], [t["tenants"]["y"] + 13, last], color=BLUE, lw=1.8, zorder=2)
    for n in ("tenants", "end_users", "agents", "api_keys"):
        yy = t[n]["y"] + 13 if n == "tenants" else row_y(n, "tenant_id")
        arrow(ax, (bus_x, yy), (t[n]["x"], yy), BLUE, 1.5) if n != "tenants" else ax.plot([bus_x, t[n]["x"]], [yy, yy], color=BLUE, lw=1.8, zorder=2)
    ax.text(10, (t["tenants"]["y"] + last) / 2, "tenants.id owns end_users, agents and api_keys", rotation=90, fontsize=7.6,
            color=BLUE, ha="center", va="center")

    def rel(p, q, card, name="", color=MUTED, rad=0.0, at=0.5, dx=0, dy=0):
        arrow(ax, p, q, color, 1.4, rad=rad)
        label(ax, p[0] + (q[0] - p[0]) * at + dx, p[1] + (q[1] - p[1]) * at + dy, f"{card}  {name}".strip(), color, 7.4)

    rel(R("end_users", "id"), L("profile_facts", "end_user_id"), "1 : N", "", at=0.5, dy=-12)
    rel(R("end_users", "id"), L("sessions", "end_user_id"), "1 : N", "", at=0.62, dy=0)
    rel(R("agents", "id"), L("sessions", "agent_id"), "1 : N", "", at=0.5, dy=0)
    rel(bottom_("profile_facts"), top_("sessions"), "N : 1", "source_session_id", at=0.5)
    rel(R("sessions", "id"), L("debriefs", "session_id"), "1 : 1", "", at=0.5, dy=-12)
    rel(R("debriefs", "session_id"), L("debrief_questions", "session_id"), "1 : N", "", at=0.55)
    rel(R("debriefs", "session_id"), L("debrief_messages", "session_id"), "1 : N", "", at=0.55)
    rel(R("debriefs", "session_id"), L("voice_notes", "session_id"), "1 : N", "", at=0.55)
    rel(bottom_("debriefs"), top_("extractions"), "1 : 1", "", at=0.5)
    rel(R("extractions", "session_id"), L("extracted_facts", "session_id"), "1 : N", "", at=0.5)

    # reading guide
    frame(ax, cx[1], guide_y, TW + GAP - 30, 300, "How to read this", fc="#F7FAFC", ec=MUTED)
    notes = [
        ("Facts", "profile_facts is append-only. A new value flips the old row (is_current false,\nsuperseded_by set) and inserts the new one, in one transaction."),
        ("Merged view and history", "Merged view = rows where is_current is true. History = all rows."),
        ("Soft references", "superseded_by, question_id, parent_id and saved_fact_id are plain\nstrings, not foreign keys."),
        ("Audit", "profile_facts.provenance, extractions.llm_input / llm_output / dropped and\ndebrief_messages.meta record why a fact exists."),
        ("Colours", "yellow = profile data, blue = intake, green = debrief, purple = extraction."),
    ]
    import textwrap
    yy = guide_y + 44
    for head, body in notes:
        body = "\n".join(textwrap.wrap(" ".join(body.split()), 62))
        ax.text(cx[1] + 16, yy, head, fontsize=8.8, fontweight="bold", color=INK, va="top", zorder=6)
        ax.text(cx[1] + 16, yy + 14, body, fontsize=8, color=MUTED, va="top", zorder=6, linespacing=1.3)
        yy += 14 + 13 * (body.count("\n") + 1) + 14

    for ext in ("svg", "png"):
        fig.savefig(OUT / f"data-model.{ext}", dpi=130 if ext == "png" else None, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    architecture()
    datamodel()
    print("wrote architecture.(svg|png) and data-model.(svg|png) in", OUT)
