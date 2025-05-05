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
        self.start_time = time.time()
        self.redistribution_delay = 5.0  # Wait 5 seconds before starting redistribution

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

    def find_long_distance_minerals(self, worker: Unit):
        """Find mineral patches at unclaimed bases for long distance mining."""
        # Get all expansion locations
        expansion_locations = self.ai.expansion_locations_list
        
        # Filter out locations that have our bases or enemy bases
        unclaimed_locations = [
            pos for pos in expansion_locations
            if not self.ai.townhalls.closer_than(6, pos) and
            not self.ai.enemy_structures.closer_than(6, pos)
        ]
        
        if not unclaimed_locations:
            return None
            
        # Sort locations by distance to worker
        unclaimed_locations.sort(key=lambda pos: worker.distance_to(pos))
        
        # Check each location for minerals
        for pos in unclaimed_locations:
            minerals = self.ai.mineral_field.closer_than(8, pos)
            if minerals:
                # Return the mineral patch with fewest workers
                return min(minerals,
                          key=lambda m: len([w for w in self.ai.workers if w.order_target == m.tag]))
        return None

    def redistribute_workers(self):
        """Check worker distribution and transfer excess workers from oversaturated bases."""
        current_time = time.time()
        
        # Don't redistribute workers for first 5 seconds
        if current_time - self.start_time < self.redistribution_delay:
            return
            
        # Only check every worker_check_interval seconds
        if current_time - self.last_worker_check < self.worker_check_interval:
            return

        self.last_worker_check = current_time

        # Check each base for oversaturation
        for base in self.ai.townhalls:
            nearby_minerals = self.ai.mineral_field.closer_than(8, base)
            nearby_workers = self.ai.workers.filter(
                lambda w: w.is_gathering and w.order_target in nearby_minerals.tags
            )
            
            # If we have more than 2 workers per patch, redistribute excess
            mineral_count = len(nearby_minerals)
            if mineral_count > 0:  # Only process bases with remaining minerals
                optimal_workers = mineral_count * 2
                current_workers = len(nearby_workers)
                
                if current_workers > optimal_workers:
                    excess_workers = nearby_workers[-int(current_workers - optimal_workers):]
                    
                    # Find other bases that aren't fully saturated
                    other_bases = [th for th in self.ai.townhalls if th.tag != base.tag]
                    for worker in excess_workers:
                        transferred = False
                        
                        # First try to transfer to our own bases
                        for target_base in sorted(other_bases, key=lambda b: worker.distance_to(b)):
                            target_minerals = self.ai.mineral_field.closer_than(8, target_base)
                            target_workers = self.ai.workers.filter(
                                lambda w: w.is_gathering and w.order_target in target_minerals.tags
                            )
                            
                            # If this base isn't oversaturated, send worker here
                            if len(target_workers) < len(target_minerals) * 2:
                                # Find least saturated mineral patch
                                best_mineral = min(target_minerals, 
                                                key=lambda m: len([w for w in self.ai.workers if w.order_target == m.tag]))
                                worker.gather(best_mineral)
                                transferred = True
                                break
                        
                        # If no available base found, try long distance mining
                        if not transferred:
                            target_mineral = self.find_long_distance_minerals(worker)
                            if target_mineral:
                                worker.gather(target_mineral)

    def handle_idle_workers(self) -> None:
        """Send idle workers to mine at the nearest base with available minerals."""
        for worker in self.ai.workers.idle:
            # Find bases that aren't fully saturated
            available_bases = []
            for th in self.ai.townhalls:
                nearby_minerals = self.ai.mineral_field.closer_than(8, th)
                if not nearby_minerals.exists:
                    continue
                    
                nearby_workers = self.ai.workers.filter(
                    lambda w: w.is_gathering and w.order_target in nearby_minerals.tags
                )
                
                if len(nearby_workers) < len(nearby_minerals) * 2:
                    available_bases.append((th, nearby_minerals))
            
            assigned = False
            if available_bases:
                # Sort by distance to worker
                nearest_base, minerals = min(available_bases, 
                                          key=lambda x: worker.distance_to(x[0]))
                
                # Find mineral patch with fewest workers
                best_mineral = min(minerals,
                                 key=lambda m: len([w for w in self.ai.workers 
                                                  if w.order_target == m.tag]))
                worker.gather(best_mineral)
                assigned = True
            
            # If no available base found, try long distance mining
            if not assigned:
                target_mineral = self.find_long_distance_minerals(worker)
                if target_mineral:
                    worker.gather(target_mineral)

    def find_nearest_mining_base(self, worker: Unit) -> tuple[Unit, Unit]:
        """Find the nearest base with available minerals and a mineral patch to mine from."""
        for th in sorted(self.ai.townhalls, key=lambda x: worker.distance_to(x)):
            nearby_minerals = self.ai.mineral_field.closer_than(8, th)
            if nearby_minerals:
                # Find mineral patch with fewest workers
                best_mineral = min(nearby_minerals, 
                                key=lambda m: len([w for w in self.ai.workers if w.order_target == m.tag]))
                return th, best_mineral
        return None, None

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

    def on_step(self) -> None:
        """Update speed mining for all workers."""
        # Recalculate targets if needed
        if len(self.mineral_target_dict) != len(self.ai.mineral_field):
            self.calculate_targets()

        self.redistribute_workers()  # Check and redistribute workers if needed
        self.handle_idle_workers()   # Handle idle workers at mined out bases
        for worker in self.get_mineral_workers():
            self.speedmine_single(worker)
