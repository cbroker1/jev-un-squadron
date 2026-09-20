# Handoff - 2026-09-19 evening, America/Chicago

## Where this stands

A bounded experimental controller plays a 1800-game-frame segment of U.N. Squadron level 1 with Jev choosing movement. **Level 1 is not finished**; the segment ends on its frame budget, not at a level end.

Best recent runs, counting kills after Jev takes control at frame 20663:

| Run (`runs/`) | Kills (aircraft/tank/turret) | Hits | Power-ups | End |
|---|---|---:|---:|---|
| `combat-20260919-190025-afb1d?-live` | **42** (29/5/8) | 3 | 3 | full window |
| `combat-20260919-192145-60236?-live` | 39 (28/5/6) | 3 | 3 | full window |
| `combat-20260919-192417-b6847?-live` | 36 (30/0/6) | 3 | 2 | full window |

For scale: a passive configuration reached 10 kills, and an aircraft that only sits and fires gets 5 and dies around frame 21205.

Read next: [PROJECT_STATE.md](PROJECT_STATE.md) current checkpoint, [MEMORY_MAP.md](MEMORY_MAP.md), then the reports [OBJECT_TYPES](hazard_observation/OBJECT_TYPES_2026-09-19.md), [PAUSE_AND_STEP](hazard_observation/PAUSE_AND_STEP_2026-09-19.md) and [AIRCRAFT_SLOTS](hazard_observation/AIRCRAFT_SLOTS_2026-09-19.md).

## How it works now

- **Pause-and-step.** Lua pauses the emulator on each decision frame (`client.pause()`, frozen heartbeat, 5 s watchdog) and the choice applies from the observed frame. Decisions run every **6 game frames** (`--interval`).
- **Whole object table.** WRAM `0x1000..0x1FC0` holds 0x40-byte records; bytes 1..3 are a routine address that identifies the type. `TableTracker` classifies every record: helicopters `$02:B04A`, enemy bullets `$04:F97F` (blue or orange), weapon power-up `$04:FABA`, screen-clearing power-up `$04:FAD9`, tanks `$02:9274` and `$02:90F0..9203`, turrets `$02:93DD`.
- **What Jev is given per option** (all computed, none of it a tactic): closest tracked threat and its direction; whether that gap sits inside the measured 9-22 px collision range; which targets a shot fired from there would hit and when; the aim error to the nearest reachable target; targets ahead and behind, with the distance to slip past the nearest behind; nearest threat ahead and behind separately; how many targets drift into the gun's line within 30 frames if it holds that position; where the move ends; room from the entry side and room to fall back; what the nearest threat closes to if it stays; and the measured terrain floor there.
- **Whole-field map.** `field_forecast_next_30_frames` gives a 4x8 grid over the flyable area with, per cell, the targets that would cross the gun line within 30 frames and how close threats would come.
- **Re-plan trigger.** If a threat appears where none was tracked, or the closest gap halves against what Jev was shown, Lua pauses on the next frame and Jev is asked again.

## Terrain: the open problem

Terrain is **not** in the object table and is now the main damage source; most remaining hits have no tracked object within 36 px, always while flying low (Y 174-191).

- **Level scroll position is WRAM `0x007B`** (16-bit, +0.5 px/frame), exported as `scroll_x`. `level column = player_x + scroll_x`.
- `build_terrain_map.py` builds `terrain_map.json` from past runs: per 4 px level column, the lowest altitude flown without an untracked hit and the altitude of any untracked hit. The request reports that per option. **Rerun it after new runs** to extend coverage: `python build_terrain_map.py`.
- `build_terrain_profile.py` tried to read the ground surface from screenshots; **it does not work** because colour cannot separate collidable ground from background art (it returns the mountains at Y 103-128). Kept only as a record of the approach.
- Next: keep growing the measured map, and extend it into the boss section once runs get that far.

## Running it

```powershell
run_jev_segment.bat                # live: stepped, firing prelude, interval 6, max 300 requests, 1800 frames
python run_segment.py --mode dry --stepped --prelude-fire --interval 6 --max-calls 300 --frames 1800
python run_segment.py --mode baseline --prelude-fire --frames 1800
python analyze_segment.py runs\<run> --baseline runs\<same-settings baseline>
python build_terrain_map.py        # after runs, to extend the terrain map
python -m unittest test_bridge test_brain test_combat   # 56 offline tests
```

Discovery tools: `probe_hazards.py --modes replay --replay-run runs\<run>` (exact replay with full-WRAM capture), `survey_objects.py <capture>` (object table by routine address), `render_object_types.ps1`, `render_run_track.ps1`, `analyze_aircraft_slot.py`, `replay_brain.py --combat`.

## Rules that still hold

- **Slot 1 must hash `c1ea750e...`** (game frame 20183). `run_segment.py` refuses to start otherwise. A stray save state overwrote it once; BizHawk's `.bak` held the original. The emulator directory and save states are not in the repository.
- `typesafe_api_key.txt` stays local and ignored; only `play_segment.py --mode live` reads it. Never print or commit it.
- Carl approved paid requests (free tier). This session used about 5,700.
- The runners refuse to start if an emulator is already open and close only their own process. Stop with Ctrl+C or `stop_segment.bat`.
- Keep the D/L calibration in `bridge.py`/`launch.bat` working; it never sends a freeze.
- Evidence discipline: adopt an object type only after checking it against screenshots in two recordings, and keep health/damage/death unmapped. The hit marker (`$04:F8A1` in slot `0x1040`) is a candidate used only to count outcomes after a run.
- Avoid overfitting to this stretch of level 1: stage facts are counted at runtime, thresholds are relative, and tactics belong to Jev rather than to code.

## Next steps

1. Repeat runs to get distributions; single runs still swing between 36 and 42 kills and 1 to 6 hits.
2. Grow `terrain_map.json` from every run and check whether terrain hits keep falling.
3. Aircraft collisions are the other damage source; they happen when Jev works the right side.
4. Extend past frame 22463 toward the boss, surveying new routines from a replay capture before Jev sees them.

## Pasteable restart prompt

```text
Continue this Windows U.N. Squadron project. Read CLAUDE_HANDOFF.md, the current PROJECT_STATE.md checkpoint, MEMORY_MAP.md, and hazard_observation/OBJECT_TYPES_2026-09-19.md. The controller uses pause-and-step with decisions every 6 game frames, classifies the whole WRAM object table by routine address (helicopters, bullets, both power-up types, tanks, turrets), and gives Jev measured shot geometry, a 30-frame whole-field forecast, squeeze and position facts, and a measured terrain map keyed by scroll position (WRAM 0x007B). run_jev_segment.bat runs 1800 frames with up to 300 requests. Best runs destroy 36-42 units with 3 hits; terrain is the main remaining damage source and level 1 is not finished.

Next: repeat runs for a distribution, rebuild terrain_map.json with build_terrain_map.py after each batch, reduce aircraft collisions on the right side, and extend past frame 22463 toward the boss, surveying new object routines from a replay capture first. Keep slot 1 at hash c1ea750e..., keep health/death unmapped, and do not hard-code tactics.
```
