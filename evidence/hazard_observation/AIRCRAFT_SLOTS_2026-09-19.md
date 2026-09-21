# Aircraft slots 0x17C0, 0x1800, 0x1840, 0x1880 - gate/lifetime validation, 2026-09-19

Handoff entry: [CLAUDE_HANDOFF.md](../../docs/notes/CLAUDE_HANDOFF.md). Current truth: [PROJECT_STATE.md](../../docs/notes/PROJECT_STATE.md), [MEMORY_MAP.md](../../docs/notes/MEMORY_MAP.md). Previous step: [combat segment report](COMBAT_SEGMENT_2026-09-19.md).

**Zero Jev requests in this step.** The credential file was not read. Every emulator run was a zero-API runner that closed only its own process.

## Verdict

The orange-aircraft blind spot found after the live combat run is closed for four explicitly checked slots. `0x1840` (the handoff's `0x1851/0x1854` candidate) passed every handoff criterion. The three other ranked candidates (`0x17D1`, `0x1811`, `0x1891`) belong to slots `0x17C0`, `0x1800` and `0x1880`, and each passed the same per-slot test in both recordings. The controller now observes **7 checked aircraft slots + 6 projectile slots**.

This is still incomplete coverage. It is not a colour/type classifier, collision geometry, health/death mapping or level-clear capability. `0x1700`/`0x1740` pass the gate only in the Left/firing replay, where three zoomed samples each show green helicopters exiting right. They remain unadopted candidates.

## Method

- Recordings (unchanged): neutral `probe_20260919-114543-d95c1f_neutral` (samples 0-60 and 550-900, every 2 game frames) and Left/firing replay `probe_20260919-132216-1dd64b_pulse8` (0-60, 480-570). For `0x1840` and `0x1880`, the 64-byte records are byte-identical in the two recordings at all 42 shared samples, including the 11 active samples 550-570. That overlap is not independent evidence; the replay contributes 480-548 and a different player/firing context. `0x17C0` and `0x1800` differ in that window because the replay's player destroyed them.
- Gate: the existing aircraft research gate, bytes `+0..+3 = C8 4A B0 02` and `+8 = 03`. Coordinates: signed 24-bit little-endian /256 at `+0x10` (X) and `+0x13` (Y). The old u8 candidates (`0x1851/0x1854`, etc.) are the integer bytes of these fields.
- `analyze_aircraft_slot.py <capture> --base 0x1840 [--compare <capture>]` (new) applies the existing aircraft gate/reset code to a slot's bytes and writes `aircraft_slot_<base>_evidence.json`. Running it does not enable a slot.
- `scripts\render_projectile_evidence.ps1 -EnemyProfile -ProjectileBases <base>` was reused. Single-base sheets now label the gate byte and the 16.8 X/Y, so hidden markers can be audited. Zoomed crops of edge cases were also inspected.

## Results

"Orange" means that an orange-pixel component (`orange_components.csv`) lies within 3.1 px of the gated, on-screen reference. That is proximity evidence, not identity. "Suppressed" counts samples where the old ungated u8 pair would have drawn an on-screen marker but the gated 16.8 reference draws none.

| Slot | Neutral recording | Left/firing replay | Orange (neutral / replay) | Suppressed (n / r) | Inspected sheets |
|---|---|---|---|---|---|
| `0x1840` | 550-766 on screen; 768-774 reference past the right edge; 776-888 gate off (`00`); 890-900 new occupant, a **green** helicopter | 480-570, one lifetime | 109/110 (miss: sample 900, green) / 46/46 | 62 / 0 | `orange_1840_gated_neutral_track.png`, `orange_1840_gated_neutral_exit.png`, `orange_1840_gated_left_replay.png` |
| `0x17C0` | 550-810; 812-820 past the right edge; 822-900 gate off | 480-488; hit header `D0` at 490, explosion at the reference at 492, score +100; later reused by a ground-level object (gated out) | 131/131 / 5/5 | 43 / 33 | `aircraft_17C0_gated_neutral.png`, `aircraft_17C0_gated_left_replay.png` |
| `0x1800` | 550-744; 746-752 past the right edge; 754-866 gate off; 868-900 new occupant, a **green** helicopter | 480-546; `D0` at 548 beside the player; explosion at 550 | 98/107 (all 9 misses are 880-900, the green occupant) / 34/34 | 62 / 12 | `aircraft_1800_gated_neutral.png`, `aircraft_1800_gated_left_replay.png` |
| `0x1880` | 550-788; 790-796 past the right edge; 798-900 gate off | 480-570, one lifetime | 120/120 / 46/46 | 54 / 0 | `aircraft_1880_gated_neutral.png`, `aircraft_1880_gated_left_replay.png` |

The sheets live in the recording folders. Each reference follows its helicopter through wide X and Y ranges in both recordings, for example `0x1840`: neutral X 24..256 / Y 64..149 and replay X 26..130 / Y 125..176.

**Phantoms explained.** The neutral 780/820 "phantom" at (15,97) is the low byte of X = 271.05 (`0x010F0E`) after the helicopter left the screen. With the full 24-bit X, the gate and the on-screen test each independently suppress it.

**Reference is not extent.** At `0x1840` samples 768-774 the reference is past X=256 but the tail is still visible. Off-screen references are excluded from forecasts, so a partly visible sprite at the right edge can be unrepresented.

## Coordinates: fraction and sign

- **X.** `+0x10..+0x12` is 16.8 with a carry into the high byte. For example, `0x1840` moves 255.727 -> 259.133 across samples 766 -> 768 at a constant 436/256 px per frame. The neighbouring field `+0x16..+0x18` integrates into X within 1/256 px on 114/117 neutral and 45/45 replay two-frame steps for `0x1840` (`0x17C0` 130/135 and 26/26, `0x1800` 103/117 and 33/33, `0x1880` 121/123 and 45/45). During the orange lifetimes, every miss is at most 4/256 px, at velocity changes. `0x1800`'s other 12 misses are its green second occupant, whose X steps differ from the field by a constant 65/256 px per frame; that occupant's motion rule is not decoded.
- **Y.** `+0x19..+0x1B` integrates into Y whenever Y moves (82/117 and 36/45 for `0x1840`). The other steps are stretches where Y stays constant while that field is non-zero. Its meaning is not adopted. Y fraction support comes from these integrating steps.
- **Sign.** Negative coordinates were not observed; the minimum X is about 24. The signed decode remains untested for this family, as for `0x16C0/0x1780/0x1940`.

## Lifetimes and velocity

The unchanged tracker was run on the real bytes. Gate-off samples clear velocity. A new occupant starts a new generation with no velocity. `0x1840` is generation 1 from 550 to 774, inactive from 776, generation 2 from 890 (`vx` None). One conservative extra reset occurs when the byte-13 fingerprint changes inside a lifetime (`0x1840` sample 900, `0x1800` sample 878). That drops one velocity estimate and never carries one over.

Only transitions with at least one gate-off sample in between were observed (2-frame sampling). A direct occupant swap without a gate-off frame has not been seen; the tracker's gap/jump guards remain the fallback.

Header states seen in these slots are byte observations, not decoded game states:

- `C8 4A B0 02 .. 03`: gated, flying.
- `D0 C0 FC 04 .. FF/F9`: after a hit; coordinates drift, then byte 0 becomes `00`.
- `00 4A B0 02 ..`: after exiting; coordinates frozen near X=271.
- `C8 F0 90 02 .. 05` (and `E0 74 92 02` in a dry run): other objects reusing `0x17C0`. **Byte 0 = `C8` alone is not an aircraft test.**

Regression tests: `test_slot_1840_recorded_exit_and_reuse_never_carry_velocity` and `test_slot_17c0_recorded_hit_and_ground_reuse_are_not_aircraft` (real 22-byte payloads). `test_lua_export_matches_checked_slot_lists` keeps `lua/main.lua` and `ENEMY_BASES` equal.

## Runtime checks (zero API)

| Run (`runs/`) | Result |
|---|---|
| `combat-20260919-135757-4bbef0-dry` | 4 aircraft slots. All runner checks passed. Exported `0x1840` payloads were byte-identical to the offline captures at all 110 overlapping frames. `dry_slot_1840_reference.png` (inspected) shows the reference on the helicopter from its entry at the top right (frame 20603), earlier than either recording. |
| `combat-20260919-140241-240bde-dry` | 7 aircraft slots. All runner checks passed. `0x1840/0x1880/0x1940` were identical to the captures at 109/109 frames. `0x16C0/0x1780/0x17C0/0x1800` diverged only after the dry run's inputs diverged (frame 20672): the dry run shot down different helicopters and `0x1800` survived. `dry_slot_1800_reference.png` and `dry_slot_17C0_reference.png` were inspected. |
| `combat-20260919-140905-903ba4-baseline` | New 7-slot baseline, zero API, normal end at frame 20873. Against the old 3-slot baseline: player X/Y identical at all 688 shared frames, previously exported slot bytes identical, 34/34 screenshots identical. The 7-slot dry run matches it on 487/487 pre-decision observations and 24/24 screenshots. The dry run's mock requests carried 6/4/4/3/3 aircraft tracks. |
| `bridge-check-20260919-140406-33db6b` | **Failed.** The regular bridge crashed on its final dry-run action when a concurrent Lua write read as `None` after acknowledgement. This is a latent `bridge.py` bug; the larger state file slightly widens the race. Fixed by skipping unreadable reads after the no-progress watchdog; covered by `test_unreadable_state_after_final_ack_waits_for_a_real_state`. |
| `bridge-check-20260919-140501-03201e`, `...-140507-3b1b07` | D/L dry-run and cardinal calibration pass after the fix, with exact 30/20-frame actions. |

All 45 offline tests pass (`python -m unittest discover -s tests -t tests`).

## Offline controller check at the live decision frames

The replay reproduces the live run's input prefix. Its RAM at the live decision frames gives the same player positions and the same original track counts (2 aircraft, 1/1/0 bullets) as the live `decision_trace.json`. The runs are `runs/brain-replay-20260919-135730-42ecda` (4 slots) and `runs/brain-replay-20260919-140232-c33436` (7 slots), from `python src/replay_brain.py <replay> --combat --horizon-frames 30`.

| Live request (frame) | Player | Aircraft tracks: original / now | Aircraft-reference gap per action, now (original) |
|---|---|---|---|
| 1 (20663; offline at 20665, the first sample with velocity) | 96,112 | 2 / 6 | down 17.3 (44.8); others unchanged |
| 2 (20693; Jev chose Left) | 61,112 | 2 / 5 | up 54.6 (77.3), down 7.9 (77.3), **left 32.3 (77.3)**, right 35.8 (35.8), hold 52.4 (77.3) |
| 3 (20723; reply never retained) | 16,112 | 2 / 5 | up 26.1 (160.7), down 10.4 (160.7), **left 6.4 (160.7)**, right 16.2 (133.8), hold 6.4 (160.7) |

The helicopter formation sweeping along the bottom left toward the player was absent from both applied Left requests. These gaps are between reference points. They do not show how Jev would now choose, or that the outcome would change.

## Observation near the live guard (not a mechanism claim)

In the replay, `0x1800`'s helicopter was 11 px right of and 15 px below the player reference at frame 20729. It switched to the `D0` header at frame 20731, one frame before the live guard fired (X=15 at 20732). Explosions appear there by sample 550 and the score rose by 100 by sample 552. In the dry run, where mock movement kept the player away, that helicopter kept flying. This is consistent with a player-helicopter collision. Collision, damage and death semantics remain **unverified**, and the guard and movement bounds are unchanged.

## Still unknown

`0x1700`/`0x1740` (gated only in the replay, exiting right), ground objects, terrain, other hazard families, collision sizes, health/death/recovery, kills/pickups and level-clear detection. The late-response drain branch in `play_segment.py` is still not verified with a real in-flight request.
