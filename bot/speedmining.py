from typing import Dict, List, Set
from sc2.position import Point2
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.units import Units
import math
import time

MINING_RADIUS = 1.325

class SpeedMining:
    def __init__(self, bot_ai, enable_on_return=True, enable_on_mine=True):
        self.ai = bot_ai
        self.enable_on_return = enable_on_return
        self.enable_on_mine = enable_on_mine
        self.mineral_target_dict: Dict[Point2, Point2] = {}
        self.calculate_targets()
        self.last_worker_check = 0
        self.worker_check_interval = 30  # Check every 30 seconds

    def get_mineral_workers(self) -> Units:
        """Get all workers that are mining minerals (not gas)."""
        return self.ai.workers.filter(
            lambda unit: not unit.is_carrying_vespene and 
            (unit.order_target is None or 
             not self.ai.gas_buildings.find_by_tag(unit.order_target))
        )

    def get_intersections(self, p1: Point2, r1: float, p2: Point2, r2: float) -> List[Point2]:
        """Get intersection points of two circles."""
        d = math.sqrt((p2.x - p1.x) ** 2 + (p2.y - p1.y) ** 2)
        
        # Circles too far apart or contained within each other
        if d > r1 + r2 or d < abs(r2 - r1):
            return []
        
        # Circles are exactly touching
        if d == 0 and r1 == r2:
            return []
        
        a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
        h = math.sqrt(r1 * r1 - a * a)
        
        p3 = Point2((p1.x + a * (p2.x - p1.x) / d, p1.y + a * (p2.y - p1.y) / d))
        
        # One intersection point
        if d == r1 + r2:
            return [p3]
        
        # Two intersection points
        dx = h * (p2.y - p1.y) / d
        dy = h * (p2.x - p1.x) / d
        
        return [
            Point2((p3.x + dx, p3.y - dy)),
            Point2((p3.x - dx, p3.y + dy))
        ]

    def calculate_targets(self):
        """Calculate optimal mining positions for mineral fields."""
        self.mineral_target_dict.clear()
        
        # Get expansion locations (townhall positions)
        centers: List[Point2] = []
        for th in self.ai.townhalls:
            centers.append(th.position)
            
        # For each mineral field
        for mf in self.ai.mineral_field:
            target: Point2 = mf.position
            # Find closest expansion
            center = min(centers, key=lambda p: p.distance_to(target))
            # Move target towards expansion
            target = target.towards(center, MINING_RADIUS)
            
            # Check for nearby minerals that might cause collisions
            close = self.ai.mineral_field.closer_than(MINING_RADIUS, target)
            for mf2 in close:
                if mf2.tag != mf.tag:
                    # Get intersection points of mining circles
                    points = self.get_intersections(
                        mf.position, MINING_RADIUS,
                        mf2.position, MINING_RADIUS
                    )
                    # If we found intersection points, use the one closest to base
                    if len(points) == 2:
                        target = min(points, key=lambda p: p.distance_to(center))
            
            self.mineral_target_dict[mf.position] = target

    def calculate_optimal_worker_count(self) -> int:
        """Calculate optimal number of workers based on mineral patches near bases."""
        total_patches = 0
        for base in self.ai.townhalls:
            nearby_minerals = self.ai.mineral_field.closer_than(8, base)
            total_patches += len(nearby_minerals)
        return total_patches * 2  # 2 workers per patch is optimal

    def redistribute_workers(self):
        """Check worker count and redistribute if necessary."""
        current_time = time.time()
        if current_time - self.last_worker_check < self.worker_check_interval:
            return

        self.last_worker_check = current_time
        optimal_workers = self.calculate_optimal_worker_count()
        current_miners = len([w for w in self.ai.workers if w.is_gathering])

        if current_miners > optimal_workers:
            # Find a worker to move to another base
            for worker in self.ai.workers:
                if worker.is_gathering:
                    # Find another base that isn't the closest one
                    current_base = self.ai.townhalls.closest_to(worker)
                    other_bases = self.ai.townhalls.filter(lambda b: b.tag != current_base.tag)
                    
                    if other_bases:
                        target_base = other_bases.closest_to(worker)
                        # Find least saturated mineral patch at new base
                        nearby_minerals = self.ai.mineral_field.closer_than(8, target_base)
                        if nearby_minerals:
                            best_mineral = min(nearby_minerals, 
                                            key=lambda m: len([w for w in self.ai.workers if w.order_target == m.tag]))
                            worker.gather(best_mineral)
                            print(f"Moving excess worker to new base - Current miners: {current_miners}, Optimal: {optimal_workers}")
                            break

    def speedmine_single(self, worker: Unit):
        """Optimize mining for a single worker."""
        if not worker.orders or len(worker.orders) != 1:
            return

        current_order = worker.orders[0]
        
        # Skip if no townhalls exist
        if not self.ai.townhalls.exists:
            return
            
        townhall = self.ai.townhalls.closest_to(worker)

        # Handle workers returning with minerals
        if self.enable_on_return and worker.is_returning:
            target = townhall.position.towards(worker.position, townhall.radius + worker.radius)
            if 0.75 < worker.distance_to(target) < 2:
                worker.move(target)
                worker(AbilityId.SMART, townhall, queue=True)

        # Handle workers gathering minerals
        elif (self.enable_on_mine and not worker.is_returning and 
              current_order.target in self.ai.mineral_field.tags):
            mf = self.ai.mineral_field.find_by_tag(current_order.target)
            if mf and mf.position in self.mineral_target_dict:
                target = self.mineral_target_dict[mf.position]
                if 0.75 < worker.distance_to(target) < 2:
                    worker.move(target)
                    worker(AbilityId.SMART, mf, queue=True)

    def on_step(self):
        """Update speed mining for all workers."""
        # Recalculate targets if needed
        if len(self.mineral_target_dict) != len(self.ai.mineral_field):
            self.calculate_targets()

        self.redistribute_workers()  # Check and redistribute workers if needed
        for worker in self.get_mineral_workers():
            self.speedmine_single(worker)
