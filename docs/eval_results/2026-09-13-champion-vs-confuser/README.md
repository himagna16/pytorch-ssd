# Champion vs confuser, flown head to head — Sep 12, 2026

The team has to choose which network goes on a drone that flies near people.
Until this run that choice rested on **still-image** measurements, because
**every closed-loop flight ever run used the champion**. The confuser had never
flown. This is the missing half: both networks, the same six chip cells, the
same session, interleaved.

**Nothing here touched real hardware.** Every frame is rendered, and the "chip"
network runs under onnxruntime rather than on a real GAP8.

---

## 0. TL;DR

* The confuser **does what it was built to do**: on the dog it drifts 0.215 m and
  **passes** the 0.5 m gate, where the champion drifts 0.974 m and fails.
* The confuser **does not follow people**. It tracks a stationary person on
  **0.000** of frames, and fails both the heading and distance gates on the two
  person-following cells.
* Retuning the threshold does **not** rescue it. The champion at its own
  operating point is better than the confuser at **every** threshold on **both**
  axes at once (§4). Read §4's caveat with §4's result.
* **No recommendation is made here.** That is a team decision for Sai, Grace and
  David. This document is evidence.

## 1. Design

48 flights: 6 cells x 2 models x 4 repeats, **interleaved** model by model and
ABBA-counterbalanced, all in one session on the matte floor.

| property | value |
|---|---|
| flights attempted / valid | 48 / 48 (24 per model) |
| repeat vs chronological order | Pearson 0.0, Spearman 0.0 |
| mean flight order | champion 24.5, confuser 24.5 |
| max consecutive same model | 2 |
| matched pairs sharing a noise seed | yes |

**Which confuser.** `plain_follow_eval576_confuser`, chosen because it is the
only confuser on the same production line as the champion, it is the exactly
parallel 608-image re-gate of a byte-identical ONNX, and it passes all semantic
gates on the 500+ pack. The `qathn` variants were rejected as counterparts
because their false-alarm rates sit **at or above** the champion's, so they are
not "the confuser" in any useful sense.

> **Worth the team's attention:** `plain_follow_prod_confuser_final` *fails* the
> agreement gate at 96 images while the **same network** *passes* at 608. That
> earlier rejection was a small-sample artefact, not a property of the model.

**Both networks verified per flight.** Distinct ONNX hashes
(champion `d90555c8`, confuser `56ed6ee7`) and distinct output scales
(champion 2.009823510888964e-4, confuser 2.1179195027798414e-4) recorded in every
run's `summary.json`; the harness refuses to mark a flight valid if either does
not match its plan row. Flying one model with the other's scale would have been
silent and would have invalidated everything.

**Code pinned.** All five tool files byte-identical before the first flight and
after the last, and identical to the hashes used by the 14-cell baseline, the
stability run and the range sweep. One toolchain across the whole series.

**Machine health.** sim/wall 0.992–1.001, zero attitude upsets in 48 flights,
load ~4.7 throughout, worst step gap 183.9 ms (chip class, where the 153 ms rate
cap puts the floor near 158 ms by construction).

## 2. Verdicts

Champion 4 pass / 2 fail. Confuser 2 pass / 3 fail / 1 characterised.

| cell | champion | confuser | gates failed |
|---|---|---|---|
| A.static__ships | **PASS** | **FAIL** | confuser: heading max, settled distance, final in band |
| B.moving__ships | **PASS** | **FAIL** | confuser: heading max, settled distance |
| C.empty__ships | PASS | PASS | neither |
| D.occlusion__ships | FAIL | FAIL | both: relatch time |
| E.furniture__ships | PASS | PASS | neither |
| F.pets__ships | **FAIL** | **CHARACTERISED** | champion: drift 0.974 m vs 0.5 gate |

Gate values where either model failed:

