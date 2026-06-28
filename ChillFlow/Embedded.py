#!/usr/bin/env python3
"""
Embedded configuration: a 1m × 1m cube of cold air centred in a warm room.
Falling thermal → mushroom → gravity current.

Saves to embedded_run.npz
"""

import numpy as np
from scipy import fft
from scipy.ndimage import map_coordinates
import time

# ── Parameters (identical to fridge) ──
L = 3.0
T_warm = 20.0
T_cold = 4.0
g = 9.81
beta = 1.0 / 293.15
nu = 3.0e-3
alpha = 3.0e-3
dt = 0.02
T_end = 90.0
N = 128
save_every = 250

h = L / (N - 1)
M = N - 2
nsteps = int(T_end / dt)

# ── Grid ──
x = np.linspace(0.0, L, N)
y = np.linspace(0.0, L, N)
dx = dy = h
X, Y = np.meshgrid(x, y)

# ── Initial condition: 1m × 1m centred cube ──
# x ∈ [1, 2], y ∈ [1, 2]
embedded = (X >= 1.0) & (X <= 2.0) & (Y >= 1.0) & (Y <= 2.0)

T = np.full((N, N), T_warm, dtype=np.float64)
T[embedded] = T_cold
T_initial_mean = T.mean()

omega = np.zeros((N, N), dtype=np.float64)
psi = np.zeros((N, N), dtype=np.float64)

# ── DST Poisson solver ──
k = np.arange(1, M + 1, dtype=np.float64)
lambda_1d = (2.0 * np.cos(np.pi * k / (M + 1)) - 2.0) / (h * h)
LAM = lambda_1d[:, np.newaxis] + lambda_1d[np.newaxis, :]


def poisson_solve(rhs):
    f = rhs[1:-1, 1:-1].copy()
    F = fft.dst(f, type=1, axis=0, norm=None)
    F = fft.dst(F, type=1, axis=1, norm=None)
    F /= LAM
    psi_int = fft.idst(F, type=1, axis=0, norm=None)
    psi_int = fft.idst(psi_int, type=1, axis=1, norm=None)
    psi_full = np.zeros((N, N), dtype=np.float64)
    psi_full[1:-1, 1:-1] = psi_int
    return psi_full


def laplacian(f):
    out = np.zeros_like(f)
    out[1:-1, 1:-1] = (
        (f[2:, 1:-1] - 2.0 * f[1:-1, 1:-1] + f[:-2, 1:-1]) / (dy * dy) +
        (f[1:-1, 2:] - 2.0 * f[1:-1, 1:-1] + f[1:-1, :-2]) / (dx * dx)
    )
    return out


def advect(fld, u, v):
    i_vals = np.arange(N, dtype=np.float64)
    j_vals = np.arange(N, dtype=np.float64)
    II, JJ = np.meshgrid(i_vals, j_vals)
    xi_dep = II - u * dt / dx
    yj_dep = JJ - v * dt / dy
    coords = np.stack([yj_dep.ravel(), xi_dep.ravel()], axis=0)
    result = map_coordinates(fld, coords, order=1, mode='nearest').reshape(N, N)
    return result


def apply_T_BC(T):
    T[0, :] = T[1, :]
    T[-1, :] = T[-2, :]
    T[:, 0] = T[:, 1]
    T[:, -1] = T[:, -2]
    return T


def apply_omega_BC(omega, psi):
    omega[0, :] = -2.0 * psi[1, :] / (h * h)
    omega[-1, :] = -2.0 * psi[-2, :] / (h * h)
    omega[:, 0] = -2.0 * psi[:, 1] / (h * h)
    omega[:, -1] = -2.0 * psi[:, -2] / (h * h)
    return omega


# ── Main loop ──
snapshots = []
times = []
step_counter = 0

print(f"Starting embedded simulation: {N}×{N} grid, {nsteps} steps, dt={dt}s")
print(f"  T_warm={T_warm}°C, T_cold={T_cold}°C")
print(f"  Initial mean T = {T_initial_mean:.4f}°C")
phi = (1.0 * 1.0) / (L * L)
T_inf = phi * T_cold + (1 - phi) * T_warm
print(f"  Theoretical T_inf = {T_inf:.3f}°C (phi={phi:.4f})")
print(f"  Cold cube: x∈[1,2], y∈[1,2]")
t_start = time.time()

snapshots.append(T.copy())
times.append(0.0)

for step in range(1, nsteps + 1):
    t = step * dt

    # 1. Poisson solve
    psi = poisson_solve(-omega)

    # 2. Velocities
    u = np.zeros_like(psi)
    v = np.zeros_like(psi)
    u[1:-1, :] = (psi[2:, :] - psi[:-2, :]) / (2.0 * dy)
    v[:, 1:-1] = -(psi[:, 2:] - psi[:, :-2]) / (2.0 * dx)
    u[0, :] = 0.0; u[-1, :] = 0.0
    v[:, 0] = 0.0; v[:, -1] = 0.0

    # 3. Semi-Lagrangian advection
    omega_adv = advect(omega, u, v)
    T_adv = advect(T, u, v)

    # 4. Diffusion
    omega_new = omega_adv + dt * nu * laplacian(omega_adv)
    T_new = T_adv + dt * alpha * laplacian(T_adv)

    # 5. Buoyancy torque
    dTdx = np.zeros_like(T_new)
    dTdx[:, 1:-1] = (T_new[:, 2:] - T_new[:, :-2]) / (2.0 * dx)
    omega_new[1:-1, 1:-1] += dt * g * beta * dTdx[1:-1, 1:-1]

    # 6. BCs
    T_new = apply_T_BC(T_new)
    omega_new = apply_omega_BC(omega_new, psi)

    omega = omega_new
    T = T_new

    if step % save_every == 0 or step == nsteps:
        snapshots.append(T.copy())
        times.append(t)
        print(f"  t = {t:6.1f}s, step {step:6d}/{nsteps}, mean T = {T.mean():.4f}°C"
              f" (init {T_initial_mean:.4f}°C)")

elapsed = time.time() - t_start
print(f"Simulation finished in {elapsed:.1f}s")

# ── Save ──
snapshots_arr = np.array(snapshots)
times_arr = np.array(times)
np.savez('embedded_run.npz',
         snapshots=snapshots_arr, times=times_arr, x=x, y=y,
         T_warm=T_warm, T_cold=T_cold, L=L, N=N, dt=dt, nu=nu, alpha=alpha, g=g, beta=beta)
print(f"Saved {len(snapshots)} snapshots to embedded_run.npz")
print(f"  Shape: {snapshots_arr.shape}")
print(f"  Mean T drift: {snapshots_arr[-1].mean() - T_initial_mean:.6f}°C")
