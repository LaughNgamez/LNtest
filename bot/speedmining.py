from typing import Dict
from sc2.position import Point2
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit

# Mining radius constant - this is the optimal distance for workers to mine from
MINING_RADIUS = 1.325

class SpeedMining:
    def __init__(self, bot_ai, enable_on_return=True, enable_on_mine=True):
        self.ai = bot_ai
        self.enable_on_return = enable_on_return
        self.enable_on_mine = enable_on_mine
        self.mineral_target_dict: Dict[Point2, Point2] = {}
        self.calculate_targets()
    
    def calculate_targets(self):
        """Calculate optimal mining positions for each mineral field."""
        for mf in self.ai.mineral_field:
            target: Point2 = mf.position
            # Get closest townhall to this mineral field
            center = self.ai.townhalls.closest_to(mf).position
            # Calculate target position by moving from mineral towards townhall
            target = target.towards(center, MINING_RADIUS)
            self.mineral_target_dict[mf.position] = target

    def speedmine_single(self, worker: Unit):
        """Apply speed mining optimizations to a single worker."""
        townhall = self.ai.townhalls.closest_to(worker)

        # Handle workers returning resources
        if self.enable_on_return and worker.is_returning and len(worker.orders) == 1:
            target: Point2 = townhall.position
            target = target.towards(worker, townhall.radius + worker.radius)
            if 0.75 < worker.distance_to(target) < 2:
                worker.move(target)
                worker(AbilityId.SMART, townhall, queue=True)
                return

        # Handle workers going to mine
        if (
            self.enable_on_mine
            and not worker.is_returning
            and len(worker.orders) == 1
            and worker.order_target in self.ai.mineral_field.tags
        ):
            mf = self.ai.mineral_field.find_by_tag(worker.order_target)
            if mf is not None:
                target = self.mineral_target_dict.get(mf.position)
                if target and 0.75 < worker.distance_to(target) < 2:
                    worker.move(target)
                    worker(AbilityId.SMART, mf, queue=True)

    def update(self):
        """Update speed mining for all workers."""
        if len(self.ai.townhalls) < 1:
            return

        # Get all mineral workers
        workers = self.ai.workers.filter(
            lambda unit: not unit.is_carrying_vespene 
            and (unit.is_gathering or unit.is_returning)
        )

        # Apply speed mining to each worker
        for worker in workers:
            self.speedmine_single(worker)
