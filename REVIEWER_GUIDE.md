# Reviewer guide: test the hosted app

About 10 minutes. You need three things from the submission email:

- `<APP_URL>`, the app address
- `<ACME_KEY>`, the API key for tenant `tn_acme`
- `<GLOBEX_KEY>`, the API key for tenant `tn_globex` (only used for the isolation check)

If the app has been idle, the first request can take up to a minute to wake up.

## 1. Check it is up (30 seconds)

1. Open `<APP_URL>/health`. Expect `{"status":"ok","db":"ok"}`.
2. Open `<APP_URL>/docs` (Swagger). Click **Authorize** and paste `<ACME_KEY>`.

## 2. Run the full loop on a refund task (3 minutes)

1. Open `<APP_URL>/admin`, paste `<ACME_KEY>` and press **Connect**. You see "Tenant tn_acme" and four closed tasks.
2. Press **Debrief** on "Refund for damaged order #44871". The chat opens on the right with an intro
   ("Quick debrief on Rahul M. ...") and one question at a time ("Question 1 of up to 7").
3. Answer the questions in turn (type and press Enter):
   - `he said never email him, only whatsapp, and not after 9pm`
   - press **Skip** on the next one
   - `his wife places most orders, he just handles complaints`
   - `he asked for store credit instead of refund next time`
4. After the last answer you see "Preparing your summary…", then **Here's what I'll save**. Each fact shows a confidence badge
   and **You said: "..."**, a quote from your own words.
5. Edit one value in its text box, press **Discard** on another fact, then press the **Save N facts** button. Expect **Saved ✓** in
   the chat and a "Profile updated" message in the panel.

If the AI is enabled, the questions are tailored to refunds and adapt to your answers. If it is not enabled you will see
built-in question templates and your own words offered as notes. Both are expected behaviour.

## 3. Look at the profile (1 minute)

Press **Profile** on that task (or open the **Profile viewer** tab). Expect the current facts with confidence, the evidence
quote and the source session, an "edited by agent" tag on the fact you edited, no trace of the one you discarded, and the
LLM-ready context block at the bottom.

## 4. Check idempotency and resume (30 seconds)

Go back to **Closed tasks** and press **Debrief** on the same refund task again. Expect "Resumed existing session" and the
finished conversation with **Saved ✓**, not a duplicate. Tick "Start a fresh session each time" to run it again from the start.

## 5. Try a different task type (2 minutes)

Press **Debrief** on "Set up a new business account" (Meera T.). The questions differ from the refund ones, leaning toward
products, communication style and constraints. Answer, review, save, then open her profile.

## 6. Contradict an old fact and read the history (1 minute)

Press **Debrief** on "Move delivery slot for order #45102" (Rahul again) and answer the contact-preference question with a change, for
example `he now wants SMS, mornings only, no whatsapp`. Save. In the Profile viewer for `eu_55021`, open **History** for the
changed fact: the old value is marked **superseded** with its original session, and the new one is **current**.

If the AI is off, both debriefs save your words as a note under the same key (one per question category), so the second
replaces the first the same way. If the AI is on, the key is whatever it chose (for example `preferred_channel`).

## 7. Voice (optional, 1 minute)

If the chat shows a **🎤 Record** button, voice is enabled. Press it, allow the microphone, speak for a few seconds and press
**Stop**. The transcript appears in the text box: edit it, then send. No button means voice is off on this deployment.
If the deployment runs the stub transcriber (`STT_PROVIDER=dev`), the transcript is a fixed sentence whatever you say. That
proves the upload, job and edit flow but not real speech recognition.

## 8. Check the API directly (2 minutes)

```bash
APP=<APP_URL>; KEY=<ACME_KEY>; G=<GLOBEX_KEY>

# merged profile, history and LLM-ready context (no LLM call on these reads)
curl -s -H "X-API-Key: $KEY" $APP/v1/profiles/eu_55021
curl -s -H "X-API-Key: $KEY" $APP/v1/profiles/eu_55021/history
curl -s -H "X-API-Key: $KEY" "$APP/v1/profiles/eu_55021/context?max_tokens=150"

# idempotent intake: prints 201, then 200 for the identical repeat
BODY='{"idempotency_key":"review-1","tenant_id":"tn_acme","agent":{"id":"ag_104","name":"Priya S."},"end_user":{"id":"eu_55021","display_name":"Rahul M."},"task":{"id":"review-1","type":"refund_dispute","title":"Review test"}}'
for i in 1 2; do curl -s -o /dev/null -w "%{http_code}\n" -X POST $APP/v1/sessions -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d "$BODY"; done

# isolation between tenants
curl -s -o /dev/null -w "%{http_code}\n" -H "X-API-Key: $G" $APP/v1/profiles/eu_55022   # 404: Meera exists only in tn_acme
curl -s -H "X-API-Key: $G" $APP/v1/profiles/eu_55021                                      # same id in tn_globex: a separate profile, no Acme facts
curl -s -o /dev/null -w "%{http_code}\n" -X POST $APP/v1/sessions -H "X-API-Key: $G" -H "Content-Type: application/json" -d "$BODY"   # 403: body says tn_acme
curl -s -o /dev/null -w "%{http_code}\n" $APP/v1/profiles/eu_55021                       # 401: no key
```

## What good looks like

| Check | Expected |
|---|---|
| Health and docs | `ok` and a Swagger page |
| Refund debrief | One question at a time, at most 7, skip and end work, no invented facts |
| Review screen | Every fact has an evidence quote from your words; edit and discard work |
| Saved profile | Facts appear in the viewer with confidence, evidence and source; edits are tagged |
| Repeat Debrief | Resumes the same session |
| Different task type | Different questions |
| Contradiction | Old value kept as history, new value current |
| API | 201 then 200 for repeats; other tenant gets 404 or an empty separate profile; wrong tenant in the body gets 403; no key gets 401 |

## If something looks wrong

| Symptom | Likely cause |
|---|---|
| First request is very slow | The free host was asleep. Wait up to a minute and retry |
| 401 on every call | Wrong or missing key. Send it in the `X-API-Key` header, no quotes |



Known limits are listed in the README under *Limitations and what was cut* and in `docs/design-note.pdf`.
