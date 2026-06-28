#!/usr/bin/env python3
"""
Cold-air-in-a-warm-room: a 2D buoyancy-driven convection toy.

Fridge configuration: a 0.6 m × 1.5 m block of cold air on the floor,
against the left wall. Simulates a sideways gravity current.

Saves a stack of temperature snapshots to 'fridge_run.npz'.
"""

import numpy as np
from scipy import fft
from scipy.ndimage import map_coordinates
import time
import os

# ── Parameters ──────────────────────────────────────────────────────────────
L = 3.0                # room side length [m]
T_warm = 20.0          # ambient temperature [°C]
T_cold = 4.0           # cold region temperature [°C]
g = 9.81               # gravity [m/s^2]
beta = 1.0 / 293.15    # thermal expansion coefficient [1/K]
nu = 3.0e-3            # effective kinematic viscosity [m^2/s]
alpha = 3.0e-3         # effective thermal diffusivity [m^2/s]
dt = 0.02              # timestep [s]
T_end = 90.0           # total simulated time [s]
N = 128                # grid points per side
save_every = 250       # save a snapshot every this many steps

# Derived
h = L / (N - 1)        # grid spacing
M = N - 2              # number of interior points
nsteps = int(T_end / dt)

# ── Grid ────────────────────────────────────────────────────────────────────
# x horizontal, y vertical (gravity acts in -y)
x = np.linspace(0.0, L, N)
y = np.linspace(0.0, L, N)
dx = h
dy = h

# 2D arrays: shape (N, N), index [j, i] → (y_j, x_i)
X, Y = np.meshgrid(x, y)

# ── Initial condition: cold block on the floor, left wall ───────────────────
# cold block: x ∈ [0.15, 0.75], y ≤ 1.5
fridge = (
    (X >= 0.15) & (X <= 0.75) &
    (Y <= 1.5)
)

T = np.full((N, N), T_warm, dtype=np.float64)
T[fridge] = T_cold
T_initial_mean = T.mean()

omega = np.zeros((N, N), dtype=np.float64)
psi = np.zeros((N, N), dtype=np.float64)

# ── DST Poisson solver setup ────────────────────────────────────────────────
# Eigenvalues of the 5-point Laplacian for Dirichlet BC on interior (M = N-2)
# λ_k = [2 cos(π k/(M+1)) - 2] / h^2,  k = 1..M
k = np.arange(1, M + 1, dtype=np.float64)
lambda_1d = (2.0 * np.cos(np.pi * k / (M + 1)) - 2.0) / (h * h)
# 2D eigenvalues: λ_i + λ_j
LAM = lambda_1d[:, np.newaxis] + lambda_1d[np.newaxis, :]  # (M, M)

# Transform matrices: DST-I (type-I discrete sine transform)
# scipy.fft.dst with type=1, norm=None is orthonormal up to factor 2(M+1)
# We'll use dst/ idst directly.


def poisson_solve(rhs):
    """
    Solve ∇²ψ = -rhs with ψ = 0 on all walls using DST-I.

    rhs has shape (N, N) including boundaries (which are ignored).
    Returns ψ of shape (N, N) with boundaries zero.
    """
    # Interior
    f = rhs[1:-1, 1:-1].copy()
    # Forward DST on both axes
    F = fft.dst(f, type=1, axis=0, norm=None)
    F = fft.dst(F, type=1, axis=1, norm=None)
    # Solve in spectral space
    F /= LAM
    # Inverse DST
    psi_int = fft.idst(F, type=1, axis=0, norm=None)
    psi_int = fft.idst(psi_int, type=1, axis=1, norm=None)
    # Place back with zero boundaries
    psi_full = np.zeros((N, N), dtype=np.float64)
    psi_full[1:-1, 1:-1] = psi_int
    return psi_full


# ── Helper: laplacian ───────────────────────────────────────────────────────
def laplacian(f):
    """Central-difference Laplacian on uniform grid. f shape (N,N)."""
    out = np.zeros_like(f)
    out[1:-1, 1:-1] = (
        (f[2:, 1:-1] - 2.0 * f[1:-1, 1:-1] + f[:-2, 1:-1]) / (dy * dy) +
        (f[1:-1, 2:] - 2.0 * f[1:-1, 1:-1] + f[1:-1, :-2]) / (dx * dx)
    )
    return out


# ── Semi-Lagrangian advection ──────────────────────────────────────────────
def advect(fld, u, v):
    """
    Semi-Lagrangian advection step.
    fld: quantity to advect (N, N).
    u, v: velocity components (N, N), u = ∂ψ/∂y, v = -∂ψ/∂x.
    Returns advected field at grid points.
    """
    # Grid indices
    i_vals = np.arange(N, dtype=np.float64)
    j_vals = np.arange(N, dtype=np.float64)
    II, JJ = np.meshgrid(i_vals, j_vals)

    # Departure points (backward tracing)
    # u is in m/s, dt in s; convert to index units
    xi_dep = II - u * dt / dx
    yj_dep = JJ - v * dt / dy

    # Bilinear interpolation via map_coordinates
    # map_coordinates expects (row, col) = (j, i)
    coords = np.stack([yj_dep.ravel(), xi_dep.ravel()], axis=0)
    result = map_coordinates(fld, coords, order=1, mode='nearest').reshape(N, N)
    return result


