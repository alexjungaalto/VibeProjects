#!/usr/bin/env python3
"""
Fridge zoom: first 10 seconds with finer time resolution (0.5s snapshots).
"""

import numpy as np
from scipy import fft
from scipy.ndimage import map_coordinates
import time

L = 3.0
T_warm = 20.0
T_cold = 4.0
g = 9.81
beta = 1.0 / 293.15
nu = 3.0e-3
alpha = 3.0e-3
dt = 0.02
T_end = 10.0
N = 128
save_every = 25  # every 0.5s

h = L / (N - 1)
M = N - 2
nsteps = int(T_end / dt)

x = np.linspace(0.0, L, N)
y = np.linspace(0.0, L, N)
dx = dy = h
X, Y = np.meshgrid(x, y)

fridge = (X >= 0.15) & (X <= 0.75) & (Y <= 1.5)
T = np.full((N, N), T_warm, dtype=np.float64)
T[fridge] = T_cold
T_initial_mean = T.mean()
omega = np.zeros((N, N), dtype=np.float64)
psi = np.zeros((N, N), dtype=np.float64)

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
        (f[2:, 1:-1] - 2.0*f[1:-1,1:-1] + f[:-2,1:-1]) / (dy*dy) +
        (f[1:-1,2:] - 2.0*f[1:-1,1:-1] + f[1:-1,:-2]) / (dx*dx)
    )
    return out

def advect(fld, u, v):
    ii, jj = np.meshgrid(np.arange(N, dtype=np.float64), np.arange(N, dtype=np.float64))
    xi = ii - u * dt / dx
    yj = jj - v * dt / dy
    coords = np.stack([yj.ravel(), xi.ravel()], axis=0)
    return map_coordinates(fld, coords, order=1, mode='nearest').reshape(N, N)

def apply_T_BC(T):
    T[0,:] = T[1,:]; T[-1,:] = T[-2,:]
    T[:,0] = T[:,1]; T[:,-1] = T[:,-2]
    return T

def apply_omega_BC(omega, psi):
    omega[0,:] = -2.0*psi[1,:]/(h*h)
    omega[-1,:] = -2.0*psi[-2,:]/(h*h)
    omega[:,0] = -2.0*psi[:,1]/(h*h)
    omega[:,-1] = -2.0*psi[:,-2]/(h*h)
    return omega

snapshots = [T.copy()]
times = [0.0]

print(f"Fridge zoom: {N}×{N}, {nsteps} steps, dt={dt}s, T_end={T_end}s")
t0 = time.time()

for step in range(1, nsteps + 1):
    t = step * dt
    psi = poisson_solve(-omega)
    u = np.zeros_like(psi); v = np.zeros_like(psi)
    u[1:-1,:] = (psi[2:,:] - psi[:-2,:]) / (2.0*dy)
    v[:,1:-1] = -(psi[:,2:] - psi[:,:-2]) / (2.0*dx)
    u[0,:]=0; u[-1,:]=0; v[:,0]=0; v[:,-1]=0

    omega = apply_omega_BC(advect(omega, u, v) + dt*nu*laplacian(omega), psi)

    T_new = advect(T, u, v) + dt*alpha*laplacian(T)
    dTdx = np.zeros_like(T_new)
    dTdx[:,1:-1] = (T_new[:,2:] - T_new[:,:-2]) / (2.0*dx)
    omega[1:-1,1:-1] += dt * g * beta * dTdx[1:-1,1:-1]
    T = apply_T_BC(T_new)

    if step % save_every == 0 or step == nsteps:
        snapshots.append(T.copy())
        times.append(t)
        print(f"  t={t:5.2f}s, step {step:5d}/{nsteps}, mean T={T.mean():.4f}°C, "
              f"min={T.min():.2f}°C")

print(f"Done in {time.time()-t0:.1f}s, {len(snapshots)} snapshots")

np.savez('fridge_zoom.npz',
         snapshots=np.array(snapshots), times=np.array(times),
         x=x, y=y, T_warm=T_warm, T_cold=T_cold, L=L, N=N,
         dt=dt, nu=nu, alpha=alpha, g=g, beta=beta)
print("Saved fridge_zoom.npz")
