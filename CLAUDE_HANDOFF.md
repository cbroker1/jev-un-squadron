# Handoff - 2026-09-20, America/Chicago

Later work and the current resume checkpoint are in [CODEX_HANDOFF.md](CODEX_HANDOFF.md),
and the 2026-09-20 write-up is in [SESSION_2026-09-20.md](SESSION_2026-09-20.md).
Read those before treating the status below as current: damage is now scored by health
lost, not by the hit-marker heuristic that file still refers to.

## Where this stands

A bounded controller plays U.N. Squadron level 1 with Jev choosing movement every 3 game
frames. **Level 1 is not finished and the boss has never been killed**: no boss part has
ever been destroyed. Carl's goal is every unit on the level destroyed with the aircraft
untouched.

Best measured results, from `runs_table.py`:

| Run | Units destroyed | Share | Hits | Reached | What it was testing |
|---|---|---|---|---|---|
| R99 | **82 / 108** | 76% | 4 | 24271 | walls remembered for the run |
| R97 | 50 / 58 | **86%** | 3 | 22613 | walls remembered for the run |
| R89 | 80 / 109 | 73% | 4 | 24328 | going back counts the drop |

Boss attempts from the practice save, mean frames survived in the fight:
184 baseline, 269 with the quiet altitude, 382 holding off the hull at the bottom left,
best single attempt 566.

## Read this before changing how Jev is asked

`docs/typesafe/` holds all 109 pages of the vendor documentation, fetched 2026-09-20, with
`docs/typesafe/README.md` listing the rules this project currently breaks. The short
version, and the most promising work left:

- Jev **cannot do arithmetic or numeric comparison** - the documentation says to do it in
  code. Every option currently carries ~1,600 characters of numbers for Jev to weigh.
- Questions should be **atomic**, and many can be asked in **one call in parallel** for
  almost no extra latency. This project asks one overloaded question per call.
- Large irrelevant state **degrades accuracy**; requests are ~22 KB with 6,489 characters
  of instructions.
- Confidence below 0.5 means do not act; measured confidences run 0.19 to 0.5.

The redesign that follows from this: compute the comparisons in code, hand Jev short
categorical verdicts, split the one movement question into several atomic questions in the
same call, and use confidence to fall back to the previous action.

## What actually moves the numbers

Measured, repeatedly: **facts help, instructions hurt.** Five instructions written by the
agent each cost kills and were reverted (36, 41, 37, 13 kills). Every measurement added
helped. Carl's own corrections - turrets first, boss parts vulnerable, ground targets
reachable with a small drop, hug the ground and hold the bottom left - have all been right
and are attributed where they appear in the request.

## How it works

- **Pause-and-step**: Lua pauses the emulator on each decision frame, so no game frames
  elapse while Jev thinks. Frames between decisions run at 100% speed.
- **Object table**: WRAM `0x1000..0x1FC0`, 0x40-byte records, bytes 1..3 a routine address.
  Helicopters `$02:B04A`, bullets `$04:F97F`, power-ups `$04:FABA` and `$04:FAD9`, tanks,
  turrets, the fortified line's `$02:9649` shells, and the boss: `$04:C4FC` is its
  straight-flying invincible fire (turns in 4% of frames), `$04:C559` its small turning
  missiles (92%), `$04:C3B1`/`C3E6`/`C005`/`C5E6` the hull.
- **Firing**: the gun fires right along the aircraft's own line at 11 px/frame, capped by
  the weapon at about six shots a second whatever the pulse. Measured kill bands: ground
  targets from 6 px above to 10 px below, aircraft from 8 above to 17 below.
- **Walls**: shots that stop short with no destroyed marker beside them are recorded by
  level position and kept for the rest of the run (two stops make a wall, one does not).
  The offline map in `terrain_map.json` adds columns confirmed across runs.
- **Maps**: `danger_map.json` (where runs died and were hit, per position and altitude,
  with the boss keyed by screen position because the scroll counter wraps there),
  `terrain_map.json` (structures and recorded collisions).

## Tools

```powershell
dashboard.bat                       # http://127.0.0.1:8770, follows runs by itself
python run_segment.py --mode live --stepped --prelude-fire --interval 3 --max-calls 2400 --frames 6000 --change "what this run tests"
python run_segment.py ... --load-slot 3 --expected-start-frame 24121 --warmup 12   # boss practice, a minute an attempt
python runs_table.py --last 12 --full-level-only     # units, share, hits, change under test
python benchmark.py --recent 3 --baseline 12         # per-segment regression check
python replay_run.py --best-boss                     # watch a run back
python build_danger_map.py; python build_terrain_map.py
python -m unittest test_bridge test_brain test_combat test_dashboard    # 97 offline tests
```

## Rules that still hold

- **Slot 1 must hash `c1ea750e...`** and is never written. Slots 2 and 3 are practice
  entries (fortified line at 22200, boss at 24121), reproducible with `lua/probe_save_at.lua`.
- `typesafe_api_key.txt` stays local; never printed or committed.
- Never name a local variable `key` inside `play_segment.run` - it shadows the API key and
  has broken runs twice. `test_bridge` now fails if anything does.
- Evidence discipline: adopt an object type only after two recordings agree; keep health
  and death unmapped beyond the run-ending guard; do not claim level completion.
- Run `benchmark.py` after every change. Gameplay regressions do not show up in unit tests.

## The VRAM terrain thread is closed, negative

Reading stage geometry from VRAM tilemaps was pursued to a conclusion and does not work
with this emulator core: the best alignment found over ~900 configurations scores 92%
against a null model that only knows "sky above, content below" at 93%. Details and the
four other disproved approaches are in `AUDIT_2026-09-20.md`. It would need the PPU's own
BG registers, which Snes9x here does not expose; bsnes or Mesen would settle it.

## Next

1. The Jev redesign above, measured with `benchmark.py` and `runs_table.py`.
2. The boss: parts absorb hits and none has ever been destroyed; attempts now last long
   enough to study from slot 3.
3. Ground tanks sit at 4 to 6 of 12 destroyed, the worst non-boss rate.
