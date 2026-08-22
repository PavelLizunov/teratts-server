# DSH voice browser acceptance

Run this only after Linux Tailnet HTTPS and authenticated `POST /tts` pass, the DSH Host settings point at that HTTPS URL, and `TERATTS_TOKEN` is configured. Restart DSH from an external SSH/console channel after closing the active DSH session; never signal the process from a request it serves.

## External activation gate

1. From an external shell, verify no important DSH agent/job is running.
2. Record the current DSH PID and the Web profile package version.
3. Restart only `dsh-web.service` through its supervisor.
4. Wait for a new PID and HTTP 200 on `127.0.0.1:3080`.
5. Confirm the boot graph serves `dsh-client-ui-teratts` `0.2.0` and the client bundle contains strict Remote codecs, DSH icons and no endpoint/credential.
6. Open a new authenticated browser session and refresh once.

## Browser observations

Use one finalized assistant message containing normal Markdown, inline code, a fenced code block, a link and Unicode Russian text.

- [ ] One voice action appears in `conversation.chat.assistant-actions`, after feedback/copy and before branch according to slot order.
- [ ] Idle glyph is the local 16px `currentColor` speaker SVG; no emoji appears.
- [ ] Button is keyboard reachable and has accessible name `Read response aloud`.
- [ ] Click changes to `IconLoadingOutline16`, exposes `aria-busy=true`, and sends one Host Remote call.
- [ ] Successful synthesis changes to `IconStopFill16` and audio begins.
- [ ] Second click stops audio, aborts pending work when applicable, unloads media and returns to idle.
- [ ] Replay works after natural completion and after manual stop.
- [ ] Starting another message stops the previous message: only one browser playback exists.
- [ ] Fenced code becomes the short code-block marker; Markdown syntax and HTML are not spoken verbatim.
- [ ] HTTP/config/audio failures show one Toast announcement, not duplicate alerts; user cancellation shows no error.
- [ ] Browser console has no Remote mount, codec, React lifecycle, mixed-content, CORS, media or object-URL errors.
- [ ] Removing the action from the DOM during loading/playing cancels/stops and revokes resources.

## Evidence capture

Record: DSH PID/version, served plugin URL/revision, screenshot of idle/loading/playing states, console screenshot or export, network/RPC result without credentials, and whether audio was audibly confirmed. Mark unobserved items `Not verified`; bundle/backend evidence cannot substitute for browser observations.
