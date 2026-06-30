<p align="center">
  <img src="https://img.shields.io/badge/status-experimental-orange" alt="Status">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/vibe-chill-blue" alt="Vibe">
</p>

# ❄️ ChillFlow

**What happens when you open the fridge?** The cold air doesn't just sit there —
it's heavier than the warm room air, so it spills out, pours down, and flows
across the floor like an invisible waterfall. ChillFlow is a little physics toy
that simulates exactly this: a pocket of cold air released into a warm room.
Watch it slump, spread, settle into layers, and slowly even out.

<p align="center">
  <a href="fridge_zoom.mp4"><img src="fridge_zoom.gif" alt="Fridge zoom animation" width="400"></a>
  <br>
  <em>Cold air (blue) pours off the shelf and races across the floor as a
  spreading "puddle" of cold. (<a href="fridge_zoom.mp4">full-resolution MP4</a>)</em>
</p>

---

## 📋 Table of Contents

- [The Idea in One Paragraph](#the-idea-in-one-paragraph)
- [Two Scenarios](#two-scenarios)
- [Quick Start](#quick-start)
- [Results](#results)
- [What It Gets Right (and What It Skips)](#what-it-gets-right-and-what-it-skips)
- [Under the Hood](#under-the-hood)
- [File Reference](#file-reference)
- [Make It Your Own](#make-it-your-own)
- [References](#references)
- [License](#license)

---

## The Idea in One Paragraph

Heat moves through a room in two very different ways. It can **seep** slowly from
warm spots to cold spots, the way a hot pan handle gradually warms up — that's
fine over centimetres but hopelessly slow across a whole room (it would take
*days*). Or warm and cold air can physically **swap places**: cold air sinks,
warm air rises, and the room mixes itself in *minutes*. ChillFlow simulates this
second, far faster process. Cold air falls, fans out across the floor, and ends
up in layers — cold below, warm above — before everything blends to one
temperature. The whole show is driven by a single fact: cold air is heavier than
warm air.

---

## Two Scenarios

Both use the same simulation — only the starting shape of the cold air differs.

| Scenario | Script | Where the cold air starts | What you see | Preview |
|---|---|---|---|---|
| **Fridge** | `Fridge.py` | A tall slab against the left wall, sitting on the floor | Cold air **fans sideways** across the floor | [`fridge_simulation.mp4`](fridge_simulation.mp4) |
| **Embedded** | `Embedded.py` | A cube floating in the middle of the room | Cold air **drops**, blooms into a mushroom shape, then spreads | [`embedded_simulation.mp4`](embedded_simulation.mp4) |

Once the cold air reaches the floor, both scenarios behave the same way — the
room "forgets" how the cold air got there.

---

## Quick Start

### Prerequisites

```bash
python3 -m pip install numpy scipy matplotlib pillow
# ffmpeg is needed for MP4 output (conda install ffmpeg or brew install ffmpeg)
```

### Run a simulation

```bash
# Fridge scenario (cold air fans across the floor) — 90 seconds
python3 Fridge.py

# Embedded scenario (cold cube falls and blooms) — 90 seconds
python3 Embedded.py

# Zoomed-in fridge (just the first 10 seconds, in finer detail)
python3 FridgeZoom.py
```

### Turn the results into videos and figures

Run `Fridge.py` **and** `Embedded.py` first — the rendering scripts read the
`fridge_run.npz` / `embedded_run.npz` files those produce.

```bash
# Videos + figures (run after the simulations above)
python3 render_mp4.py          # → fridge_simulation.mp4
python3 render_zoom.py         # → fridge_zoom.mp4
python3 render_comparison.py   # → fridge_panel.png, comparison_panel.png, embedded_simulation.mp4

# Hero GIF (made from the zoom video)
ffmpeg -i fridge_zoom.mp4 -vf "fps=12,scale=400:-1:flags=lanczos,palettegen" /tmp/pal.png
ffmpeg -i fridge_zoom.mp4 -i /tmp/pal.png -lavfi "fps=12,scale=400:-1[x];[x][1:v]paletteuse" fridge_zoom.gif
```

> **Note:** `render_comparison.py` currently points at the `.npz` files using
> absolute paths near the top of the file — edit those to match your setup
> before running it elsewhere.

### What you'll see in the terminal

```
Starting fridge simulation: 128×128 grid, 4500 steps, dt=0.02s
  T_warm=20.0°C, T_cold=4.0°C
  Cold block: x∈[0.15,0.75], y≤1.5
  t =    5.0s, step   250/4500, mean T = 18.396°C (init 18.438°C)
  t =   10.0s, step   500/4500, mean T = 18.397°C (init 18.438°C)
  ...
  t =   90.0s, step  4500/4500, mean T = 18.413°C (init 18.438°C)
Simulation finished in 18.7s (4500 steps)
Saved 19 snapshots to fridge_run.npz
```

Each run saves a `.npz` file with temperature snapshots and the settings used —
ready for your own analysis or rendering.

---

## Results

### How the room evolves

The simulation goes through four phases. The starting shape only matters for the
first one.

| Phase | Fridge | Embedded | What's happening |
|---|---|---|---|
| **1. Release** (0–5 s) | Slab slumps sideways | Cube drops like a stone | Cold air starts moving almost instantly |
| **2. Spread** (5–20 s) | Cold air fans across the floor | Mushroom bloom → hits floor → spreads outward | Cold air races along the ground |
| **3. Layering** (20–60 s) | Cold settles below, warm above | Same | Big movements die down |
| **4. Evening-out** (60–90 s) | Slowly blends toward one temperature | Same | Only slow mixing left |

### Tracking the falling cold cube (embedded scenario)

The cube's centre starts in the middle of the room (1.5 m up) and drops to the
floor within about five seconds:

| Time | Centre height | Floor temp | Phase |
|---|---|---|---|
| 0 s | 1.50 m | 20.0°C | Cube centred |
| 5 s | 0.76 m | 19.9°C | Falling — drops 0.74 m in 5 s |
| 10 s | 0.87 m | 17.0°C | Hits floor — floor cools 3°C |
| 20 s | 0.77 m | 16.5°C | Spreading across floor |
| 45 s | 0.84 m | 16.6°C | Settled into layers |
| 90 s | 0.93 m | 16.9°C | Slowly evening out |

<p align="center">
  <img src="comparison_panel.png" alt="Comparison panel" width="800">
  <br>
  <em>Side by side: fridge (cold air fanning sideways, left) vs embedded
  (falling cube, right) at matching moments.</em>
</p>

### Sanity check

The results were cross-checked against a separate, independent version of the
same toy. The cold air falls out of the centre within five seconds in both, the
mushroom-and-spread shapes match, and the four phases happen in the same order
over the same timescales. Total heat is also conserved: with the room sealed,
the average temperature barely drifts (a few hundredths of a degree over 90
seconds), as it should.

---

## What It Gets Right (and What It Skips)

This is a deliberately simple toy. Knowing what's left out matters as much as
knowing what's in.

**It captures:** cold air sinking and warm air rising, cold air spreading across
the floor, the room settling into temperature layers, and heat being conserved
in a sealed room.

**It skips:**

| Simplification | Why it matters |
|---|---|
| **Flat 2D slice, not full 3D** | A real falling blob of cold air forms a doughnut-shaped ring; in 2D it shows up as a mushroom. Real-world mixing is a bit more vigorous. |
| **Sped-up mixing** | The simulation smooths the air's swirliness so it runs cleanly on a modest grid. Shapes and the order of events are faithful; treat exact clock times as ballpark. |
| **No heat through the walls** | Walls are perfect insulators, so the room can't actually cool down toward the outdoor temperature. |
| **No humidity** | The visible "fog" rolling out of an open freezer isn't modelled. |
| **Instant release** | The cold air's container simply vanishes at the start — no door-opening motion. |

---

## Under the Hood

*For the curious — skip this if you just want pretty videos.*

The simulation tracks two things on a 128×128 grid: the **temperature** of the
air everywhere, and how the air is **swirling**. Each step it does roughly this:

1. **Buoyancy** — wherever cold air sits next to warm air, it starts to sink and
   the warm air starts to rise. This is the engine of the whole thing.
2. **Flow** — from that swirling, work out which way the air is moving at every
   point.
3. **Carry** — move the temperature and the swirl along with the flow (cold air
   gets physically carried to new places).
4. **Smooth** — let temperature and swirl spread out very slightly, the way heat
   naturally evens out.

The walls are sealed (air can't pass through and sticks at the surface), so no
heat escapes and total energy stays constant.

### Where it becomes linear algebra

Step 2 is the interesting one. "Work out the flow from the swirl" sounds vague,
but it's pinned down by one rule that has to hold at *every* grid point at once —
and each point's value depends on its neighbours. Write that rule out for all
128 × 128 points and you get a giant set of equations: ~16,000 unknowns, ~16,000
equations, all tangled together. In matrix form it's just **A x = b** — the kind
of linear system numerical linear algebra exists to solve.

So every single time step, the toy quietly solves a 16,000-equation system. Doing
that the naïve way would be far too slow, so ChillFlow uses a **fast transform**
(`scipy.fft`) that cracks this particular system in one shot — the same trick
behind fast Fourier transforms. That's the bottleneck step, and it's why a
physics toy ends up leaning on the same math as solving `A x = b` in a linear
algebra class.

### Settings used

| Setting | Value |
|---|---|
| Room size | 3.0 m square slice |
| Warm (room) temperature | 20 °C |
| Cold-air temperature | 4 °C |
| Grid | 128 × 128 points |
| Time step | 0.02 s |
| Simulated duration | 90 s |

All of these live near the top of each script — see
[Make It Your Own](#make-it-your-own).

### A note on "sped-up mixing"

Real room air is so lively that capturing every little eddy would need a far
bigger grid than 128×128. To keep things smooth and fast, the toy dials up how
quickly the air smooths itself out. The trade-off: the **shapes and the order of
events are faithful**, but the **exact times are compressed**. The "days vs.
minutes" contrast in the intro describes *real* air — inside the simulation both
processes are sped up, but the punchline (swapping air beats seeping heat) still
holds.

The full equations and numerical methods aren't reproduced here to keep things
readable — the code in [`Fridge.py`](Fridge.py) is short and commented if you
want to see exactly how each step is done.

---

## File Reference

### Scripts

| File | Purpose |
|---|---|
| [`Fridge.py`](Fridge.py) | Fridge scenario: cold slab on the floor. Runs a 90 s simulation. |
| [`Embedded.py`](Embedded.py) | Embedded scenario: cold cube in the middle. Runs a 90 s simulation. |
| [`FridgeZoom.py`](FridgeZoom.py) | Fridge scenario zoomed into the first 10 s, in finer detail. |
| [`render_mp4.py`](render_mp4.py) | Turns `fridge_run.npz` into `fridge_simulation.mp4` |
| [`render_comparison.py`](render_comparison.py) | Makes the side-by-side panels + `embedded_simulation.mp4` |
| [`render_zoom.py`](render_zoom.py) | Turns `fridge_zoom.npz` into `fridge_zoom.mp4` |

### Data files (made by the simulations)

| File | Contents |
|---|---|
| `fridge_run.npz` | 19 snapshots (0–90 s, every 5 s) |
| `embedded_run.npz` | 19 snapshots (0–90 s, every 5 s) |
| `fridge_zoom.npz` | 21 snapshots (0–10 s, every 0.5 s) |

### Output files (made by the rendering scripts)

| File | Made by | What it is |
|---|---|---|
| `fridge_simulation.mp4` | `render_mp4.py` | Full 90 s fridge animation |
| `fridge_zoom.mp4` | `render_zoom.py` | First 10 s of the fridge, slowed down |
| `fridge_zoom.gif` | `ffmpeg` (from the zoom MP4) | The animated GIF at the top of this README |
| `embedded_simulation.mp4` | `render_comparison.py` | Full 90 s embedded animation |
| `fridge_panel.png` | `render_comparison.py` | 6-panel figure (fridge) |
| `comparison_panel.png` | `render_comparison.py` | Side-by-side fridge vs. embedded |

### Reference images (checked in, made during the sanity check)

| File | What it is |
|---|---|
| `embedded_comparison.png` | Embedded run next to the independent reference |
| `comparison_timeseries.png` | Floor and ceiling temperatures over time |
| `reference_panels.png` | Frames from the independent version, used for comparison |

---

## Make It Your Own

All the knobs live near the top of each script. Common tweaks:

| What to change | Where | Example |
|---|---|---|
| **Shape/position of the cold air** | the `fridge` / `embedded` mask | a different block, e.g. cold air across the whole ceiling |
| **Temperatures** | `T_warm`, `T_cold` | warmer room → stronger, faster flow |
| **How smooth vs. swirly the flow is** | `nu`, `alpha` | lower values → more turbulent (you'll want a smaller time step too) |
| **Detail level** | `N` | `N = 256` for a sharper picture (slower) |
| **Length / how often it saves** | `T_end`, `save_every` | `T_end = 30, save_every = 50` |

---

## References

A few starting points if you want to go deeper on the physics and the methods.

**The physics of warm and cold air**
- Turner, J. S. (1973). *Buoyancy Effects in Fluids*. Cambridge University Press.
- Tritton, D. J. (1988). *Physical Fluid Dynamics* (2nd ed.). Oxford University Press.
- Emanuel, K. A. (1994). *Atmospheric Convection*. Oxford University Press.

**The simulation methods**
- Thom, A. (1933). "The flow past circular cylinders at low speeds."
  *Proc. R. Soc. Lond. A*, 141(845), 651–666.
- Fletcher, C. A. J. (1991). *Computational Techniques for Fluid Dynamics*
  (2nd ed.). Springer.
- Press, W. H. et al. (2007). *Numerical Recipes* (3rd ed.). Cambridge
  University Press.

---

## License

MIT License. See [LICENSE](LICENSE).

---

<p align="center">
  <sub>Made with ❄️, NumPy, SciPy, and Matplotlib.</sub>
  <br>
  <sub>Part of <strong>VibeProjects</strong> · <strong>ChillFlow</strong>.</sub>
</p>
