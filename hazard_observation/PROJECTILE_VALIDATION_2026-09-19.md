# Projectile observation validation

Follow-up: [2026-09-19 brain adoption and validation](BRAIN_ADOPTION_2026-09-19.md) adds tested player bounds, signed projectile coordinates, slot-lifetime evidence and completed main-bridge checks. Its current checkpoint supersedes this report's pending-work statements; this file preserves the earlier experiments.

Captures ran on local 2026-09-18; this report was completed on 2026-09-19. All experiments in this report used **zero Jev requests**, the existing USA ROM, Snes9x, and quicksave slot 1. The save hash stayed unchanged in every completed probe.

## Reproduction

- ROM SHA-256: `0b155a54b6134601fc0791252a63ca73efd522667c3d6fd7a44f5b3c500039d7`. Earlier notes accidentally omitted the final `7`.
- Slot-1 SHA-256: `c1ea750e24cdb17e2050eb4f490c82b3e7544c11441f736f60df7c014fde0f3d`.
- BizHawk 2.11.1; Snes9x configured; NTSC; WRAM is 131072 bytes.
- Each probe started at game frame 20183. Lua explicitly set 50% speed, and `inputs.csv` recorded `speed_percent=50` every frame. Wall time for the 660-frame pulsed run was 24.639 seconds including emulator startup and capture work.
- `probe_hazards.py` owns only the emulator it starts. `run_projectile_probe.bat` runs neutral and pulsed-Y captures. Esc, Ctrl+C, and `stop_projectile_probe.bat` can stop the experiment.
- Every snapshot has its actual game frame, binary snapshot index, and exact screenshot filename. Old `sample/4` indexing must not be used on the new capture format.

## What the controlled captures established

| Question | Evidence | Conclusion |
|---|---|---|
| Does the game receive the requested inputs? | `probe_20260918-211754-45e1bc_neutral/inputs.csv` and its pulsed companion: 660 consecutive frames each; `joypad.getwithmovie(1)` read in `event.oninputpoll` agrees with the requested mask on every polled frame. | Verified for these runs. This readback is stronger evidence than an action file. |
| Does Y fire? | `probe_20260918-211701-bb7bbe_pulse6/frame_0012.png`; pulsed combat images; three single-shot runs below. | One frame of Y on, five frames explicitly off produces visible shots. Legacy hazard captures held Y; that is a different experiment. |
| Are captures repeatable? | `probe_20260918-211754-45e1bc_neutral` versus `probe_20260918-212224-2705a0_neutral`: all 65 shared raw WRAM snapshots and PNG files match byte for byte. | Verified fresh slot-1 repetition, not a mid-run reload test. |
| Can one enemy-fired projectile be located? | [Projectile contact sheet](probe_20260918-211754-45e1bc_neutral/projectile_contact_sheet.png), raw frames 564-622, and `cyan_components.csv`. It appears beside the green enemy at sample 564 and moves left/down independently while the enemy moves right. Player Y input is off for the whole run. | WRAM `0x1AD1` X / `0x1AD4` Y follow this projectile. Visual origin supports classifying this occurrence as enemy-fired. Its ability to damage the player, slot lifetime and general type identifier remain unverified. |
| Is it distinguishable from our gunfire? | `probe_20260918-212327-a2161e_pulse6` applies exactly one Y press at sample 6. Two additional probes move up/down for 20 frames, then apply one Y press at sample 24. | A separate orange/white player shot travels right. `0x1091` follows its X; `0x1094` equals its visible Y at 112, 62 and 162 in the three probes. |
| Does Stop cancel the queued run? | `probe_20260918-213036-623846_neutral/status.txt`: stopped at sample 408 / game frame 20591; exit code 0; next pulsed run was never started. | Verified for the new offline runner. Its `validation.json` intentionally has `frame_budget=false` because the user-stop test ended early. |

## Enemy-fired projectile track

`match_projectile_track.py` matched measured cyan sprite pixels against every WRAM byte. These visual samples have one component of at least four cyan pixels each. Color is a measurement aid for this experiment, not a runtime object classifier.

