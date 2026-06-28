#!/usr/bin/env python3
"""Render fridge zoom (10s) as MP4 with finer time resolution."""
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.colors import Normalize
from matplotlib.patches import Rectangle

data = np.load('/Users/junga1/playground/fridge_zoom.npz')
snapshots = data['snapshots']
times = data['times']
x = data['x']
y = data['y']
L = float(data['L'])
T_warm = float(data['T_warm'])
T_cold = float(data['T_cold'])

nt = len(snapshots)
print(f"Loaded {nt} snapshots, t=0–{times[-1]:.1f}s")

vmin, vmax = 3.0, 21.0
norm = Normalize(vmin=vmin, vmax=vmax)

fig, ax = plt.subplots(1, 1, figsize=(6.4, 5.6))
fig.subplots_adjust(left=0.1, right=0.88, top=0.93, bottom=0.1)

im = ax.imshow(snapshots[0], origin='lower', extent=[0, L, 0, L],
               cmap='coolwarm', norm=norm, aspect='equal')
cb = fig.colorbar(im, ax=ax, label='Temperature (°C)')
title = ax.set_title(f't = {times[0]:.1f} s', fontsize=12)
ax.set_xlabel('x (m)')
ax.set_ylabel('y (m)')
ax.set_xlim(0, L)
ax.set_ylim(0, L)

# Cold-block outline
rect = Rectangle((0.15, 0.0), 0.6, 1.5, fill=False,
                 edgecolor='gray', linestyle='--', linewidth=0.8)
ax.add_patch(rect)

mean_T = snapshots[0].mean()
txt = ax.text(0.02, 0.97, f'Mean T = {mean_T:.2f}°C',
              transform=ax.transAxes, fontsize=9,
              verticalalignment='top', color='white',
              bbox=dict(boxstyle='round,pad=0.3', facecolor='black', alpha=0.5))

# Min/max annotation
min_T = snapshots[0].min()
max_T = snapshots[0].max()
txt2 = ax.text(0.02, 0.90, f'Min = {min_T:.1f}°C  Max = {max_T:.1f}°C',
               transform=ax.transAxes, fontsize=8,
               verticalalignment='top', color='white',
               bbox=dict(boxstyle='round,pad=0.3', facecolor='black', alpha=0.5))

def update(frame):
    im.set_array(snapshots[frame])
    title.set_text(f't = {times[frame]:.1f} s')
    mean_T = snapshots[frame].mean()
    min_T = snapshots[frame].min()
    max_T = snapshots[frame].max()
    txt.set_text(f'Mean T = {mean_T:.2f}°C')
    txt2.set_text(f'Min = {min_T:.1f}°C  Max = {max_T:.1f}°C')
    return im, title, txt, txt2

fps = max(10, min(30, nt // 3))
anim = animation.FuncAnimation(fig, update, frames=nt, interval=1000/fps, blit=True)
anim.save('fridge_zoom.mp4', writer=animation.FFMpegWriter(fps=fps, bitrate=2000))
print(f"Saved fridge_zoom.mp4 ({fps} fps, {nt} frames, {times[-1]:.1f}s sim)")

plt.close(fig)
