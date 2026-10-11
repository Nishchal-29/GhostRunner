"""Simulator engine for generating fake telemetry from a route."""
from __future__ import annotations

import asyncio
import logging
import time

from config import get_settings
from engine.models import RouteModel, TelemetryFix

logger = logging.getLogger("ghostrunner.simulator")


class Simulator:
    """Runs a simulated run along a route, emitting telemetry to a queue."""
    def __init__(self, route: RouteModel, out_queue: asyncio.Queue, base_speed_mps: float = 3.0):
        self.route = route
        self.out_queue = out_queue
        self.base_speed_mps = base_speed_mps

        self.settings = get_settings()
        self.speed_mult = self.settings.demo_sim_speed_mult

        self.task: asyncio.Task | None = None
        self.is_running = False
        self.current_chainage_m = 0.0
        self.update_interval_s = 1.0  # Emits 1 fix per second in sim time

    async def _loop(self) -> None:
        """Main simulation loop."""
        from engine.route_model import RouteGeometry
        geom = RouteGeometry(self.route.points)

        logger.info("Simulator started. Speed mult: %.1f", self.speed_mult)

        while self.is_running and self.current_chainage_m < self.route.length_m:
            dt = self.update_interval_s
            # Calculate distance covered in this tick
            dist = self.base_speed_mps * self.speed_mult * dt

            self.current_chainage_m += dist
            self.current_chainage_m = min(self.current_chainage_m, self.route.length_m)

            lat, lon = geom.point_at(self.current_chainage_m)

            fix = TelemetryFix(
                t=time.time(),
                lat=lat,
                lon=lon,
                speed=self.base_speed_mps * self.speed_mult,
                heading=0.0, # Approximate, could calculate from dx/dy
                acc=5.0
            )

            await self.out_queue.put(fix)

            # Sleep in real time to match the tick
            # But wait, if speed_mult is used to cover MORE distance per real tick,
            # we just sleep `dt` real seconds.
            await asyncio.sleep(dt)

        logger.info("Simulator finished route.")
        self.is_running = False

    def start(self) -> None:
        """Start the simulator task."""
        if not self.is_running:
            self.is_running = True
            self.task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        """Stop the simulator task."""
        self.is_running = False
        if self.task:
            self.task.cancel()
            self.task = None

    def set_speed_mult(self, mult: float) -> None:
        self.speed_mult = mult
