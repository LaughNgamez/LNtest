"""Module for managing unit creation and control."""

from typing import Optional

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit


class UnitManager:
    """Manages unit creation and control."""

    def __init__(self, bot_instance):
        """Initialize the unit manager.
        
        Args:
            bot_instance: The main bot instance
        """
        self.bot = bot_instance
        self._zergling_rally_point: Optional[Point2] = None

    @property
    def zergling_rally_point(self) -> Optional[Point2]:
        """Get the current zergling rally point."""
        return self._zergling_rally_point

    @zergling_rally_point.setter
    def zergling_rally_point(self, point: Point2) -> None:
        """Set the zergling rally point.
        
        Args:
            point: The new rally point
        """
        self._zergling_rally_point = point

    def distribute_workers_initially(self) -> None:
        """Distribute workers evenly among mineral patches at game start."""
        workers = self.bot.workers
        mineral_fields = self.bot.mineral_field.closer_than(
            10,
            self.bot.townhalls.first
        )
        
        # Assign each worker to a mineral field, cycling through the fields
        for i, worker in enumerate(workers):
            target_mf = mineral_fields[i % len(mineral_fields)]
            worker.gather(target_mf)

    async def on_unit_created(self, unit: Unit) -> None:
        """Handle newly created units.
        
        Args:
            unit: The newly created unit
        """
        if (unit.type_id == UnitTypeId.ZERGLING and
            self._zergling_rally_point and
            not self.bot.cleanup.cleanup_mode_active):
            # First move to rally point
            unit.move(self._zergling_rally_point)
            # Then patrol between rally point and main base
            unit.patrol(self.bot.start_location, queue=True)
            
        elif unit.type_id == UnitTypeId.OVERLORD:
            # Keep overlords near our main base
            unit.move(self.bot.start_location)
            
        elif unit.type_id == UnitTypeId.DRONE:
            await self._assign_drone_to_minerals(unit)

    async def _assign_drone_to_minerals(self, drone: Unit) -> None:
        """Assign a drone to mine minerals at the nearest base.
        
        Args:
            drone: The drone to assign
        """
        # Try to find minerals at any base
        for base in sorted(
            self.bot.townhalls,
            key=lambda th: drone.distance_to(th.position)
        ):
            mineral_fields = self.bot.mineral_field.closer_than(10, base)
            if mineral_fields:
                # Find mineral field with fewest workers
                target = min(
                    mineral_fields,
                    key=lambda mf: len(self.bot.workers.filter(
                        lambda w: w.is_gathering and w.order_target == mf.tag
                    ))
                )
                drone.gather(target)
                break  # Stop once we've found a valid mineral field
