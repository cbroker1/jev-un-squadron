# Brain architecture adoption and validation - 2026-09-19

Machine-local date: September 19, 2026, America/Chicago. All experiments and tests in this report used **zero Jev requests**. The reusable credential file was not read or changed. The original D/L launcher remains intact.

## What was adopted

The useful idea from [jev_vampire_survivors](https://github.com/oldmoldycake/jev_vampire_survivors/tree/dae83d82593a13b882bf0abd5f481b5219357f64) is separation of game-state capture, a compact action digest, typed questions and execution. Its Linux Unity integration is not needed here. We retain BizHawk, its Lua API, the file bridge and the existing Windows workflow. We did not copy its late-response acceptance or movement fallback-on-error behavior, nor mistake its polling rate for a rate of fresh model decisions.

Following the installed TypeSafe skill and current [Choice documentation](https://docs.typesafe.ai/primitives/choice), code does the known coordinate math; the question offers meaningful movement descriptions. The [state documentation](https://docs.typesafe.ai/concepts/state) calls for text/structured state, not screenshot input. Screenshots here validate our observations; they are not sent to Jev. The live ROM check uses the documented [BizHawk game-info API](https://tasvideos.org/Bizhawk/LuaFunctions#gameinfogetromhash).

- `brain/observations.py`: explicit checked slots, signed reference coordinates, game-frame velocities, independent slot lifetimes and ROM/schema checks.
- `brain/digest.py`: cardinal consequences, measured movement bounds and nearest projected reference-point separation over at most 30 game frames. No collision boxes/probability are invented.
- `brain/questions.py`: five explicit options (up/down/left/right/hold), unknown coverage stated, firing independent. The prompt remains marked OFFLINE RESEARCH.
- `replay_brain.py`: unique logs and request previews from saved captures, no network or controller writes. Mock decisions are labelled `deterministic_test`, never `jev`.
- `observe_brain.py`: passive current-state reader; no movement/fire commands, STOP handshake only, no repeated preview of an unchanged frame, stops on reload/session changes or loss of progress.
- `lua/main.lua`: adds a small versioned packet of six slots' observed bytes to the existing state file. Exact ROM hash is checked by the reader. The regular controller/launcher workflow is preserved.
- `check_bridge.py --mode brain-preview` and `launchers\run_brain_preview.bat`: bounded automatic real-emulator verification. The checker now rejects another run's old STOP state and returns failure for failed checks.

The new observation/digest/request path is implemented and verified **offline**, including a live emulator's observations. It is deliberately not wired to paid requests or control execution yet (`live_control_ready=false`). The old live path remains target-70 calibration, including its explicitly logged legacy confidence override. No new report attributes a deterministic or fallback action to Jev.

## Reproducibility

ROM SHA-256: `0b155a54b6134601fc0791252a63ca73efd522667c3d6fd7a44f5b3c500039d7`.
ROM SHA-1 from file and Lua: `a2dd48574b9f7a49977c91d12d5c52c17c2c82aa`.
Slot-1 SHA-256: `c1ea750e24cdb17e2050eb4f490c82b3e7544c11441f736f60df7c014fde0f3d`.
BizHawk 2.11.1 / Snes9x, WRAM, original slot starts at game frame 20183. New runners explicitly set and log 50% speed; sound volume stays zero. Save hashes were unchanged after the runs. No RAM pokes or downloaded ROMs.

All paths below are relative to the project root unless linked relative to this report. Raw `frames.csv` ties each image to an exact game frame and full-RAM snapshot index; filenames alone are not the validation.

## Movement and the forecast experiment

Separate captures held one direction for samples 1..120, then neutral through 150:

| Capture under `evidence/hazard_observation/` | Observed reference-point bound |
|---|---|
| `probe_20260919-120249-a2c691_neutral` | Up: Y 48 |
| `probe_20260919-120309-36680a_neutral` | Down: Y 191 |
| `probe_20260919-120318-89d814_neutral` | Left: X 16 |
| `probe_20260919-120327-bf3cdb_neutral` | Right: X 239 |

Inputs were read back at the core, positions measured throughout and raw sample-120 images inspected. X/Y are WRAM `0x1011/0x1014`; positive Y means down. Travel before the bounds is five pixels per two frames. These limits apply to the current pilot/save's reference point, not sprite extents or collision geometry.

The independent intervention [probe_20260919-120911-629b88_neutral](probe_20260919-120911-629b88_neutral/forecast_validation.json) held Left only on samples 601..620. Its 37 shared pre-intervention RAM captures were byte-identical to the neutral reference. `verify_forecast.py` uses only state/history through sample 600 to predict the next 20 frames. Across all 11 captured points, both player and first-projectile coordinates had **zero error**. Player X changed 96 -> 46 with Y 112. Actual input-poll masks matched the exact window and were zero outside it. Raw sample-600/620 screenshots were inspected. This validates the short forecast, **not** collision avoidance, damage prevention or survival.

## Projectile-family evidence and limits

Main neutral capture: [probe_20260919-114543-d95c1f_neutral](probe_20260919-114543-d95c1f_neutral/manifest.json), 900 frames, 207 snapshots. A signature search across actual WRAM found six bases; these were not generated by assuming a stride. Corresponding coordinates were compared with independently extracted image components and visually inspected.

| Base | X/Y starts (signed24LE /256) | Neutral visual matches | Firing visual matches |
|---|---|---|---|
| `0x1AC0` | `0x1AD0/0x1AD3` | 45 | 29 |
| `0x1B00` | `0x1B10/0x1B13` | 22 | 13 |
| `0x1B40` | `0x1B50/0x1B53` | 14 | 6 |
| `0x1B80` | `0x1B90/0x1B93` | 13 | 5 |
| `0x1BC0` | `0x1BD0/0x1BD3` | 7 | Not observed with this signature |
| `0x1C00` | `0x1C10/0x1C13` | 7 | Not observed with this signature |

Inspection aids: [neutral six-slot overlay](probe_20260919-114543-d95c1f_neutral/family_reference_overlay.png), [firing four-slot overlay](probe_20260919-121654-34c1a8_pulse6/firing_family_reference.png), [lifetime transition overlay](probe_20260919-114543-d95c1f_neutral/lifetime_signed_gated.png). Boxes label RAM reference points, not collision sizes. The cyan-component matcher allows a three-pixel reference/rendering difference; color animation means a missing cyan match does not prove disappearance. Raw screenshots were inspected as well as annotations.

The first slot has three moving occurrences in the neutral capture: samples 564..720, 742..782, and 802..900. Between occurrences, `00`/`C0` tags and changed header bytes invalidate history. Old coordinates can remain in an inactive slot; drawing them unconditionally creates a phantom marker. X passes 0.9609375 at sample 698 to -2.21875 at 700; interpreting just its unsigned byte falsely wraps it to the right edge. Another slot (`0x1B40`) passes Y 0 at sample 888, then -3 to -18 at 890..900. Signed 16.8 reads keep those trajectories continuous.

The accepted research gate is only the observed header `CC 7F F9 04` with +0x08 equal to 1, at the six explicit bases. Opaque fingerprint changes, session/epoch changes, non-increasing frames, gaps over six frames, or implausible jumps reset velocity. The gap and jump limits are tracking guardrails, not game mechanics. Reuse with an indistinguishable header between missed frames remains possible; all bullet classes and slots are not established.

The [firing capture](probe_20260919-121654-34c1a8_pulse6/validation.json) repeated 900 frames at 50% speed with Y one frame on/five off. It produced visible player shots and 53 visual matches across four of the mapped enemy-projectile slots. The separate player-shot occurrence `0x1091/0x1094` remains distinct; general player-shot enumeration is not implemented. The regular bridge's existing Y four-on/four-off pattern also produced visible shots in [frame 20265](../../runs/bridge-check-20260919-122841-fc42ab/frame_20265_call_3.png).

## Real bridge regression evidence

Each run below has its own `manifest.json`, input trace and `validation.json`. Every listed completed run closed its own emulator normally, preserved slot 1 and used zero API requests.

| Run under `runs/` | Observed result |
|---|---|
| `bridge-check-20260919-122547-fb47e1` | Passive stream: 901 consecutive states over 900 game frames; 31 previews exactly 30 frames apart; 484 states with continuous on-screen track velocity; no injected movement/fire. |
| `bridge-check-20260919-124301-4ba70e` | Invoked through the actual `launchers\run_brain_preview.bat`: same 901 consecutive observations, 31 previews, 205 matching coordinate snapshots and 21 byte-identical reference screenshots. Normal automatic shutdown, no API requests. |
| `bridge-check-20260919-122719-3657b3` | Hold/up/down/left/right each exactly 20 applied frames, final hold 1; resulting positions match expected cardinal travel. All six input ACKs show observe-to-apply = issue-to-apply = 1 game frame. |
| `bridge-check-20260919-122841-fc42ab` | Normal dry-run, three actions exactly 30 frames each, Y pulse input readback and visibly inspected shots. |
| `bridge-check-20260919-122848-f3a7b7` | Actual slot-1 load during Down; no injection after reload and no stale replay in the following 30 frames. |
| `bridge-check-20260919-122911-e550f9` | Deliberately terminated only the offline Python child; Lua's action lease ended after exactly 30 frames; no replay during 30 additional frames. |

The passive bridge [reference comparison](../../runs/bridge-check-20260919-122547-fb47e1/reference_comparison.json) checked **205 shared coordinate snapshots and 21 byte-identical screenshots** against the independent full-WRAM neutral capture. This establishes that the new main.lua packet/decoder preserves the verified observations. It does not establish a safe movement policy. Screenshot [game frame 20803](../../runs/bridge-check-20260919-122547-fb47e1/brain_frame_20803.png) was inspected directly.

The first attempt, `bridge-check-20260919-122448-ff27d2`, failed before observation because of a Python syntax error. Its initially recorded final state belonged to an old run and is explicitly rejected as evidence. Its owned emulator required fallback cleanup. The syntax issue and checker freshness weakness were fixed; the later successful run above is the accepted evidence. Failed artifacts were preserved.

`python -m unittest discover -s tests -t tests`: **30 passing offline tests**, including actual capture replay with networking forbidden, signed decoding, per-slot identity, profile validation, reload/gap resets, forecast geometry, physical-versus-injected input, duplicate-frame suppression, stale reply rejection, sanitized API-error accounting and stop cleanup. Unit tests alone are not gameplay evidence; the emulator runs above supply that.

## Timing and mode honesty

At 50% speed the 900-frame passive stream took 29.941 seconds after its handshake. It consumed every game frame in that run (maximum observed gap 1). Preview spacing was 30 game frames, not Python sleeps. The normal bridge's intermediate decision schedule is observation-to-observation; API latency consumes the target interval rather than being followed by another full interval. Its final action gets its full applied-frame lease before STOP.

No new real Jev latency was measured here. One-frame offline apply delay does not predict paid API latency or threat avoidance. Existing late replies are rejected; the experimental request preview is not wired to paid decisions. Pause-and-step remains deferred, and no real-time or survival improvement is claimed. `hold` is not assumed safe, low health never implies holding still, and model confidence is not collision probability.

The historical target-70 Jev calibration is the only live-model behavior established so far. The new preview exposes five movement descriptions and explicit unknowns; it has no model decision, fallback or applied action. Sample previews are in `runs/brain-replay-20260919-121840-3a434a` (neutral) and `runs/brain-replay-20260919-121840-05ec60` (firing).

## Remaining prerequisite and single next experiment

Enemy-aircraft bodies still are not represented in the digest, so projectile separation can look favorable while a visible aircraft occupies the proposed route. Health/danger/recovery/death remain unknown. `EXTINCT` text was visible in earlier captures even while the aircraft later remained visible; text/flashing alone must not be used as a death or invulnerability detector. Firing alignment, collision geometry and terrain are also missing. This is progress toward useful Jev decisions, not a completed hazard-avoidance agent.

Next: validate **one enemy-aircraft X/Y track** near the player using the existing neutral/firing captures, beginning with the previously visually correlated `0x16D1` X candidate and an evidence-driven Y comparison. Require three separated frame-matched visual locations and a fresh-save/movement comparison before inclusion in observations. Use zero Jev requests. Do not start another unconstrained whole-RAM ranking cycle or infer object layouts from the projectile profile.

After that observation prerequisite, the first useful Jev-driven segment must be a bounded five-attempt experiment with current-frame summaries, model/requested/applied provenance, no confidence-to-hold fallback and explicit frame-age rejection. It should compare against firing-only from the same save, without reporting unverified kills, pickups, damage counts or survival.

Power-ups, shops, special weapons, broad infrastructure changes and pause-and-step are deferred. The original milestone ordering remains player controls -> hazards/damage -> bounded useful Jev decisions -> repeatable evaluation -> pickups. No new emulator or worker was left running after these checks.
