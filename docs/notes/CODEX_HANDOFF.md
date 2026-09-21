# Codex handoff - 2026-09-20

Read this before resuming, then `CLAUDE_HANDOFF.md` for the earlier history and
`AUDIT_2026-09-20.md` for the closed VRAM investigation. Update this file at every
meaningful checkpoint; Carl expects work to survive a usage interruption.

## User request and current objective

Carl accepted the recommendation to use Astra / Extra High for the next Jev redesign
and boss investigation, and explicitly requested a maintained handoff. The gameplay
goal remains every level-1 unit destroyed with zero damage. Neither level completion
nor a destroyed boss part has been demonstrated.

Active work: redesign the Jev decision interface using computed comparisons,
categorical facts, independent questions, and measured uncertainty handling. Preserve
the current controller as a comparison mode until live evidence supports replacement.

## Latest checkpoint: opt-in implementation passes offline tests; live tests next

- Added `brain/decisions.py`, policy `categorical-v1`: three parallel Choices for
  attack, pickup, and positioning. Python computes eligibility, numerical
  comparisons, objective selection, and deterministic fallback candidates.
- `run_segment.py --policy categorical-v1 --stepped` selects it. Default remains
  `legacy`. Raw answers, selected objective, raw move, actual move, fallback reason,
  and policy/code hashes are recorded. `jev_fallback` commands are counted separately.
- Confidence floor is an experimental 0.5. A fallback only repeats a previous move
  if it remains both eligible and among the objective's computed best candidates.
  Starting inside a collision band uses endpoint clearance to find an escape.
- Restored analysis for 22 existing runs R100-122 (R114 has no applicable validation).
  R120, R121, and R122 each have ONE hit marker. All still have zero boss parts killed.
- The runner now writes analysis even when validation reports death/guard failure.
  Benchmark has separate `--entry full` (default), `--entry boss`, and `--entry practice`
  comparisons, warns about missing analysis, and reports partial exposure. Boss
  practice entries after frame 24040 are now counted.
- 109 tests pass: `python -B -m unittest test_decisions test_benchmark test_bridge test_brain test_combat test_dashboard`.
  Includes API answer validation, fallback safety, collision escape, and the actual
  pause/ack loop with synthetic replies. These are NOT gameplay evidence.
- Ran both full and boss benchmarks after changes; these still describe old policies.
  No live categorical-policy run has happened yet. Do not promote it on unit tests.

Next: inspect saved-state request sizes, run a short dry emulator check, then matched
bounded live legacy/categorical experiments from slot 1 and slot 3. Use explicit
`--change` labels and keep default legacy unless repeated play justifies promotion.

### Experiment checkpoint

- Rebuilt categorical requests for all 1,015 R99 and 185 R122 decisions without HTTP.
  Median bytes: R99 21,779 -> 4,201 (-80.7%); R122 20,133 -> 4,538 (-77.5%).
  A representative body is `data/samples/categorical_request_example.json`.
- R123 dry categorical bridge check: PASS, zero HTTP requests, five mock decisions,
  no game frames elapsed while deciding, input readback and save hash confirmed.
- R124 is the first fresh live legacy comparison: slot 1, prelude fire, interval 3,
  900-frame budget, 340-call cap, change label `redesign A/B opening 900f baseline legacy; replicate 1`.
  COMPLETE: 25/31 units (81%), two hit markers, full 900 frames; validation PASS.
  Median request 24,166 bytes; median latency 333 ms.
- R125 COMPLETE with the same start/budgets, categorical-v1 replicate 1:
  26/32 units (81%), two hit markers, full 900 frames, validation PASS.
  Median request 4,135 bytes (-82.9% vs R124); median latency 269 ms (-19.2%).
  186 applied Jev moves and 98 applied fallback moves. One pair is not evidence
  of a reliable gameplay gain. R126 (legacy replicate 2) is now running.
  Planned comparison is three replicates per policy, interleaved. Do not tune the
  categorical policy between those runs; diagnose and version subsequent changes.
- R126 COMPLETE (legacy replicate 2): 23/32 units, one hit, full 900 frames, PASS;
  median 24,956 bytes / 335 ms. R127 COMPLETE (categorical replicate 2): 21/32,
  two hits, 900 frames, PASS; median 4,145 bytes / 257 ms, 90 fallback commands.
  Gameplay benefit is NOT established. Default must remain legacy. R128 (legacy
  replicate 3) is running; R129 should be categorical replicate 3 at identical budgets.
- Dashboard now distinguishes the active question's raw Jev choice/probabilities
  from the applied fallback move and labels the fallback reason. Its 12 tests pass.
