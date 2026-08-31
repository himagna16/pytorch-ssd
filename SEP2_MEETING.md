# Team Meeting — Sep 2, 2026 · Backend Report & Agenda

Prepared by Sai (backend / Role 1). Full experimental record: EXPERIMENTS.md.
Repo: github.com/himagna16/pytorch-ssd (`main` = docs/tools/results,
`successor-release` = the deployed application).

## 1. Executive summary (the 60-second version)

In the ten days since the team formed, the backend has: reproduced every
result in David's thesis independently on our own hardware; trained a model
that **beats his released model** on both accuracy and quantization
robustness; **deployed that model through his full release pipeline** with a
bit-exact GVSOC (simulated GAP8) validation — it is now the repo's official
application; made the pipeline **portable off David's machine** for the
first time (5 bug fixes); and identified + 3x-improved the model's worst
real-world failure mode (chasing pets/mannequins).

## 2. What happened, in order

- **Reproduction**: environments rebuilt from scratch (macOS, torch 2.2.2
  team pin), thesis claims replicated: bin heads preserve decoded commands
  under quantization; straight-through backbones export cleanly.
- **David's handoff verified**: SHA-256 integrity PASS; his released
  checkpoint scored through our independently built audit matches his
  published numbers (15/16 x-bin preservation) — two toolchains agree.
- **Successor training campaign** (his training stack + our compute):
  warm-start and from-scratch runs both beat his released model; a
  quantization-aware (QAT) fine-tune produced the current champion.
- **Deployment**: champion released end-to-end (NEMO export in a
  containerized copy of the thesis-era environment → DORY codegen → GAP8
  build → GVSOC), integrity gate PASS, 14/14 output values exact.
- **Error analysis → targeted fix**: misses are mostly tiny background
  people (operationally irrelevant); the real hazard is confident false
  positives on animate non-persons. A confuser-skewed retrain cut that 3x.
- **Two honest negative results**: further QAT continuation plateaued
  (accuracy axis is squeezed at ~0.80); stacking QAT *after* the confuser
  fix erases the fix (ordering matters).

## 3. The scoreboard (all numbers = quantized deployed form, val2017)

| model | peak F1 | animate-confuser FP rate | status |
|---|---|---|---|
| David's released (baseline) | 0.789 | 0.239 | superseded |
| **QAT champion** | **0.8008** | 0.239 | **deployed & silicon-validated** |
| **Confuser model** | 0.7947 | **0.083** | operational-safety candidate |

Supporting facts: the 16-image drift audit proved to predict full-set
quantization degradation exactly (audit 16/16 → 0.00 F1 loss; 14/16 →
0.55 loss). Champion's chip output on the golden image decodes correctly
(visible / centered / close).

## 4. Decisions this meeting must make

1. **Which model ships to the drone**: the accuracy champion (0.8008) or
   the confuser model (0.795 but 3x fewer pet/mannequin false alarms).
   **Both are now GVSOC-validated with exact tensor agreement** — either
   choice is flight-ready, promotion is one command. Recommendation to
   discuss: for indoor flying, the confuser model; the champion remains
   the benchmark. (Reproduction status: champion's number independently
   confirmed by Grace — exact silicon PASS on an Intel Mac — and by Oaj
   on Linux/WSL.)
2. **Operating threshold + hysteresis**: sweep tables are in EXPERIMENTS.md;
   proposal on the table: visible >0.55 / lost <0.45 hysteresis to kill
   near-threshold flicker (~10% of frames sit in the risk band).
3. **Next training campaign, if any**: the one untested recipe is a joint
   QAT+confuser run from scratch (could yield a have-it-all model; needs
   either babysat 1-epoch chunks locally or a cheap rented Linux GPU —
   NEMO's QAT leaks memory on Apple GPUs). Alternative: freeze training
   until real drone-camera data exists (the biggest known win; blocked on
   hardware drop-off).
4. **Firmware interface**: the deployed 14-value int32 contract (x-bins
   0-8, visibility 9, size buckets 10-13) + decode rules — frontend team
   should confirm they build against this.
5. **Offering David a PR** with the 5 pipeline portability fixes (one had
   his home directory hardcoded — the pipeline could not previously run on
   any other machine).

## 5. Asks / coordination

- **Hardware**: drone + AI-deck drop-off date (David → Sai, arranged).
- **Grace (Role 2)**: second-machine reproduction of the release validation;
  then the QAT-alpha-preservation study (learned quantization parameters
  currently don't ship — open research question).
- **Oaj (evaluation/data lane)**: independent metric reproduction, curated
  evaluation packs, real-camera data-collection plan.
- **Prof. Mok**: guidance on framing (course credit / lab / club), and
  whether this arc (reproduce → beat → deploy → harden) fits a
  workshop-paper shape worth pursuing.

## 6. Presentation flow suggestion (10 min)

1. One slide/screen: the scoreboard table above (30s).
2. The two overlay galleries: what the model sees, what it gets wrong —
   ending on the mannequin/cat false alarms (2 min).
3. The deployment story: same 14 integers from the simulated chip and the
   laptop, twice over — what "validated" means here (2 min).
4. The trade-off decision (champion vs confuser) — open the floor (5 min).
