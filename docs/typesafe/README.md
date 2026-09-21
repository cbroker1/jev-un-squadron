# TypeSafe / Jev documentation, saved locally

All 109 pages of https://docs.typesafe.ai were fetched on 2026-09-20 so changes to this
project could be checked against the vendor's own guidance instead of assumption. The pages are
TypeSafe's, so they are kept locally and **not redistributed in this repository**: only this
summary is tracked. Read them at https://docs.typesafe.ai (the page index is
https://docs.typesafe.ai/llms.txt). The file names cited below are paths on that site.

## The rules this project is currently breaking

Read before changing how requests are built. Each line is the documentation's position,
followed by what this project does today.

| Documentation | This project |
|---|---|
| "Jev is not a calculator. We strongly recommend **implementing any mathematical logic in code**." (`model-jaggedness/jev-1.13.md`) | every option carries about 1,600 characters of numbers - pixels, frames, percentages - and Jev is asked to weigh them |
| "Break complex problems into **atomic questions**… don't hide multiple judgments behind one question" (`concepts/how-to-build-with-system-one.md`) | one `movement` question conflating dodging, attacking, positioning, power-ups, terrain and the boss method |
| "Ask many independent questions together… they execute in parallel with little effect on response time"; measured 12x cheaper and 10x faster (`cookbooks/parallel_questions.md`, `patterns/fan-out.md`) | one question per call, about 1,300 calls in a full run |
| "Large states containing unrelated information act as **distractors and degrade accuracy**… context rot" (`model-jaggedness/jev-1.13.md`) | about 22 KB per request |
| "Keep instructions short" (`concepts/how-to-build-with-system-one.md`) | 6,489 characters of instructions |
| criteria as objects with `what`, `not_for`, `examples` (`primitives/advanced.md`) | 1,600-character prose blobs |
| confidence below 0.5 means do not act on it (`confidence.md`) | measured confidences run 0.19 to 0.5 and every answer is acted on |
| `Score` for ordered judgments, `Noul` for yes/no (`primitives/score.md`, `primitives/noul.md`) | neither is used |

## Facts worth keeping in mind

- Endpoint `POST https://api.typesafe.ai/v1/systemone`, bearer auth, model `jev-latest`
  (currently `jev-1.13.0`). Input $0.042 per million tokens; output free.
- 64k tokens of context per request; state plus the longest question must fit in 32k.
- Choice takes up to 255 options; Score takes 2 to 10 levels; Noul is a single 0-1 value
  that is a probability of yes, not a degree.
- Confidence is computed from the shape of the distribution:
  `(count x peak - 1) / (count - 1)`. Flat distribution means the model is unsure.
- Rate limits: 1,200 requests a minute, 250k tokens a second. 429 and 529 want backoff.
- Known weak spots besides arithmetic: dates and durations, multi-hop reasoning, double
  negatives, and literal reading of scoping words - state conditions explicitly.
- Answers are not guaranteed consistent when two options sit close together; the
  consistency cookbook raises agreement from 90.8% to 99.2% by refusing to act below a
  probability threshold.
