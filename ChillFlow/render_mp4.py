#!/usr/bin/env python3
"""
Render the fridge simulation temperature field as an MP4 video.
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.colors import Normalize

# Load data
data = np.load('fridge_run.npz')
snapshots = data['snapshots']  # (nt, N, N)
times = data['times']
x = data['x']
y = data['y']
T_warm = float(data['T_warm'])
T_cold = float(data['T_cold'])
L = float(data['L'])

nt = len(snapshots)
print(f"Loaded {nt} snapshots, time range: {times[0]:.1f} – {times[-1]:.1f}s")

# T_range for colorbar: fixed across all frames
vmin = T_cold - 1.0
vmax = T_warm + 1.0
norm = Normalize(vmin=vmin, vmax=vmax)

# Set up the figure
fig, ax = plt.subplots(1, 1, figsize=(6.4, 5.6))
fig.subplots_adjust(left=0.1, right=0.88, top=0.93, bottom=0.1)

# Initial image
im = ax.imshow(snapshots[0], origin='lower', extent=[0, L, 0, L],
               cmap='coolwarm', norm=norm, aspect='equal')
cb = fig.colorbar(im, ax=ax, label='Temperature (°C)')

# Title
title = ax.set_title(f't = {times[0]:.1f} s', fontsize=12)

# Labels
ax.set_xlabel('x (m)')
ax.set_ylabel('y (m)')
ax.set_xlim(0, L)
ax.set_ylim(0, L)

# Cold-block outline for reference (fridge config)
rect = plt.Rectangle((0.15, 0.0), 0.6, 1.5, fill=False,
                     edgecolor='gray', linestyle='--', linewidth=0.8)
ax.add_patch(rect)

# Text annotation for mean T
mean_T = snapshots[0].mean()
txt = ax.text(0.02, 0.97, f'Mean T = {mean_T:.2f}°C',
              transform=ax.transAxes, fontsize=9,
              verticalalignment='top', color='white',
              bbox=dict(boxstyle='round,pad=0.3', facecolor='black', alpha=0.5))


def update(frame):
    im.set_array(snapshots[frame])
    title.set_text(f't = {times[frame]:.1f} s')
    mean_T = snapshots[frame].mean()
    txt.set_text(f'Mean T = {mean_T:.2f}°C')
    return im, title, txt


# Create animation
print("Rendering MP4...")
fps = min(30, max(5, nt // 10))  # adaptive fps
anim = animation.FuncAnimation(fig, update, frames=nt, interval=1000/fps, blit=True)

# Save as MP4
writer = animation.FFMpegWriter(fps=fps, bitrate=2000)
anim.save('fridge_simulation.mp4', writer=writer)
print("Saved fridge_simulation.mp4")

plt.close(fig)
