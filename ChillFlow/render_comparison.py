#!/usr/bin/env python3
"""
Generate a 6-panel figure + MP4 for both fridge and embedded configurations,
comparable to the reference embedded_panel.png.
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.patches import Rectangle
import matplotlib.animation as animation

# ── Load both simulations ──
fridge = np.load('/Users/junga1/playground/fridge_run.npz')
embedded = np.load('/Users/junga1/playground/embedded_run.npz')

L = float(fridge['L'])
T_warm = float(fridge['T_warm'])
T_cold = float(fridge['T_cold'])

# ── Pick 6 evenly spaced snapshot indices ──
def pick_times(times, n=6):
    """Pick n approximately evenly spaced time indices."""
    indices = np.linspace(0, len(times) - 1, n, dtype=int)
    return indices, times[indices]

# ── 6-panel figure: 2 rows × 3 cols ──
panel_times = [0, 5, 10, 20, 45, 90]  # seconds matching typical panel output

fig, axes = plt.subplots(2, 3, figsize=(14, 8))
fig.subplots_adjust(left=0.06, right=0.92, top=0.94, bottom=0.06, wspace=0.25, hspace=0.30)

vmin, vmax = 3.0, 21.0
norm = Normalize(vmin=vmin, vmax=vmax)
cmap = 'coolwarm'

# Find closest snapshot indices
fridge_times = fridge['times']
emb_times = embedded['times']

for idx, target_t in enumerate(panel_times):
    row, col = divmod(idx, 3)
    ax = axes[row, col]

    # Fridge: find closest time
    fi = np.argmin(np.abs(fridge_times - target_t))
    ei = np.argmin(np.abs(emb_times - target_t))

    T_fridge = fridge['snapshots'][fi]
    T_emb = embedded['snapshots'][ei]

    # Show fridge temperature field
    im = ax.imshow(T_fridge, origin='lower', extent=[0, L, 0, L],
                   cmap=cmap, norm=norm, aspect='equal')
    # Overlay dashed rectangle for initial cold block
    rect = Rectangle((0.15, 0.0), 0.6, 1.5, fill=False,
                     edgecolor='gray', linestyle='--', linewidth=0.8, alpha=0.5)
    ax.add_patch(rect)

    ax.set_title(f'Fridge t={fridge_times[fi]:.0f}s', fontsize=11)
    ax.set_xlabel('x (m)')
    ax.set_ylabel('y (m)')
    ax.set_xlim(0, L)
    ax.set_ylim(0, L)

    # Add mean T annotation
    mean_T = T_fridge.mean()
    ax.text(0.03, 0.97, f'$\langle T \\rangle = {mean_T:.1f}$°C',
            transform=ax.transAxes, fontsize=8,
            verticalalignment='top', color='white',
            bbox=dict(boxstyle='round,pad=0.2', facecolor='black', alpha=0.5))

# Colorbar
cbar_ax = fig.add_axes([0.94, 0.06, 0.015, 0.88])
cb = fig.colorbar(im, cax=cbar_ax, label='Temperature (°C)')
cb.set_ticks([4, 8, 12, 16, 20])

fig.suptitle('Fridge Simulation: Cold block gravity current (6-panel)',
             fontsize=13, y=0.98)
plt.savefig('fridge_panel.png', dpi=150, bbox_inches='tight')
print("Saved fridge_panel.png")

# ── Also create a comparison panel (embedded vs fridge side by side) ──
fig2, axes2 = plt.subplots(3, 4, figsize=(16, 10))
fig2.subplots_adjust(left=0.05, right=0.93, top=0.95, bottom=0.05, wspace=0.2, hspace=0.35)

comp_times = [0, 5, 10, 20, 45, 90]
for idx, target_t in enumerate(comp_times):
    row = idx // 2
    col_offset = (idx % 2) * 2

    fi = np.argmin(np.abs(fridge_times - target_t))
    ei = np.argmin(np.abs(emb_times - target_t))

    T_f = fridge['snapshots'][fi]
    T_e = embedded['snapshots'][ei]

    # Fridge column
    ax_f = axes2[row, col_offset]
    im_f = ax_f.imshow(T_f, origin='lower', extent=[0, L, 0, L],
                       cmap=cmap, norm=norm, aspect='equal')
    ax_f.add_patch(Rectangle((0.15, 0.0), 0.6, 1.5, fill=False,
                              edgecolor='gray', linestyle='--', linewidth=0.8, alpha=0.4))
    ax_f.set_title(f'Fridge t={fridge_times[fi]:.0f}s', fontsize=10)
    ax_f.set_xlabel('x (m)')
    ax_f.set_ylabel('y (m)')
    ax_f.set_xlim(0, L)
    ax_f.set_ylim(0, L)

    # Embedded column
    ax_e = axes2[row, col_offset + 1]
    im_e = ax_e.imshow(T_e, origin='lower', extent=[0, L, 0, L],
                       cmap=cmap, norm=norm, aspect='equal')
    ax_e.add_patch(Rectangle((1.0, 1.0), 1.0, 1.0, fill=False,
                              edgecolor='gray', linestyle='--', linewidth=0.8, alpha=0.4))
    ax_e.set_title(f'Embedded t={emb_times[ei]:.0f}s', fontsize=10)
    ax_e.set_xlabel('x (m)')
    ax_e.set_ylabel('y (m)')
    ax_e.set_xlim(0, L)
    ax_e.set_ylim(0, L)

cbar_ax2 = fig2.add_axes([0.94, 0.05, 0.015, 0.90])
cb2 = fig2.colorbar(im_e, cax=cbar_ax2, label='Temperature (°C)')
cb2.set_ticks([4, 8, 12, 16, 20])
fig2.suptitle('Comparison: Fridge (gravity current) vs Embedded (falling thermal)',
              fontsize=13)
plt.savefig('comparison_panel.png', dpi=150, bbox_inches='tight')
print("Saved comparison_panel.png")

# ── MP4 of embedded (for direct comparison with reference GIF/MP4) ──
print("\nRendering embedded MP4...")
fig3, ax3 = plt.subplots(1, 1, figsize=(5.5, 5))
fig3.subplots_adjust(left=0.1, right=0.88, top=0.93, bottom=0.1)

im3 = ax3.imshow(embedded['snapshots'][0], origin='lower', extent=[0, L, 0, L],
                 cmap=cmap, norm=norm, aspect='equal')
cb3 = fig3.colorbar(im3, ax=ax3, label='Temperature (°C)')
rect3 = Rectangle((1.0, 1.0), 1.0, 1.0, fill=False,
                   edgecolor='gray', linestyle='--', linewidth=0.8, alpha=0.4)
ax3.add_patch(rect3)
title3 = ax3.set_title(f't = {emb_times[0]:.0f} s', fontsize=12)
ax3.set_xlabel('x (m)')
ax3.set_ylabel('y (m)')
ax3.set_xlim(0, L)
ax3.set_ylim(0, L)

txt3 = ax3.text(0.02, 0.97, f'Mean T = {embedded["snapshots"][0].mean():.2f}°C',
                transform=ax3.transAxes, fontsize=9, verticalalignment='top',
                color='white', bbox=dict(boxstyle='round,pad=0.3', facecolor='black', alpha=0.5))

def update_emb(frame):
    im3.set_array(embedded['snapshots'][frame])
    title3.set_text(f't = {emb_times[frame]:.0f} s')
    txt3.set_text(f'Mean T = {embedded["snapshots"][frame].mean():.2f}°C')
    return im3, title3, txt3

nt_emb = len(emb_times)
fps_emb = max(5, min(30, nt_emb // 8))
anim3 = animation.FuncAnimation(fig3, update_emb, frames=nt_emb, interval=1000/fps_emb, blit=True)
anim3.save('embedded_simulation.mp4', writer=animation.FFMpegWriter(fps=fps_emb, bitrate=2000))
print("Saved embedded_simulation.mp4")

plt.close('all')
print("\nDone. Generated: fridge_panel.png, comparison_panel.png, embedded_simulation.mp4")
