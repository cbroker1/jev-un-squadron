# Project state

## Current checkpoint - 2026-09-19 evening, attacking play and terrain (Claude session)

**Start with [CLAUDE_HANDOFF.md](CLAUDE_HANDOFF.md).** Evidence: [object-table report](../../evidence/hazard_observation/OBJECT_TYPES_2026-09-19.md). Level 1 is **not finished**; the segment ends on its frame budget. About 5,700 paid attempts this session (free tier, approved).

- **The controller plays to attack.** Decisions every 6 game frames with pause-and-step; measured shot geometry (shots travel right at 11 px/frame at the aircraft's Y, vertical tolerance about 10 px); aim error toward the nearest reachable target; targets ahead and behind; a 30-frame whole-field forecast over a 4x8 grid; squeeze numbers for both sides; and turrets and both power-up types as targets.
- **Best runs over 1800 frames:** 42, 39 and 36 kills with 3 hits each and 2-3 power-ups, all reaching the end of the window. Passive configurations managed 10 kills; a stationary firing aircraft gets 5 and dies at 21205.
- **Position turned out to be the lever.** Every earlier number described the present, so the greedy choice crept toward targets and got pinched. Once options carried what a position would be worth over the next 30 frames, kills roughly doubled and the aircraft settled on the left where targets come to it.
- **Terrain is the main remaining damage source** and is not in the object table. The level scroll position is WRAM `0x007B` (exported as `scroll_x`), so `build_terrain_map.py` builds a measured map keyed by level column: lowest altitude flown safely, and altitudes where untracked hits happened. Rebuild it after runs.
- **56 offline tests pass.** New tools: `survey_objects.py`, `scripts\render_object_types.ps1`, `build_terrain_map.py`, `build_terrain_profile.py` (does not work; colour cannot separate ground from background art), `probe_hazards.py --modes replay`.
- Slot 1 was overwritten once by a stray save state and restored from BizHawk's `.bak`; runners now refuse to start unless it hashes `c1ea750e...`.

**Single next experiment:** repeat `launchers\run_jev_segment.bat` several times for a distribution, rebuilding `terrain_map.json` between batches, and check whether terrain hits keep falling. Then extend past frame 22463 toward the boss, surveying new object routines from a replay capture first.

## Earlier checkpoint - 2026-09-19 evening, object table, power-ups and tanks (Claude session, historical)

**Start with [CLAUDE_HANDOFF.md](CLAUDE_HANDOFF.md).** Latest evidence: [object-table report](../../evidence/hazard_observation/OBJECT_TYPES_2026-09-19.md). Level 1 is **not solved**. Total paid attempts: **170**.

- **The object table is mapped.** WRAM `0x1000..0x1FC0` holds 0x40-byte records; bytes 1..3 are a routine address that identifies the type.
  - Helicopters `$02:B04A`; enemy bullets `$04:F97F` (blue **or orange**); the power-up `$04:FABA` (slot `0x1400`, collected on contact at about 18 px); ground tanks `$02:9274` and `$02:90F0..9203`. Each was checked on screenshots in two recordings.
  - Candidate hit marker: `$04:F8A1` in slot `0x1040`.
- **The controller uses the whole table.** `TableTracker` replaces the fixed slot lists, objects up to 32 px off-screen count, and tanks are collision bodies.
  - Each option leads with its closest tracked threat, then the power-up approach and the tank firing line, and names the edge it ends on.
  - A re-plan trigger pauses and asks again when a threat closes in mid-action.
- **Live results, 900 frames, one run each:**
  - The earlier fixed-slot run got 1 hit.
  - The object-table run killed 3 tanks, but 1 hit came from descending onto a tank.
  - Tanks-as-bodies: 1 hit at the right edge, no tanks killed.
  - **`combat-20260919-170320-486fe9-live` (closest-threat wording): 0 hit markers through 21563, power-up collected, 0 tanks.**
- **Tools:**
  - `probe_hazards.py --modes replay --replay-run <run>` for exact replay captures.
  - `survey_objects.py` and `scripts\render_object_types.ps1`.
  - `analyze_segment.py` now reports candidate hits, pickups and tank kills.
  - `hazard_snapshots.lua` now reports its own errors (after a console-only error that Carl caught).
- `launchers\run_jev_segment.bat` now runs 900 frames with a cap of 45. **52 offline tests pass.**

- **Second pass (generalizing):** stage-specific prompt claims replaced by `object_entries_counted_this_run` (counted live); the re-plan trigger is relative (threat appears, or gap halves) with no tuned pixel threshold; the planned code-computed "safe tank line" was dropped as overfitting.
  - A shadowed `key` variable broke live requests for about 4 attempts; fixed, with the error location now logged and a test that every stepped request carries the key.
  - **Three more runs: 0 hit markers each, full window; power-up collected in 1 of 3; no tanks.** Zero hits now holds across four runs. Total paid attempts: **279**.

- **Attacking play (evening):** decisions every 6 game frames, measured shot geometry (shots travel right at 11 px/frame at the aircraft's Y, vertical tolerance about 10 px), aim-error guidance, turrets as high-value targets, targets-behind gradient, threat directions, retreat room as a waiting preference, and the screen-clearing power-up `$04:FAD9` (touching it destroyed every live target in both observed pickups).
  - Best runs: 21-24 kills with **0 hits** over the 900-frame window, both turrets destroyed and the weapon power-up collected.
  - Collisions are the main damage source; every recorded one happened at a reference gap of 9-22 px, which the request now states.
  - Slot 1 was overwritten by a stray save at 18:13 and restored from BizHawk's `.bak`; runners now refuse to start against a changed baseline and abort before paid requests if Lua attaches late.

**Single next experiment:** repeat `launchers\run_jev_segment.bat` 2-3 times to see whether 0 hits holds. Then add a code-computed safe tank line, for example "level with a tank at least N px ahead", so tank kills return without collisions. Then extend the window past frame 21563.

## Earlier checkpoint - 2026-09-19, pause-and-step (Claude session, historical)

**Start with [CLAUDE_HANDOFF.md](CLAUDE_HANDOFF.md).** Latest evidence: [pause-and-step report](../../evidence/hazard_observation/PAUSE_AND_STEP_2026-09-19.md). This supersedes the aircraft-slot checkpoint below. Level 1 is **not solved**. Carl approved paid requests (free tier). Total paid attempts so far: **68** (3 earlier, 65 this session).

- **Pause-and-step is implemented and verified.**
  - Commands may carry `freeze_at_frame`. Lua pauses the emulator on that frame (`client.pause()`, frozen heartbeat, 5-second watchdog), and the choice applies from the observed frame.
  - `run_segment.py --stepped` enables it; the zero-API dry run applied 900 ms mock replies with 0 game frames elapsed.
  - `bridge.py`/D/L never sends a freeze and still passes its check.
- **The runner's neutral gun-off prelude was a handicap.** The player took a hit at about frame 20583 (DANGER from 20623), and the helicopter formation survived. Every earlier segment gave Jev an already-damaged aircraft. `--prelude-fire` keeps the gun on; with it, the formation is shot down before 20733.
- **Live results, one run each:**
  - Continuous, gun-off (`161552-2be94c`): 4 choices. Control was lost at about 20732, when helicopter `0x1800` entered its hit header 20 px away, before Up (observed 20723) applied at 20733. The guard stopped the run at 20778.
  - Stepped, gun-off (`162830-7da253`): all 5 choices applied from their observed frames. Up at 20723 took the aircraft to (16,48), `0x1800` was never hit, and the run ended normally.
  - Stepped + firing prelude (`162721-f5cd5f`): 10 choices over 20663-21083, a normal end, and all checks passed. The HUD gauge stayed full, while the matching stationary firing baseline (`162523-593790`) took a hit about 20963-21003 and showed DANGER at 21083. Score and money matched.
- **Caveats:** HUD-only damage reading (no health RAM mapping); single runs; a stationary baseline is a weak comparison; Jev often uses the X=16/Y=48 corners; ground fire, terrain and other hazards are untracked; the late-reply drain branch was still not exercised.
- `launchers\run_jev_segment.bat` now runs the stepped + firing-prelude configuration (max 14 requests, 420 frames).
- **47 offline tests pass.**

- **Repeatability:** two more 420-frame stepped runs.
  - `163441-2b78da` repeated the original 10 choices exactly.
  - `163515-8a9165` differed only in the last two.
  - The gauge stayed full through 21083 in all three runs.
- **Longer window:** the 900-frame stepped run `163645-fc9efa` made 26 choices to frame **21563**, with every move exact (never lost control).
  - Its first HUD hit came at about **21383**, with DANGER from 21463.
  - The matching stationary firing baseline `163609-585d4f` was hit at about 20983, lost control at 21084, and the guard stopped it at 21205.
- **Next failure cause (visual):** an **untracked orange-ball projectile family**, probably from the large ground turret. The ball was on the jet at 21383 after Jev moved down from the (239,48) corner; the only tracked bullet was about 50 px away.

**Single next experiment (zero API):** find the orange-ball projectile slots with the same method used for the aircraft:
1. A full-WRAM plus screenshot capture over frames about 21280-21420 that reproduces the run's inputs or a similar position.
2. Orange-fragment ranking.
3. A per-slot gate and lifetime check in two recordings.

Then add the slots and rerun the 900-frame stepped segment (`--max-calls 30 --frames 900`). Keep health/death RAM unknown until a separate mapping experiment exists.

## Earlier checkpoint - 2026-09-19, aircraft slots (Claude session, historical)

**Start with [CLAUDE_HANDOFF.md](CLAUDE_HANDOFF.md).** Evidence: [aircraft slot validation](../../evidence/hazard_observation/AIRCRAFT_SLOTS_2026-09-19.md). Superseded by the pause-and-step checkpoint above; its "single next experiment" was run (see above). Level 1 is **still not solved**. This step made **no paid requests**; total paid attempts remain 3.

- The orange-aircraft blind spot is closed for four explicitly checked slots: `0x17C0`, `0x1800`, `0x1840` and `0x1880`. They use signed 16.8 X/Y at `+0x10/+0x13` and the existing aircraft gate. Each passed its own checks in both saved recordings:
  - The reference follows its helicopter over wide X/Y ranges.
  - It disappears when the reference passes X=256 or the gate turns off (`D0` after a hit, `00` after exit).
  - A new occupant starts a new track generation without carried velocity.
  - The old ungated "phantoms" were the 24-bit X wrapping (271 -> 15).
- The controller now observes 7 aircraft + 6 projectile slots. `ENEMY_BASES` in `brain/observations.py` must equal `enemy_bases` in `lua/main.lua`, and a test enforces it. Request coverage text is computed from those lists.
- Slots are reused by green helicopters and by a ground-level object whose byte 0 is also `C8`. The gate is not a colour/type classifier. `0x1700`/`0x1740` (green helicopters, replay-only evidence) are not adopted.
- Offline controller check at the live decision frames, using replay RAM that reproduces the live input prefix: the requests Jev actually saw had 2 aircraft tracks; the same frames now yield 5-6. This says nothing about Jev's choices or outcomes.
  - At 20693, where Jev chose Left, Left's aircraft-reference gap would be 32 px against Up's 55 px; the original request showed 77 px for every action except Right.
  - At 20723, Left/Hold would be 6 px and Up 26 px; the original request showed about 160 px.
- Near the live guard: in the replay, `0x1800`'s helicopter switched to the `D0` header at frame 20731, 11 px right of and 15 px below the player reference, one frame before the guard fired (X=15). This is consistent with a collision, but it is not accepted as collision/damage/death semantics. The guard and bounds are unchanged.
- Zero-API runtime checks:
  - Dry runs `runs/combat-20260919-135757-4bbef0-dry` (4 slots) and `runs/combat-20260919-140241-240bde-dry` (7 slots) passed every runner check.
  - Exported slot bytes equal the offline captures until the inputs diverge, and the overlay sheets in the run folders were inspected.
- The first regular-bridge dry-run check (`bridge-check-20260919-140406-33db6b`) exposed a latent `bridge.py` crash on a torn state read after the final acknowledgement.
  - Fixed, with a regression test.
  - The D/L dry-run and cardinal-calibration checks pass afterwards (`140501-03201e`, `140507-3b1b07`).
  - `launchers\launch.bat` is otherwise unchanged.
- **45 offline tests pass.** New or extended tools: `analyze_aircraft_slot.py`, `scripts\render_run_track.ps1`, `replay_brain.py --combat`, and single-base labels in `scripts\render_projectile_evidence.ps1`.
- Still unknown: health/damage/death, collision geometry, terrain, ground objects, other hazard families, kills/pickups and level clear. The late-reply drain branch in `play_segment.py` is still not exercised by a real in-flight request.

- New zero-API baseline `runs/combat-20260919-140905-903ba4-baseline` uses the 7-slot export.
  - It reproduces the old baseline exactly: player positions at all 688 shared frames, the previously exported slot bytes, and 34/34 screenshots.
  - Use it for `analyze_segment.py --baseline`. The old baseline's observation packets can never match a 7-slot run.

**Single next experiment (paid, only with Carl's explicit go-ahead):** one bounded live combat segment, `launchers\run_jev_segment.bat` (at most 5 Jev requests, same save, 50% speed), with the 7-aircraft-slot observation. Compare it against the new baseline and record:
- which tracks each request contained;
- the choices and the actual inputs applied;
- where and why the run stops.

It passes as an experiment if the provenance is complete. Surviving the formation or clearing the level is not the criterion, and must not be claimed from one run.

## Earlier checkpoint - 2026-09-19, bounded combat run (historical)

The bounded-combat checkpoint, superseded by the section above. We are **not ready to complete level 1**.

- Verified before this step: player references WRAM `0x1011/0x1014`; cardinal movement; pulsed-Y gunfire; automated launch/save/load/run/close; core input readback; reload and lease-expiry safety. Original `launchers\launch.bat` D/L workflow and local key arrangement remain unchanged. Its live prompt is still target-70 calibration, separate from the new combat controller.
- Added bounded experimental combat: `brain/combat.py`, `play_segment.py`, `run_segment.py`, `launchers\run_jev_segment.bat`, `launchers\stop_segment.bat`, `analyze_segment.py`. Code calculates reference-point trajectory summaries; Jev selects one typed movement. No confidence-based or low-health movement override. Coverage is explicitly incomplete.
- `main.lua` exports six checked projectile slots and three checked aircraft slots (`0x16C0`, `0x1780`, `0x1940`). Aircraft coordinates have frame-matched visual evidence, including a turning track and an independent same-save Left comparison. These are checked occurrences, not complete hazard/type detection.
- Final zero-API dry run `runs/combat-20260919-131829-5ea5e4-dry` applied all five mock choices and passed input/lease/STOP/speed/save/shutdown checks. Slow-mock run `131603-d08866-dry` rejected a 28-game-frame-old reply without injecting its movement. Firing-only baseline `131730-aec2da-baseline` ran to game frame 20873 and stopped normally. All used explicit 50% speed.
- **Actual threat-informed Jev run exists:** `runs/combat-20260919-131922-c4e603-live`. Three API attempts, two returned/applied Left choices. First choice: observe frame 20663 -> response 20678 -> core input begins 20679 -> X 96 to 36 by frame 20703, Y stays 112. Inspected screenshots and core readback support movement; this is no longer only target calibration. It did **not** pass the intended five-choice segment.
- That run stopped at frame 20732 when player X became 15, outside the tested controllable range 16..239. A zero-API replay `evidence/hazard_observation/probe_20260919-132216-1dd64b_pulse8` reproduced the same transition and captured a later explosion sequence. Do not widen the control bounds to suppress the guard or turn this into a health/death RAM mapping.
- Timing: request intervals 30 game frames; observed response latencies 473.55 and 269.38 ms; observation-to-input 16 and 10 game frames, including one bridge frame. First action lasted 24 frames before the next Jev command superseded it, second 30. There is no extra 30-frame sleep after API completion. No evidence yet that pause-and-step is necessary; latency is still material and trajectory summaries do not compensate for it.
- The current blind spot is orange aircraft near the player. Offline visual/RAM ranking found `0x17D1/0x17D4`, `0x1811/0x1814`, `0x1851/0x1854`, `0x1891/0x1894`. These remain **candidates and are not fed to Jev**. `0x1851/0x1854` follows an orange aircraft through multiple positions in neutral and Left/firing captures; later inactive values produce phantom markers. Activity/lifetime gating must be checked before use.
- Health/danger/recovery/death mappings, collision sizes, terrain, other hazard families, kills/pickups and level-clear detection remain unknown. A matched-prefix comparison (494 states and 24 identical screenshots before first Jev input) establishes a comparable start, not improvement over baseline.
- **41 offline unit tests pass.** A post-live fix now records pending results discarded after STOP; the actual third live response was not retained by the older tested code, so its choice/latency are unknown. The new late-drain logging branch is not yet verified with an in-flight real HTTP request and must not be credited retroactively.
- Handoff: no emulator or Python experiment process remains; both active-run files report stopped; owned emulators exited normally and slot 1 hashes are unchanged. No new paid requests during handoff. Total paid attempts in this development step: **3** (budget was 5, not spent merely to exhaust it). No root Git repository was available, so do not infer authorship/today's changes from file timestamps.

**Next experiment at that time (completed and passed; see the current checkpoint):** validate the orange-aircraft candidate `0x1851/0x1854` through active, disappearance and reused-slot states using the existing neutral and Left/firing full-RAM captures. Test the observed byte gate at candidate base `0x1840` against raw screenshots; confirm fractional/signed coordinates before adopting them. Pass: the gated marker follows the same aircraft in both recordings and disappears when that occurrence ends, with no phantom or cross-lifetime velocity. Do not add all similarly spaced addresses by assumption. Exact paths/commands and acceptance criteria are in the Claude handoff.

## Earlier checkpoint - before bounded combat (historical)

Evidence at that earlier point: [brain adoption report](../../evidence/hazard_observation/BRAIN_ADOPTION_2026-09-19.md). All tests in this earlier checkpoint used zero Jev requests; the later three paid attempts are documented above.

- Player reference: WRAM `0x1011/0x1014`, X increases right, Y increases down. Four independent held-direction tests establish X 16..239 and Y 48..191 for this pilot/save; measured cardinal travel averages 2.5 pixels per game frame. These are reference-point limits, not collision boxes. `0x002C` is rejected as persistent Y.
- Gun: visible Y-pulse shots, independent of movement. Capture tests use one frame on/five off; the unchanged regular bridge uses four on/four off. Both have inspected visual evidence. Held-button firing is not assumed.
- Projectile family: six explicit slots have frame-matched visual coordinate evidence. The `0x1AC0` slot has three observed lifetimes; its negative X and another slot's negative Y continue without wrapping onto the opposite edge. The exact-header gate is a limited research profile, NOT a complete active-object/type decoder. Health, recovery, death, enemy bodies, terrain and collision geometry remain unknown.
- Implemented the agreed decomposition: `brain/observations.py` (decoding/lifetimes), `brain/digest.py` (measured geometry), `brain/questions.py` (typed Choice descriptions), `replay_brain.py` (no-network previews). The new live-state **offline** reader is `observe_brain.py`; `main.lua` exports only the six checked slots. Model confidence is not used as a safety score in this layer.
- A real 20-frame Left intervention matched the player and projectile predictions at all 11 captured positions, with zero coordinate error: `probe_20260919-120911-629b88_neutral/forecast_validation.json`. This validates that short trajectory, not collision avoidance or survival.
- Passive bridge preview `runs/bridge-check-20260919-122547-fb47e1`: 901 consecutive states, 31 previews at exactly 30-game-frame intervals, no movement/fire commands, 205 shared coordinate snapshots and 21 screenshots identical to independent capture. Explicit 50% speed; normal emulator exit. `launchers\run_brain_preview.bat` repeats this bounded offline check without manual Lua clicks.
- The actual new batch launcher was also executed successfully: `runs/bridge-check-20260919-124301-4ba70e` repeated those 901 observations, 205 coordinate matches and 21 identical screenshots, with zero API calls and normal shutdown. No emulator was left running.
- Latest regular-bridge regression runs: cardinal `122719-3657b3`, dry-run `122841-fc42ab`, real save reload `122848-f3a7b7`, simulated offline-child crash `122911-e550f9` (full paths in the report). Exact 20/30-frame actions, one-frame observe-to-apply delay in calibration, no stale replay after reload or expiry. All 30 offline unit tests pass.
- `launchers\launch.bat` still offers D/L with the five-second countdown; the reusable local credential file is unchanged. The normal live prompt remains explicitly **fixed-target-70 calibration**. No Jev request has consumed the new projectile summaries, and no new threat-aware Jev gameplay is claimed.

Single next experiment: validate one enemy-aircraft X/Y track near the player from the existing frame-matched neutral/firing captures, starting with the visually correlated `0x16D1` X candidate. Search/compare Y rather than assuming a slot layout; require three separated visual matches plus a fresh-save/movement comparison. Budget: zero Jev requests. This unlocks body-hazard and firing-alignment summaries, which the projectile-only preview currently lacks. After that prerequisite, keep the first experimental Jev segment bounded to five attempts, with explicit provenance and stale-reply rejection.

## Earlier progress log (historical; consult the current checkpoint first)

The entries below retain the discovery history, including disproved interpretations. In particular, `0x002C` is not accepted player Y, and an `EXTINCT` HUD label alone is not accepted as death detection.

## Verified

- BizHawk 2.11.1 runs the supplied USA SNES ROM.
- Lua file bridge and Python action bridge communicate.
- Live TypeSafe Choice calls returned decisions, confidence, probabilities, and latency.
- A live calibration run produced Jev `up` decisions and visibly moved the aircraft upward.
- Launcher defaults to a 60-call limit and releases controls at stop/end.
- Zero-Jev gun test visibly fired the main gun during the `Y` button segment; the pulse pattern is recorded.
- The first provisional X/Y marker was visually rejected.
- A consolidated BizHawk-API calibration script is now available; manual RAM Search is no longer part of the workflow.
- WRAM `0x1011` and `0x002C` are verified screen-coordinate observations for the player within the tested positions and savestate. BizHawk screenshots omit Lua GUI drawings, so the live overlay itself is not the validation source; the directional probe and offline annotated captures are.

## Provisional

- WRAM `0x1024` is a repeatable movement-correlated candidate, not established player Y.
- `fire:true` is only an action-file request; visible gunfire is verified separately for the deterministic Y pulse pattern.
- The fixed target-70 prompt is calibration-only, not gameplay policy.
- Hazard-object candidates, health, danger/recovery semantics, full screen bounds, and clean mid-run savestate reload behavior remain unverified.

## Unknown

- Full screen bounds, health, hazards, enemies, bullets, pickups, collision geometry, recovery, and invulnerability semantics.
- Repeated passive runs reached visible `DANGER` and `EXTINCT` transitions, but no health address was accepted.

## Current change/test

- Added run IDs, per-run JSONL logs, emulated-frame action expiry, candidate snapshots, and zero-Jev cardinal calibration mode.
- Added an automated three-run passive health observation batch. All three runs completed and produced timestamped screenshots and change logs; the result is reproducible danger-state evidence, not a health map.
- Repeated the batch after fixing process cleanup. Runs `run_1789778438`, `run_1789778470`, and `run_1789778502` are complete and independent. Their screenshots show the same transition: active gameplay at frame-600 capture, then `EXTINCT` by frame-660 capture. The WRAM change pattern is repeatable, but broad and not uniquely attributable to health.
- Added and ran a dense passive capture (`dense_1789778766`) with screenshots every 10 emulated frames and valid frame-aligned CSV logging. The visible HUD changes from normal/danger-window at capture 620 to `DANGER` at 630 and `EXTINCT` at 640. The corresponding WRAM changes remain broad; no health field was promoted.
- Repeated the dense capture as `dense_1789778884`; its complete WRAM log and frame-630 screenshot are byte-for-byte identical to the first dense run. This verifies reproducibility of the transition, not a health address.
- Ran deterministic perturbation `perturb_1789778967` with Up held for 120 frames, then neutral. The visible transition moved earlier: `DANGER` by capture 600 and `EXTINCT` by 630. This confirms the observation responds to controlled gameplay input, but still does not isolate health memory.
- Ran deterministic Down perturbation `perturb_down_1789779128`. The aircraft was no longer visibly present by the 600-frame capture and the HUD was degraded by 630, confirming the probe can shift the death path substantially; it yielded no health address.
- Ran recovery probe `recovery_1789779221`: neutral for 450 frames, then alternating Left/Right every 30 frames. The aircraft entered an explosion/death sequence around captures 600-630; no recovery was observed and no health address was isolated.
- Ran focused first-damage capture `first_damage_1789779381`, taking screenshots every 2 frames from capture 500 onward. The first visible `DANGER` HUD transition was narrowed to between captures 626 and 628.
- Ran firing comparison `first_damage_fire_1789779536` with the verified Y pulse pattern. At captures 626-628 the aircraft remained active with no `DANGER`; visible shots and score changes were present, reaching score 1200 by capture 700. This verifies that the firing pattern changes gameplay, but it does not identify health memory.
- Audited and repaired the live bridge path: removed duplicated Lua candidate assignments, fixed the out-of-scope marker variables that caused prior `nil`/`gui.box` failures, made the marker explicitly provisional, and changed normal bridge fire to the verified Y pulse instead of defaulting to A. `bridge.py` passes Python compilation.
- Automated smoke tests with BizHawk loading `main.lua` completed: zero-Jev cardinal calibration ran 5 actions, zero-Jev gun-test ran 4 button segments, emulated frames advanced, and the stop action released controls. The resulting state recorded Y as the normal firing button and retained health as null. Visual gunfire was already independently verified in the firing observation run.
- Added `--max-calls` for bounded live tests without changing the 60-call default. A real five-call Jev run completed: all five decisions were `up`, each was applied with Y firing, actions were issued 30 emulated frames apart, and measured latencies were approximately 211–513 ms. Controls released at the limit.
- Added and ran `launchers\run_live_smoke.bat`: it automatically starts BizHawk, loads `main.lua`, performs five live Jev calls from the local credential file, releases controls, and closes the emulator. The run logged five applied `up + Y-fire` actions with 223–495 ms latency.
- Added frame-regression handling: Lua releases controls and blocks the old run after a rewind; Python detects decreasing emulated frames, logs a regression event, writes a stop action, and exits safely. State now includes `source_frame`, `frame_regressed`, and actual applied-button fields. A zero-Jev five-action timing test measured exactly 30 emulated frames between issued actions, matching the configured interval.
- Normal five-action calibration still passes after the reload-handling changes. A test-only Lua-triggered `savestate.loadslot(1)` stalled the Lua loop before a latched regression state could be observed; Python's no-progress watchdog stopped and released the action file. Reload handling remains implemented but not fully runtime-verified.
- Fresh six-step zero-Jev calibration `run-20260918-204819-0c8b7a` measured 20 emulated frames per probe: Up changed candidate Y 112→67, Down 67→107, Left changed X 96→49, and the post-right hold captured X 49→94. Neutral held position. This is repeatable directional evidence for the X/Y candidates, although automated overlay capture remains unavailable.
- Independent offline annotations placed the `0x1011/0x002C` player reference at the aircraft across combat captures 540, 560, 600, and 620. X/Y are now verified as repeatable screen-coordinate observations for this savestate/ROM; the live Lua overlay itself cannot be included in BizHawk screenshots.
- Added and ran `evidence/hazard_observation\\run_1789779942`: verified Y firing, player-coordinate candidate capture, screenshots, and full WRAM change logging. It reached active combat, but no enemy/projectile address was promoted because screenshot output does not include Lua overlays and no object candidate has visual validation yet.
- Tested BizHawk `client.screenshottoclipboard()` with the player marker. Clipboard export succeeded, but the resulting image also omitted Lua GUI text/boxes. The aircraft was visible, but marker verification remains pending an in-window visual check.
- Tested `client.setscreenshotosd(true)` as well; the resulting clipboard image still omitted Lua drawings. This confirms the available BizHawk screenshot paths cannot be used for automated overlay verification.
- Added full-WRAM snapshot capture and offline candidate ranking. Run `snap_1789780676` contains 90 snapshots over emulated frames 20187–20543; the scanner ranked 312 variable adjacent byte pairs, with top candidates around `0x16D7–0x179B`. These are discovery candidates only and are not used for control.
- Added and ran a visual-only candidate overlay for the top five pairs with Y firing. It completed without injecting candidate-based controls; because saved screenshots omit Lua overlays, no candidate was promoted from this run.
- Added neutral-vs-firing snapshot comparison. Neutral run `snap_1789781633` produced the same top coordinate-pair ranking as firing run `snap_1789780676`; 7,895 of 11.8 MB of sampled WRAM differed, but the shared top candidates were unchanged. No hazard address was promoted.
- Extended the firing snapshot through the combat/death window as `snap_1789781699`: 225 snapshots, frames 20187–21083, 29.5 MB. The offline ranker now rejects pairs dominated by 0/255/off-screen sentinels; 374 candidates remain, all unverified.
- Extended the analyzer with valid-screen occupancy and motion-change metrics. The dynamic report ranks repeatedly changing pairs such as `0x00CF/0x00D0`, `0x0068/0x0069`, `0x090B/0x090C`, and `0x1710/0x1711`, but these are still statistical candidates with no visual object validation.
- Added offline screenshot annotation for candidate RAM values. Across combat frames 540–620, some boxes overlap visible aircraft in individual frames but then point at unrelated/HUD/terrain areas, consistent with reused slots or non-coordinate data. No enemy or projectile candidate was promoted.
- Corrected the annotation frame-index bug and recorded three provisional moving-object tracks: `0x090B/0x090C`, `0x0908/0x0909`, and `0x16F5/0x16F6`. Their identities remain unknown; no collision sizes or control use have been added.
- Repeated the extended snapshot with neutral input as `snap_1789782836`. The `0x0958/0x0959` track matched the firing run at sample 580 and its annotated box landed on the same visible blue projectile with firing both off and on. This is provisional hostile-projectile/background evidence, not a verified identity.

## Superseded next experiment (historical)

Validate one projectile identity with matched firing-off/firing-on captures at short frame spacing, then validate one enemy track across three samples and a fresh slot-1 start. Use zero Jev calls. Do not promote any statistical RAM candidate or build collision logic until the visual continuity test passes.

## End-of-day audit

See [`AUDIT_2026-09-18.md`](AUDIT_2026-09-18.md) for the evidence ledger, the real Jev request-to-input trace, timing caveats, and the bounded restart prompt. No runtime code was changed during the audit. The project is blocked at the threat-observation prerequisite, not at the BizHawk/bridge plumbing.