| cell | gate | need | champion | confuser |
|---|---|---|---|---|
| A.static | heading err max | <= 12.0 deg | 4.435 PASS | 15.95 FAIL |
| A.static | settled dist err | <= 0.75 m | 0.397 PASS | 1.698 FAIL |
| A.static | final in band | == 1.0 | 1.0 PASS | 0.0 FAIL |
| B.moving | heading err max | <= 14.0 deg | 8.8 PASS | 29.055 FAIL |
| B.moving | settled dist err | <= 0.75 m | 0.519 PASS | 0.8235 FAIL |
| D.occlusion | relatch | <= 1.5 s | 4.8675 FAIL | 2.7635 FAIL |
| F.pets | drift | < 0.5 m | 0.974 FAIL | **0.215 PASS** |

## 3. The trade, in both directions

**The confuser's win is real.** On the pet scene:

| characterised metric | champion | confuser |
|---|---|---|
| false-follow episodes | 3.5 | **0.0** |
| total time false-following | 2.355 s | **0.0 s** |
| tracking fraction | 0.1305 | **0.0** |
| max confidence with no person present | 0.8755 | **0.7485** |

**The cost is that it does not do the job.** Tracking fraction with a person
present:

| cell | champion | confuser |
|---|---|---|
| A.static | 0.990 | **0.000** |
| B.moving | 0.972 | 0.104 |
| D.occlusion | 0.531 | 0.052 |

On `A.static` the confuser's numbers are *identical across all four flights*
(heading 15.95 deg, distance 3.64 m). That is the signature of a drone that
never detected anything and therefore never moved.

## 4. "You judged it at the champion's thresholds" — answered

A fair objection: the follower's 0.70 confirmation bar and 3-consecutive-frame
rule were not chosen with the confuser in mind, and its confidence sits lower
(mean 0.514 on a person in view, against the champion's 0.804). So the frames
these flights saw were re-scored at every threshold from 0.45 to 0.80.

Median latched fraction **with the person in view** (recall axis, higher better)
against **with no person in view** (false-alarm axis, lower better):

| threshold | champion recall | confuser recall | champion FA | confuser FA |
|---|---|---|---|---|
| 0.45 | 0.9904 | 0.5783 | 0.3936 | 0.1643 |
| 0.60 | 0.9904 | 0.2096 | 0.1087 | 0.0735 |
| 0.70 | 0.9904 | 0.0525 | 0.0176 | 0.0000 |
| 0.80 | 0.9729 | 0.0000 | 0.0000 | 0.0000 |

**The champion at 0.70 scores 0.9904 recall at 0.0176 false alarm. The
confuser's best recall at any threshold is 0.5783, and it costs 0.1643 false
alarm.** So the champion at its own operating point beats the confuser at every
threshold on both axes simultaneously. Even at the confuser's own selected
operating point (0.60) it reaches only 0.2096. Retuning does not rescue it.

> **CAVEAT, as important as the result.** This is an **open-loop re-scoring of
> the frames these particular flights saw**. Had the confuser latched, the drone
> would have moved and seen different frames. It **bounds** the question; it is
> not a prediction of a re-flown suite. The honest way to settle it completely is
> to re-fly the confuser with its threshold set to 0.45 or 0.60 and see what
> happens, which nobody has done.

## 5. What this does not prove

* **Anything about real hardware.** No AI-deck, no real camera, no Crazyflie.
* **That the confuser cannot be made to work.** It shows it does not work *as
  configured*, and that a pure threshold change does not fix it. A retrained or
  re-tuned confuser is a different question.
* **That the champion is safe.** It still fails the dog gate (0.974 m against
  0.5 m) and both models still fail the occlusion relatch gate.
* Subjects are flat cards, so behaviour at steep viewing angles is a scene
  artefact rather than a property of the networks (see the range sweep).

## 6. Files

`runs/` 48 flight directories, `scoreboards/` per-model suites, `scripts/` the
harness and analysis, `analysis.txt` per-cell paired metrics, `verdicts.txt`
the gate table, `threshold_sensitivity.txt` section 4's re-scoring,
`flights.jsonl` one record per flight with health and model provenance.

`progress.log` and each run's `follower.log` / `sim.log` match the `*.log`
ignore rule and were force-added when this was committed.