# ── Wall boundary conditions ────────────────────────────────────────────────
def apply_T_BC(T):
    """No-flux: wall temperature = adjacent interior cell (zero normal gradient)."""
    T[0, :] = T[1, :]        # bottom wall
    T[-1, :] = T[-2, :]      # top wall
    T[:, 0] = T[:, 1]        # left wall
    T[:, -1] = T[:, -2]      # right wall
    return T


def apply_omega_BC(omega, psi):
    """
    Thom's formula for no-slip walls.
    ω_wall = -2 ψ_adjacent / h²
    """
    # Bottom wall (j=0): ω = -2 ψ[1, :] / h²
    omega[0, :] = -2.0 * psi[1, :] / (h * h)
    # Top wall (j=N-1): ω = -2 ψ[N-2, :] / h²
    omega[-1, :] = -2.0 * psi[-2, :] / (h * h)
    # Left wall (i=0): ω = -2 ψ[:, 1] / h²
    omega[:, 0] = -2.0 * psi[:, 1] / (h * h)
    # Right wall (i=N-1): ω = -2 ψ[:, N-2] / h²
    omega[:, -1] = -2.0 * psi[:, -2] / (h * h)
    return omega


# ── Main time-stepping loop ─────────────────────────────────────────────────
snapshots = []
times = []
step_counter = 0

print(f"Starting fridge simulation: {N}×{N} grid, {nsteps} steps, dt={dt}s")
print(f"  T_warm={T_warm}°C, T_cold={T_cold}°C")
print(f"  nu=alpha={nu} m²/s, Ra≈{g * beta * (T_warm - T_cold) * L**3 / (nu * alpha):.1e}")
print(f"  Cold block: x∈[0.15,0.75], y≤1.5")
t_start_wall = time.time()

# Save initial state
snapshots.append(T.copy())
times.append(0.0)

for step in range(1, nsteps + 1):
    t = step * dt

    # 1. Poisson solve: ∇²ψ = -ω
    psi = poisson_solve(-omega)

    # 2. Velocities: u = ∂ψ/∂y, v = -∂ψ/∂x (central differences)
    u = np.zeros_like(psi)
    v = np.zeros_like(psi)
    u[1:-1, :] = (psi[2:, :] - psi[:-2, :]) / (2.0 * dy)
    v[:, 1:-1] = -(psi[:, 2:] - psi[:, :-2]) / (2.0 * dx)
    # No-slip: zero wall-normal and tangential on boundaries (already zero from diff above
    # but ensure corners and edges are zero)
    u[0, :] = 0.0
    u[-1, :] = 0.0
    v[:, 0] = 0.0
    v[:, -1] = 0.0

    # 3. Semi-Lagrangian advection for ω and T
    omega_adv = advect(omega, u, v)
    T_adv = advect(T, u, v)

    # 4. Explicit diffusion
    lap_omega = laplacian(omega_adv)
    lap_T = laplacian(T_adv)
    omega_new = omega_adv + dt * nu * lap_omega
    T_new = T_adv + dt * alpha * lap_T

    # 5. Buoyancy torque: g β ∂T/∂x
    # ∂T/∂x at interior points using central differences
    dTdx = np.zeros_like(T_new)
    dTdx[:, 1:-1] = (T_new[:, 2:] - T_new[:, :-2]) / (2.0 * dx)
    omega_new[1:-1, 1:-1] += dt * g * beta * dTdx[1:-1, 1:-1]

    # 6. Temperature BC (no-flux)
    T_new = apply_T_BC(T_new)

    # 7. Vorticity BC (Thom's formula)
    omega_new = apply_omega_BC(omega_new, psi)

    # Update
    omega = omega_new
    T = T_new

    # Save snapshot
    if step % save_every == 0 or step == nsteps:
        snapshots.append(T.copy())
        times.append(t)
        mean_T = T.mean()
        print(f"  t = {t:6.1f}s, step {step:6d}/{nsteps}, mean T = {mean_T:.4f}°C"
              f" (init {T_initial_mean:.4f}°C)")

    step_counter = step

elapsed = time.time() - t_start_wall
print(f"Simulation finished in {elapsed:.1f}s ({nsteps} steps)")

# ── Save results ────────────────────────────────────────────────────────────
snapshots_arr = np.array(snapshots)
times_arr = np.array(times)
np.savez('fridge_run.npz',
         snapshots=snapshots_arr,
         times=times_arr,
         x=x,
         y=y,
         T_warm=T_warm,
         T_cold=T_cold,
         L=L,
         N=N,
         dt=dt,
         nu=nu,
         alpha=alpha,
         g=g,
         beta=beta)
print(f"Saved {len(snapshots)} snapshots to fridge_run.npz")
print(f"  Shape: {snapshots_arr.shape}")
print(f"  Time range: {times_arr[0]:.1f} – {times_arr[-1]:.1f}s")
print(f"  Mean T drift: {snapshots_arr[-1].mean() - T_initial_mean:.6f}°C")
