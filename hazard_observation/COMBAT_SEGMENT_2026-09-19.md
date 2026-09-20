# Bounded combat step - 2026-09-19 (machine local date)

Handoff entry: [CLAUDE_HANDOFF.md](../CLAUDE_HANDOFF.md). Current truth: [PROJECT_STATE.md](../PROJECT_STATE.md), [MEMORY_MAP.md](../MEMORY_MAP.md).

## Verdict

Real progress from target calibration to a threat-informed typed Jev choice reaching the controller. **No successful five-choice combat segment, avoidance improvement or level clear is demonstrated.** Orange aircraft visible near the player are missing from the current observation set. Health/liveness and collision geometry remain unknown.

The TypeSafe skill guided separation of responsibilities: memory/tracking and consequence calculations in code, a small typed movement Choice in Jev, and explicit provenance in controller logs. The original D/L calibration is preserved. API endpoint/Choice structure were checked against current official TypeSafe documentation during implementation.

## Run ledger

All paths below are under `runs/` unless noted. Manifests contain ROM/save/source hashes. Every owned emulator closed normally; slot1 remained unchanged; configured and traced speed was50%.

| Run ID | Result | Paid attempts |
|---|---|---:|
| combat-20260919-130644-93e680-dry | Initial mock path reached an explosion/fade and out-of-bounds guard; failed intended completion. Original validator also mistook one no-input-poll frame for mismatched input. Evidence preserved. | 0 |
| combat-20260919-131409-e5b8a8-dry | Changed mock sequence and corrected readback test passed. | 0 |
| combat-20260919-131603-d08866-dry |900ms mocked delay; reply aged28frames rejected, no model movement injected, STOP acknowledged. | 0 |
| combat-20260919-131730-aec2da-baseline | Same-save, frame-anchored neutral prelude then Y-only baseline; normal end20873. | 0 |
| combat-20260919-131829-5ea5e4-dry | Final five-choice mock loop passed controller readback, frame leases, speed, STOP and shutdown checks. | 0 |
| combat-20260919-131922-c4e603-live | Two real Left choices applied; third request in flight when player-position guard stopped at20732. Five-choice objective failed. | **3** |
| hazard_observation/probe_20260919-132216-1dd64b_pulse8 | Offline replay:660frames,77 RAM/image snapshots,549 input frames identical to live prefix. Reproduced guard transition. | 0 |

The live budget was five attempts; three were used. No extra paid calls were made to fill the quota, and none during handoff.

## Actual Jev trace and timing

See [decision_trace.json](../runs/combat-20260919-131922-c4e603-live/decision_trace.json), [events.jsonl](../runs/combat-20260919-131922-c4e603-live/events.jsonl) and [inputs.csv](../runs/combat-20260919-131922-c4e603-live/inputs.csv).

| Attempt | Observation -> response -> first input | Reply latency | Observed effect |
|---|---|---:|---|
| 1 |20663 ->20678 ->20679 |473.55ms | Left consumed for24frames; X96->36, Y112 unchanged. Matches measured cardinal motion. |
| 2 |20693 ->20702 ->20703 |269.38ms | Left consumed for30frames; X36->16 then15 during the guard transition. Do not interpret the animation as controllable travel or mapped death. |
| 3 |20723 -> unknown -> not applied | unknown | In-flight request counted; older worker did not retain its result after stopping. |

Requests contained2aircraft/1bullet tracks for the first two snapshots,2aircraft/0bullets for the third, plus computed movement consequences. This is incomplete coverage, not a claim no other threats existed. No deterministic movement override was attributed to Jev.

Observed request intervals30game frames; observation-to-input16/10frames, including1bridge frame. The controller does not sleep an extra decision interval after receiving a reply. A30frame lease can be superseded earlier. Forecast horizon is30frames, but future motion and API delay remain estimates; the earlier zero-error forecast experiment only validated a particular20frame trajectory. No pause-and-step implementation or real-time survival claim was added.

Screenshots actually inspected include [first movement](../runs/combat-20260919-131922-c4e603-live/frame_20697_call_22.png), [left edge](../runs/combat-20260919-131922-c4e603-live/frame_20721_call_23.png), and the offline replay [explosion sequence](probe_20260919-132216-1dd64b_pulse8/frame_0554.png). Core requested and polled masks matched; command JSON alone was not treated as proof.

Baseline comparison found494identical pre-movement observation packets and24byte-identical screenshots. This establishes a comparable starting prefix, not survival improvement. Damage, kills, pickups and level-clear metrics remain null.

## Offline orange investigation and conclusion

The gate transition was reproduced without Jev. X15 at sample550 and14 at552/554 are outside the tested normal-control range; later motion/explosions occur after directional release. Keep the conservative stop rather than extending the validated control range.

Existing neutral captures and this independent replay were measured for orange sprite fragments. The ranking tested a three-byte X/Y separation as a hypothesis. It did not enable new slots. Candidate1851/1854 has104neutral and46replay matches and inspected orange-aircraft coordinate evidence at several positions:

- [neutral candidate contact sheet](probe_20260919-114543-d95c1f_neutral/orange_1851_neutral_reference.png)
- [independent Left/firing contact sheet](probe_20260919-132216-1dd64b_pulse8/orange_1851_left_replay.png)

Ungated neutral780/820 are phantoms after candidate base1840's leading byte becomes00. Candidate17D1/17D4 also fails ungated independent replay. These failures make activity/lifetime validation necessary; do not promote high correlation counts into a persistent object map. Exact addresses, observed headers and next acceptance test are in the handoff and MEMORY_MAP.

## Code/test boundary at handoff

New combat runner, typed request builder, observation additions, offline analysis helpers and launchers are implemented.41offline unit tests and Python compilation pass. Lua/runtime evidence comes from the listed actual runs, not compilation.

After the real run, the worker was amended to retain typed results discarded after STOP without applying them; no new real HTTP experiment tested that drain branch. Its third historical reply remains unknown. The final documentation distinguishes this change from run-verified behavior.

No processes were left running by these experiments. Single next experiment: validate orange-aircraft activity/lifetime gating using the two existing recordings, with zero API requests. Do not begin power-ups, shops, special weapons or a larger policy yet.
