# Drone Backend — Week 1 Report (Aug 26 → Sep 2)

*From Sai — I can't make the meeting, so here's everything the backend did
this week, in plain language. Details and receipts: EXPERIMENTS.md in the
repo (github.com/himagna16/pytorch-ssd).*

## What we did

**1. Made David's work run on our machines.** Rebuilt the whole training +
quantization environment from scratch, fixed the version problems, and
wrote setup guides so anyone's coding agent can replicate it (Grace on
Intel Mac and Oaj on Windows/Linux both succeeded — and both found real
bugs in our docs that are now fixed).

**2. Reproduced the thesis, then beat it.** Every result in David's thesis
now reproduces on team hardware. We then trained better models using his
own training system: our best scores **0.8008** accuracy (quantized, the
form that actually runs on the chip) vs his **0.789**.

**3. Put our model on the (simulated) chip.** Our champion went through the
full pipeline — quantization → code generation → GAP8 build → chip
simulator — and produced **exactly** the right 14 output numbers, verified
bit-for-bit. It's now the repo's official deployed application. Getting
there required fixing **5 bugs in the release pipeline** (one had David's
home folder hardcoded — it literally couldn't run on anyone else's
computer before this week).

**4. Found and fixed the scariest real-world failure.** Error analysis
showed the model confidently mistakes **cats, dogs, mannequins, and teddy
bears** for people (24% false-alarm rate) — i.e., the drone would chase
your cat. We retrained with those images emphasized: false alarms dropped
**3x (24% → 8%)**, costing only half a point of accuracy.

**5. Verified everything twice.** Grace independently reproduced the
champion's exact chip validation on her machine; Oaj reproduced the setup
on Linux. Nothing rests on one person's laptop.

## Where we stand

| model | accuracy (quantized) | chases-the-cat rate | status |
|---|---|---|---|
| David's released | 0.789 | 24% | superseded |
| **Champion** | **0.8008** | 24% | deployed, chip-validated |
| **Confuser model** | 0.795 | **8%** | chip-validated, ready |

Both models are one command away from deployment — **the team's decision is
which one ships** (suggestion: the safer one, for indoor flying). We also
proved combining both strengths cheaply doesn't work (documented honest
negative results), and wrote the **firmware spec** (docs/firmware_contract.md)
so Jade/Koa/Calvin can build the flight controller against the model's
14-value output, with ready-to-use C code.

## Three next steps

1. **Simulator first (Prof. Mok's directive):** schedule the Zoom with
   MinHyuk and work through his simulator
   (github.com/dmz44/Crazyflie_Simulator_Container) before touching
   hardware. Sai + Grace to send availability.
2. **Finish Grace's study + pick the shipping model:** Grace is measuring
   whether the deployed app loses accuracy in the release process (if yes,
   a small fix upgrades it for free). With that answered, the team picks
   champion vs confuser model.
3. **Real-camera data once we have the drones:** capture a few hundred
   frames from the actual AI-deck camera (MinHyuk pre-patched the firmware
   — image capture already works) and fine-tune on them. Our training
   images are internet photos; the real camera is different, and published
   work shows this step gives the single biggest accuracy gain available.