- Current offline suite: 110 tests pass (added a final-frame event regression check).

### New finding: damage before the first decision

Both R124 and R125 record the first hit at frame **20582**, during the fixed firing
prelude. The first decision is frame 20663. This prelude therefore already prevents
a zero-hit run from this setup. Preserve it for the current matched comparisons,
then test an earlier control start (shorter `--warmup`) as a SEPARATE experiment.
The save's origin is 20183; no need to write any save to test earlier control.

Each first-pair run also has one later tank-associated hit: R124 at 21147, R125 at
21142. In R125, all candidate paths were already inside the measured collision band
and the escape calculation admitted left. Its selected question confidence was .98,
reinforcing that confidence is not a collision probability. Inspect the few decisions
before entering the band for a future anticipation experiment; do not change v1 mid-batch.
Immediate action reversals: R124 61/257 transitions, R125 29/283. One pair only.
- Added `compare_runs.py LABELS... --output runs/comparison.json` for explicit
  matched comparisons. It checks starts/budgets, measures units/hits/exposure,
  request bytes/latency, and separates applied fallback commands. Missing analysis
  is an error, never a zero outcome. Use this for A/B pairs, plus `benchmark.py`.

## Initial investigation

The working tree was clean when this work started.

Verified directly from source and saved artifacts:

- R97: 50/58 units, 3 hit markers, ended at 22613. R99: 82/108, 4 hit markers,
  ended at 24271. Both tested walls remembered for the whole run.
- The audit's missing-memory finding is partly resolved: `combat_digest` receives
  recent choices and `combat_request` supplies the last eight plus reversal counts.
- R122 (`runs/combat-20260920-172114-e2475a-live`) used one `movement` Choice,
  8,036 instruction characters and a median request size of 20,133 bytes.
  Across 185 responses, confidence min/median/max = 0.07/0.28/0.84;
  90.8% were below 0.5. No confidence gate is applied in `play_segment.py`.
- `benchmark.py --recent 3 --baseline 12` currently scores R97-99 despite runs
  through R122. Latest boss practice runs lack `decision_trace.json`; they are
  silently excluded. Its current report flags opening and boss-segment kills.
  Boss-segment kills include other enemies, not just boss parts.
- Missing decision traces mean hit counts are UNKNOWN, not zero. Do not report
  unanalysed R120-122 as clean runs.
- Duplicate `boss_body` definitions, state fields, and boss instructions exist in
  `brain/combat.py`. They have not been changed.

## Next actions

1. Read live TypeSafe API / primitive guidance and establish offline test baseline.
2. Restore analysis coverage for existing boss runs and make benchmark omissions
   visible; compare practice runs separately from full-level entries.
3. Add an opt-in compact decision policy, retaining legacy behavior for A/B runs.
   Compute numerical comparisons in Python; give Jev explicit categorical facts.
   Keep independent judgments in one request, with logged composition and fallbacks.
4. Test on recorded states and offline controller tests, then bounded live A/B runs.
   Record run numbers, labels, outcomes, and request sizes here. Promote only with
   evidence; an experimental policy may remain opt-in if it regresses.

## Constraints and lessons

- Slot 1 is read-only and must retain the canonical `c1ea750e...` SHA-256.
- Never print or commit `typesafe_api_key.txt`, or shadow the `key` parameter inside
  `play_segment.run`. There is a regression test for that exact error.
- Keep pause-and-step, freshness checks, STOP handling, bounded calls, and saved
  telemetry. Run `benchmark.py` after changes and distinguish stale comparisons
  from actual tests of the changed policy.
- The VRAM alignment investigation is closed negative. Do not reopen without new
  PPU register evidence / an appropriate emulator core.
- The TypeSafe skill notes that confidence is distribution concentration, not a
  safety estimate. Several equally good actions can produce low confidence. Test
  confidence thresholds on these data; retaining an action must recheck its current
  measured collision constraints.
- No subagents are authorized by the current user request. Emulator experiments
  must run sequentially; preserve any emulator already open.

## Useful commands

```powershell
python -m unittest discover -s tests -t tests
python src/benchmark.py --recent 3 --baseline 12
python src/runs_table.py --last 12 --full-level-only
python src/run_segment.py --mode live --stepped --prelude-fire --interval 3 --max-calls 2400 --frames 6000 --change "description"
python src/run_segment.py --mode live --stepped --prelude-fire --interval 3 --max-calls 400 --frames 1000 --load-slot 3 --expected-start-frame 24121 --warmup 12 --change "description"
```

Offline tests pass as recorded above; gameplay improvement remains untested.
