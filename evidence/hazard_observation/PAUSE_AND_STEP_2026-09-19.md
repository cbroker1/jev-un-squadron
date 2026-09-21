# Pause-and-step and the prelude handicap - 2026-09-19 (afternoon)

Handoff entry: [CLAUDE_HANDOFF.md](../../docs/notes/CLAUDE_HANDOFF.md). Previous step: [aircraft slot validation](AIRCRAFT_SLOTS_2026-09-19.md). Carl approved paid requests for this round; they run on a free tier.

## Verdict

- **Decision latency was losing the game.** In the original gun-off scenario, pause-and-step alone was the difference:
  - Jev's Up at frame 20723 applied immediately, and the aircraft stayed under control through all 5 choices.
  - Both continuous-mode runs lost control at about frame 20732.
- **The runner's prelude was a handicap.** Its 480-frame neutral, gun-off prelude let the formation survive and let the player take a hit at about frame 20583. Every earlier combat segment therefore handed Jev an aircraft already showing DANGER.
- **Best run so far:** with the gun on from frame 1 plus pause-and-step, Jev made 10 choices over frames 20663-21083. The HUD damage gauge stayed full, while the stationary firing baseline took a hit about 20963-21003 and showed DANGER at 21083.

These are single runs per condition. Health, damage and death are read only from the HUD in screenshots; no RAM field is mapped. Level 1 is not solved.

## Implementation (zero-API tested)

- **`lua/main.lua`.** A command may carry `freeze_at_frame`.
  - On that frame, before applying any input, Lua calls `client.pause()`. It keeps writing the state with `"frozen": true` and an increasing `freeze_heartbeat` via `emu.yield()`.
  - It unpauses on a new command, STOP, or a 5-second wall-clock watchdog. It never injects input while paused.
  - Paused writes add no trace rows. `bridge.py` never sends `freeze_at_frame`, so D/L behaviour is unchanged (`bridge-check-20260919-162517-982ccb` passes).
- **`play_segment.py --stepped`.**
  - At each decision frame, it waits for Lua's frozen heartbeat at that exact frame; otherwise it stops with `freeze_not_confirmed`.
  - It then asks Jev synchronously and writes the choice with the next `freeze_at_frame`. The choice applies from the observed frame itself (`observe_to_apply_frames` 0).
  - The freshness check still applies if the watchdog ever resumes the game.
  - With no checked track to judge, it keeps firing and re-checks every 6 frames without a request.
  - The continuous mode is unchanged and remains the default in `play_segment.py`.
- **`--prelude-fire`.** Y pulses during the prelude instead of gun off.
- **`run_segment.py`.** Passes `--warmup/--frames/--stepped/--prelude-fire` through, records them in the manifest, and scales its worker timeout. When a run ends on its frame budget, its validator now requires every decision *made* to apply, rather than the full request limit.
- **Tests.** 47 offline tests pass, including `test_pause_and_step_applies_each_choice_from_the_observed_frame` and `test_pause_not_confirmed_stops_without_a_request`.

Emulator checks, zero API:

| Run (`runs/`) | Result |
|---|---|
| `combat-20260919-162425-348e15-dry` | Stepped, 900 ms mock replies. 5/5 applied with **0 game frames elapsed** while deciding; 631 input rows for 631 consecutive frames; up to 272 paused heartbeats per decision; all checks pass. (In continuous mode, a slower reply had already been rejected as 28 frames stale.) |
| `combat-20260919-162624-044833-dry` | Stepped + firing prelude, 420 frames. 11 mock choices plus 19 no-track re-checks, all acknowledged; 902 consecutive input rows. It re-validates as passing after the validator fix. |
| `combat-20260919-162523-593790-baseline` | Firing from frame 1, no movement, 420 frames. The formation was shot down (score 1200 by 20883). The player was hit about 20963-21003 (explosion at the player, gauge empty), with DANGER at 21083. |

## The prelude handicap (visual evidence)

Live-run prelude screenshots (`runs/combat-20260919-161552-2be94c-live/brain_frame_*.png`):
- The damage gauge is full through 20563.
- Red screen flash at 20583.
- Gauge nearly empty at 20603; DANGER at 20623/20643; gauge dark at 20663, the first Jev decision.

The existing fire-from-start capture `probe_20260919-121654-34c1a8_pulse6` has already destroyed the formation at sample 550 (score 900 against 100), with a full gauge. The neutral capture shows EXTINCT by 650.

## Live runs this round

