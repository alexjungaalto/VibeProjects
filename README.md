<p align="center">
  <img src="https://img.shields.io/badge/status-experimental-orange" alt="Status">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/vibe-on-purple" alt="Vibe">
</p>

# 🌀 VibeProjects

A collection of small, self-contained "vibe coding" experiments — physical
simulations, data visualizations, and animations built for the fun of it. Each
project lives in its own directory with its own README, scripts, and assets, and
each is independently runnable.

---

## 📂 Projects

### ❄️ [ChillFlow](ChillFlow/) — buoyancy-driven convection toy

A 2D simulation of what happens when a pocket of cold air is released into a
warmer room: it slumps, spreads as a gravity current, stratifies, and slowly
homogenises. Solves the vorticity–streamfunction Navier–Stokes equations under
the Boussinesq approximation, with a spectral Poisson solver and semi-Lagrangian
advection. Two configurations (a fridge-door gravity current and a centred
falling thermal) share one solver.

**Stack:** NumPy · SciPy · Matplotlib · ffmpeg → MP4/GIF
&nbsp;·&nbsp; [Read more →](ChillFlow/README.md)

<p align="center">
  <a href="ChillFlow/fridge_zoom.mp4"><img src="ChillFlow/fridge_zoom.gif" alt="ChillFlow fridge zoom animation" width="360"></a>
</p>

### 🏗️ [Verbaut](Verbaut/) — built-up area animation for Austria

*Verbaut* (German for "built-up") animates the growth of building-footprint
coverage in Austria using real OpenStreetMap data — Vienna's built-up area
expanding over 70 years (34.7 km² → 58.1 km²). Outputs a 9:16 YouTube Short, a
16:9 landscape animation, and a static sealed-surface estimator across Austrian
states.

**Stack:** OSMnx · GeoPandas · Shapely · Matplotlib · ffmpeg → MP4
&nbsp;·&nbsp; [Read more →](Verbaut/README.md)

---

## 🚀 Getting Started

Each project is standalone — clone the repo, `cd` into a project directory, and
follow its README for prerequisites and run instructions.

```bash
git clone https://github.com/alexjungaalto/VibeProjects.git
cd VibeProjects/ChillFlow   # or Verbaut
cat README.md
```

Both projects are Python 3.10+ and require `ffmpeg` on your `PATH` for video
output. Per-project dependencies are listed in their respective READMEs.

---

## 📄 License

MIT License. See [LICENSE](LICENSE). Each project also carries its own MIT
`LICENSE` file. Data sourced from OpenStreetMap is © OpenStreetMap contributors
(ODbL).