| Sample | Game frame | Measured cyan center | WRAM `1AD1/1AD4` |
|---|---|---|---|
| 568 | 20751 | 208,96 | 207,98 |
| 574 | 20757 | 198,98 | 198,100 |
| 580 | 20763 | 189,100 | 188,102 |
| 586 | 20769 | 179,102 | 179,103 |
| 592 | 20775 | 170,104 | 169,105 |
| 598 | 20781 | 160,106 | 159,107 |
| 604 | 20787 | 150,108 | 150,109 |
| 610 | 20793 | 141,110 | 140,111 |
| 616 | 20799 | 131,112 | 131,113 |
| 622 | 20805 | 122,114 | 121,115 |

The match has at most one pixel X and two pixels Y difference from the selected cyan pixels. These pixels are not the whole sprite or its collision shape. The repeat run reproduces the same values and images.

Reading u16 little-endian at `0x1AD0` and `0x1AD3`, divided by 256, gives a consistent fractional trajectory: sample 564 `(214,97)`, sample 580 `(188.5625,102.0625)`, sample 622 `(121.7890625,115.3515625)`. Over that interval the measured changes are `-1.58984375,+0.31640625` pixels/game-frame. This supports a fractional-coordinate interpretation for this occurrence; signed/off-screen encoding is not established.

The old `0x0958/0x0959` pair is not a persistent track: at sample 600 it contains `(159,224)` while the visible projectile is still on screen near `(158,108)`. It must not be used as an enduring object identity. Low-memory `0x0020/0x0022` also match during part of this trace, but their lifetime is unknown.

## Player shot track

- Center-height single shot: `probe_20260918-212327-a2161e_pulse6`, samples 10-18.
- Upper shot: [contact sheet](probe_20260918-212607-18af78_pulse6/own_shot_up.png), samples 28-36.
- Lower shot: [contact sheet](probe_20260918-212623-fcf7d6_pulse6/own_shot_down.png), samples 28-36.
- In each case the five X readings are `146,168,190,212,234`; the visible orange/white centers are `137.5,159.5,181.5,203.5,225.5`. Thus this RAM anchor is 8.5 pixels ahead of the measured center. The contact sheets explicitly adjust X by -8 for display; the 8x8 marker is **not** a collision box.
- Y is exactly 112, 62 or 162 respectively. At the next edge sample X becomes 0 while the last rendered shot is still visible. Do not reuse an inactive/wrapped slot as a new on-screen shot without a lifetime check.
- No general own-shot list, kill detector, pickup detector, or collision geometry was added.

## Other corrections and limits

- `0x002C` was over-promoted as player Y. In the neutral combat capture it is 236 at sample 564, 224 at 590, 192 at 606, 160 at 622, and 128 at 638, while `0x1014` stays 112. It is unreliable for persistent player observation. `0x1014` matches the player and gun height in the upper/center/lower controlled tests; the new capture script uses it and preserves `0x002C` as `legacy_y_scratch`.
- `lua/main.lua` now reads Y from `0x1014`. The marker color was corrected to opaque green. The existing bridge integration recheck exposed stale startup state (`run-20260918-213222-c977ca`) and did not complete; completing that recheck is required before claiming the regular bridge has passed after this change.
- A green enemy's X matches `0x16D1` across nine samples 564-580. Its visible Y is constant in this segment, so the Y address remains unverified. See `green_components_ram_matches.json`; do not infer Y from an address offset.
- The old neutral run `snap_1789783018` is complete: 225 CSV rows, 29,491,200 WRAM bytes and frame-900 screenshot. The audit's incomplete-run claim was wrong.
- The regular bridge still has the target-70 calibration prompt using unverified `0x1024`. These new hazard candidates have not been supplied to Jev. Existing health, danger/recovery, death and slot-identity limitations still apply.
- Official references used for API semantics: [BizHawk Lua functions](https://tasvideos.org/Bizhawk/LuaFunctions), [TypeSafe Choice](https://docs.typesafe.ai/primitives/choice). The TypeSafe skill keeps typed choices separate from verified observations; no inference confidence has been treated as collision probability.

## Single next experiment

Complete a fresh-state startup and corrected-player-Y check through `lua/main.lua` and `bridge.py`, with zero Jev calls. Then continue projectile lifetime validation before feeding any hazard list to Jev. No broad coordinate scan is needed: the per-occurrence projectile addresses and visual evidence above are the starting point.
