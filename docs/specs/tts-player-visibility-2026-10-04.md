# Stable DSH speech player

## Outcome and authorization
User requests fixing the DSH speech player that jumps right and disappears when interacting with messages. Implement within the existing installable TeraTTS plugin; no DSH core changes or service restart.

## Inspected cause and scope
- `dsh-plugin/lib/client.js`: the fixed player is a descendant of the message action row. DSH rc.2 action CSS applies opacity:0 to that row when an older answer is not hovered/focused. Fixed positioning does not escape ancestor opacity or containment.
- Desktop plugin CSS explicitly moves the player to right:24px.
- Active profile web-015 installs a private telemetry variant (0.9.3-private-telemetry.1). Preserve its extra telemetry code; never replace it wholesale with the public repository version.
- Scope: client portal/positioning, regression tests, factual README update and this record. Audio buffering, RPC, leases, pause/seek/rate and action/session cleanup remain unchanged.

## Implementation
Use the existing runtime `react-dom` createPortal API to place the active player in document.body, outside message hover/scroll containers. Keep it horizontally centered with viewport gutters. Measure the current conversation composer to preserve clearance after escaping inherited composer CSS variables. Stop player-region click propagation without preventing native slider operation. Preserve original action lifecycle and explicit stop behavior.

## Verification
- Red/green regression for portal parent, centered CSS, composer clearance and click isolation.
- Existing plugin tests with actual active profile dependencies.
- Real Chromium fixture at desktop/mobile sizes using production client code and DSH hover/containment CSS, covering message clicks, focus loss, scrolling and controls.
- Review exact diff; commit only task-owned files and push a dedicated GitHub task branch.
- Verify non-disruptive consumer activation only if supported; otherwise report it as pending rather than restarting.

## Unknowns and boundaries
Shared browser cannot currently reach the live GUI (loopback refused; Tailscale HTTP proxy connection failed). No dev:web watcher is running. Confirm how the installed client bundle is served before any activation claim. Message-action unmount/session navigation retains existing stop behavior; this patch does not add cross-session playback persistence.

## Follow-up: input overlap (user report)
- Prior acceptance was insufficient: the fixture invented `data-conversation-composer-seat`, which does not exist in the actual rc.2 UI. Actual source uses `[data-composer-seat]` with `[data-conversation-region="composer"]`. The incorrect selector silently used a 92px fallback and could cover the composer.
- Authorized correction: bind to the actual composer seat inside the owning session, maintain 12px clearance as its height changes. Preserve portal isolation, playback behavior, private telemetry and no-restart activation.
- Verify with actual rc.2 attribute names, a composer taller than the fallback, scroll/growth and all existing playback checks. Add an assertion that the fixture selector is present in runtime source to avoid another invented DOM contract. Check installed private bundle as well as repository bundle. Full live authenticated tab remains unavailable.
- Follow-up verification: red unit lookup and Chromium clearance reproduced the prior failure. Green unit tests and 129 behavioral tests pass (same pre-existing peer-version assertion excluded). Real Chromium checks pass for repository AND installed private bundle at 1280px/390px/320px with 100px and 180px composers, typing during playback and growth clearance.
- Installed follow-up is a one-selector patch with telemetry preserved; rollback snapshot `/var/lib/dsh/.dsh/task-artifacts/tts-player-composer-clearance-20261004/client-before.js`. Existing GUI serves exact installed bytes at client revision `417c443c0f86`, replacing `3acf9c21d3ba`. DSH process/service PIDs unchanged. No restart or profile change.
- Follow-up status: corrected, activated and pushed to the dedicated task branch (implementation `692a67a`). Final repository and installed Chromium runs also verify actual pointer clicks into the textarea before and after composer growth. The previous fixture-only no-overlap claim is superseded by this user report and corrected DOM-contract checks. Incident INC-1391 recorded and locally committed in Trajectory; that repository has no configured remote, so its GitHub backup is unavailable.

## Status
Implementation, non-disruptive client activation and verification complete. Task branch `fix/tts-player-visibility-20261004` pushed to origin; implementation commit `9a27706`. Full authenticated user-tab/audio acceptance remains unobserved as documented below.

## Evidence so far
- Red regression: original inline player and desktop-right CSS failed new placement checks.
- Portal/centering/click-isolation and composer observer lifecycle tests pass (4/4).
- Complete behavioral suite: 129 passing tests with the pre-existing exact peer-version assertion explicitly excluded. Unfiltered suite: 129 pass, 1 fails because runtime is rc.2 while the existing test pins rc.1. Do not broaden this UI fix into dependency migration.
- No dev:web watcher is running. This package already ships its executable client.js; the active rc.2 `/plugins/events` graph and client artifact were verified over the existing loopback service. Source inspection confirms dsh-client-hmr watches graph client artifacts and rebuilds the client-module revision, so a narrow installed-client patch needs no Host reload or service restart.
- Live shared-UI control socket is absent because the shared-ui plugin is currently disabled; do not enable it or manufacture authentication. Full authenticated live-page inspection remains unavailable.
- Real Chromium PASS for public repository bundle AND actual installed private telemetry bundle at 1280px, 390px and 320px. Assertions cover hidden action-row opacity, body portal, centering/gutters, message click, scroll, composer growth, pause/resume, seek, speed, explicit stop and owning-action unmount.
- Installed patch applied atomically using task-owned source hunks only; private telemetry and extra slots preserved. Rollback copy: `/var/lib/dsh/.dsh/task-artifacts/tts-player-visibility-20261004/client-before.js`.
- Existing GUI client graph changed from `7ada6848a529` to `3acf9c21d3ba`; fetching its exact revision URL returns the patched installed bytes with telemetry intact. DSH process PID 2359533 and service PID 2359515 unchanged, with original 12:11 launch time. No Host restart or profile config change.
- Limits: browser fixture uses fake audio and RPC to verify UI/lifecycle, not actual audible synthesis or the user's already-open authenticated tab. Existing clients receive the verified artifact through native HMR; if a stale tab did not consume the event, a normal page reload loads the verified revision.
