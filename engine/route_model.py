"""Route geometric models, local projection and chainage."""
from __future__ import annotations

import math
from typing import Literal

import numpy as np
import pyproj
from shapely.geometry import LineString, Point

from engine.models import Landmark, Maneuver, RouteModel


def to_utm(lat: float, lon: float) -> int:
    """Return UTM EPSG code for a given lat/lon."""
    zone = math.floor((lon + 180) / 6) + 1
    return 32600 + zone if lat >= 0 else 32700 + zone


class RouteGeometry:
    """Wraps densified NumPy route and Shapely geometries."""

    def __init__(self, raw_points: list[tuple[float, float]]):
        if not raw_points:
            raise ValueError("Empty points")

        self.raw_points = raw_points
        self.utm_epsg = to_utm(raw_points[0][0], raw_points[0][1])

        self.transformer_fwd = pyproj.Transformer.from_crs(4326, self.utm_epsg, always_xy=True)
        self.transformer_inv = pyproj.Transformer.from_crs(self.utm_epsg, 4326, always_xy=True)

        utm_pts = [self.transformer_fwd.transform(lon, lat) for lat, lon in raw_points]
        self.line = LineString(utm_pts)
        self.length_m = self.line.length

        # Densify to ~5m
        num_points = max(2, int(self.length_m / 5.0))
        distances = np.linspace(0, self.length_m, num_points)

        # Always keep final point
        if distances[-1] < self.length_m:
            distances = np.append(distances, self.length_m)

        # N x 2 array of UTM (x, y)
        self.utm_densified = np.array([self.line.interpolate(d).coords[0] for d in distances])
        self.chainages = distances

        # Parallel lat/lon
        self.ll_densified = [
            (lat, lon) for lon, lat in self.transformer_inv.itransform(self.utm_densified)
        ]

    def chainage(self, lat: float, lon: float) -> float:
        """Global chainage via projection to LineString."""
        x, y = self.transformer_fwd.transform(lon, lat)
        return self.line.project(Point(x, y))

    def chainage_windowed(self, lat: float, lon: float, hint_m: float, back_m: float = 30, ahead_m: float = 200) -> tuple[float, float]:
        """Windowed snap. Returns (chainage_m, lateral_distance_m)."""
        x, y = self.transformer_fwd.transform(lon, lat)
        pt = np.array([x, y])

        # Filter window
        start_m = hint_m - back_m
        end_m = hint_m + ahead_m

        mask = (self.chainages >= start_m) & (self.chainages <= end_m)
        if not np.any(mask):
            # Fallback if totally lost
            return self.chainage(lat, lon), Point(x, y).distance(self.line)

        window_pts = self.utm_densified[mask]
        window_chainages = self.chainages[mask]

        # Distances to all points in window
        dists = np.linalg.norm(window_pts - pt, axis=1)
        min_idx = np.argmin(dists)

        return float(window_chainages[min_idx]), float(dists[min_idx])

    def point_at(self, chainage_m: float) -> tuple[float, float]:
        """Interpolate lat/lon at chainage."""
        pt = self.line.interpolate(chainage_m)
        lon, lat = self.transformer_inv.transform(pt.x, pt.y)
        return lat, lon

    def get_side(self, lat: float, lon: float, chainage_m: float) -> tuple[Literal["left", "right", "ahead"], float]:
        """Determine side of the route."""
        x, y = self.transformer_fwd.transform(lon, lat)
        P_landmark = np.array([x, y])

        # Get tangent using points +/- 10m
        p1 = self.line.interpolate(max(0, chainage_m - 10))
        p2 = self.line.interpolate(min(self.length_m, chainage_m + 10))

        P1 = np.array([p1.x, p1.y])
        P2 = np.array([p2.x, p2.y])

        T = P2 - P1
        T_norm = np.linalg.norm(T)
        if T_norm < 1e-6:
            return "ahead", 0.0

        # Vector to landmark
        P_route = np.array([self.line.interpolate(chainage_m).x, self.line.interpolate(chainage_m).y])
        L = P_landmark - P_route

        # Cross product (Tx*Ly - Ty*Lx)
        z = T[0] * L[1] - T[1] * L[0]

        lateral_offset = abs(z) / T_norm

        # Angle check for ahead
        L_norm = np.linalg.norm(L)
        if L_norm > 1e-6:
            dot = np.dot(T, L)
            cos_theta = dot / (T_norm * L_norm)
            # ~30 deg is cos(30) ~ 0.866
            if cos_theta > 0.866:
                return "ahead", float(lateral_offset)

        return "left" if z > 0 else "right", float(lateral_offset)


def build_route_model(raw_points: list[tuple[float, float]], raw_maneuvers: list[Maneuver]) -> RouteModel:
    """Build the final RouteModel."""
    geom = RouteGeometry(raw_points)

    # Fix maneuver chainages which were temporarily stored as point indices
    fixed_maneuvers = []
    for m in raw_maneuvers:
        idx = int(m.chainage_m)
        if idx >= len(raw_points):
            idx = len(raw_points) - 1
        elif idx < 0:
            idx = 0

        pt = raw_points[idx]
        chainage = geom.chainage(pt[0], pt[1])
        m.chainage_m = chainage
        fixed_maneuvers.append(m)

    return RouteModel(
        length_m=geom.length_m,
        points=geom.ll_densified,
        maneuvers=fixed_maneuvers,
        landmarks=[],
        utm_epsg=geom.utm_epsg
    )