| Run (`runs/`) | Setup | Requests | Result |
|---|---|---:|---|
| `combat-20260919-161552-2be94c-live` | continuous, gun-off prelude, 7 aircraft slots | 4 | Choices Left, Hold, Up, Down. See the first bullet below. |
| `combat-20260919-162830-7da253-live` | **stepped**, gun-off prelude | 5 | Choices Left, Left, **Up (p=0.61)**, Hold, Left. See the second bullet below. |
| `combat-20260919-162721-f5cd5f-live` | **stepped + firing prelude**, 420 frames | 10 | Choices Left, Down, Up, Left, Up, Right, Hold, Left, Down, Left. See the third bullet below. |

- **`161552` (continuous).** Up was observed at 20723 but applied at 20733. Helicopter `0x1800` switched to its hit header `D0` at 20731/20732, 20 px from the player reference. Up was then read back by the core for 30 frames, but the aircraft drifted: (40,112) -> (53,116), then slid to X=9. Screenshots show explosions on the jet and a blank pilot portrait by 20764. The guard stopped the run at 20778.
- **`162830` (stepped, gun-off).** All 5 applied from their observed frames and every movement matched the constant-speed prediction exactly. `0x1800` never entered `D0`; the only `D0` was `0x17C0`, shot down 124 px away. Normal end at 20813, all checks pass.
- **`162721` (stepped, firing prelude).** All 10 applied with 0 frames elapsed and exact predicted positions. At the other decision frames nothing was checked, and it re-checked without requests. Normal end at 21083, all checks pass. Against the matching baseline: 478/478 pre-decision observations and 24/24 screenshots identical. The gauge stayed full at 20883-21083 against the baseline's hit, with the same score (1300) and money (3900).

Reply latencies this round were 214-493 ms. Total paid attempts so far: 3 (earlier) + 4 + 5 + 10 = **22**.

## Caveats

- The stationary firing baseline is a weak comparison: any movement might have avoided that particular hit. What hit it is not identified.
- Jev often chose the movement limits (X=16, Y=48 corners). That kept it inside the guard, but the corners are not known to be safe in general.
- Only aircraft and one bullet family are tracked. Ground/tank fire, terrain and other hazards are unknown.
- The late-reply drain branch was not exercised: stepped decisions are synchronous, and no continuous run stopped with a request in flight.
- The decision interval is still 30 frames (75 px of movement per choice). Finer steps would cost more requests.

## Repeatability and a longer window (same afternoon)

All runs used `--stepped --prelude-fire`, the configuration in `launchers\run_jev_segment.bat`. All passed every runner check, with 0 game frames elapsed at every decision.

| Run (`runs/`) | Frames / cap | Jev choices | Result |
|---|---|---|---|
| `combat-20260919-163441-2b78da-live` | 420 / 14 | 10, **identical** to `162721-f5cd5f` | Gauge full at 20983/21043/21083; score 1300 |
| `combat-20260919-163515-8a9165-live` | 420 / 14 | 10; the first 8 identical, then Hold/Down instead of Down/Left | Gauge full through 21083; score 1200 (one fewer kill) |
| `combat-20260919-163609-585d4f-baseline` | 900, stationary firing, zero API | - | Hit about 20983 and DANGER by 21083. Drifted with no input from 21084, pinned at X=16, then the reference read (0,0) at 21205; the guard stopped the run. |
| `combat-20260919-163645-fc9efa-live` | 900 / 30 | 26 | Full window to **21563**; all 26 moves within 1 px of prediction (never lost control). The gauge was full through 21343, then **hit at about 21383**, with DANGER from 21463. |

**Stepped Jev against the stationary baseline:** the stepped runs are close to deterministic, since the same emulator state gives the same or nearly the same choices. Against the stationary firing baseline, Jev's first HUD hit came about 400 frames later, and it kept control to the end of the window. The baseline lost control at 21084.

**Next failure identified, visually.**
- At frame 21383 the screen flashes red and an **orange ball** is on the jet at about (241,73); the player reference is at (239,80), moving down after Jev chose Down from the (239,48) corner at 21371.
- No checked track was near: the only tracked bullet, `0x1B00`, was about 50 px below.
- Orange balls in flight are also visible at 21363. They are probably fired by the large ground turret at the bottom right, but that is not verified.
- This is an **untracked projectile family**. The six checked projectile slots are the blue-dot family.

## Next

Find the orange-ball projectile family with the same zero-API method used for the aircraft:
1. A full-WRAM plus screenshot capture covering frames about 21280-21420.
2. Colour-fragment candidate ranking.
3. A per-slot gate and lifetime check in two recordings.

The capture has to reproduce the Jev run's inputs, or use a probe that holds a similar position. Only then add those slots and rerun the 900-frame stepped segment.

Total paid attempts after these runs: 22 + 10 + 10 + 26 = **68**.
