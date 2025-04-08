from sc2.position import Point2
import math

MINING_RADIUS = 1.325

def get_intersections(p1: Point2, r1: float, p2: Point2, r2: float):
    """Calculate intersection points of two circles."""
    d = p1.distance_to(p2)
    
    # No intersections
    if d > r1 + r2 or d < abs(r1 - r2):
        return []
    
    # One intersection
    if d == r1 + r2 or d == abs(r1 - r2):
        return [p2.towards(p1, r2)]
    
    # Two intersections
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = (r1 * r1 - a * a) ** 0.5
    
    # Calculate intersection points using perpendicular line
    # First find point p3 on the line from p1 to p2
    p3x = p1.x + (a/d) * (p2.x - p1.x)
    p3y = p1.y + (a/d) * (p2.y - p1.y)
    
    # Then find points perpendicular to p3
    dx = h * (p2.y - p1.y) / d
    dy = h * (p2.x - p1.x) / d
    
    return [
        Point2((p3x + dx, p3y - dy)),
        Point2((p3x - dx, p3y + dy))
    ]

def compute_speed_mining_positions(bases, worker_radius, bot):
    """
    Computes optimal positions for speed mining based on mineral intersections.
    
    Args:
        bases (Units): Collection of base units (townhalls).
        worker_radius (float): Radius of a worker unit.
        bot (BotAI): The bot instance for accessing game state.

    Returns:
        dict: Mapping of mineral tags to optimized mining target positions.
    """
    positions_mapping = {}
    centers = [base.position for base in bases]

    for mineral in bot.mineral_field:
        target = mineral.position
        center = target.closest(centers)
        target = target.towards(center, MINING_RADIUS)
        
        # Find any minerals that are too close
        close_minerals = bot.mineral_field.closer_than(MINING_RADIUS * 2, target)
        for other_mineral in close_minerals:
            if other_mineral.tag != mineral.tag:
                # Calculate intersection points
                points = get_intersections(mineral.position, MINING_RADIUS, other_mineral.position, MINING_RADIUS)
                if len(points) == 2:
                    # Choose the intersection point closest to our base
                    target = center.closest(points)
        
        positions_mapping[mineral.tag] = target
        print(f"Mining position for mineral {mineral.tag}: {target}")

    return positions_mapping

def speed_mine_worker(worker, speed_mining_positions, bot):
    """
    Performs speed mining micro for a given worker unit.

    Args:
        worker (Unit): The worker unit to control.
        speed_mining_positions (dict): Mapping of mineral tags to optimized mining target positions.
        bot (BotAI): The bot instance (needed for game context like townhalls, units).
    """
    # Skip if worker has multiple orders
    if len(worker.orders) != 1:
        return

    townhall = bot.townhalls.closest_to(worker)
    
    # Handle returning workers
    if worker.is_returning and not worker.is_carrying_vespene:
        target = townhall.position.towards(worker.position, townhall.radius + worker.radius)
        if 0.75 < worker.distance_to(target) < 2:
            print(f"Worker {worker.tag} optimized return")
            worker.move(target)
            worker.smart(townhall, queue=True)
            return

    # Handle mining workers
    if (not worker.is_returning and 
        worker.tag in bot.worker_assignments):
        
        mineral_tag = bot.worker_assignments[worker.tag]
        mineral = bot.mineral_field.find_by_tag(mineral_tag)
        
        if mineral and mineral_tag in speed_mining_positions:
            target = speed_mining_positions[mineral_tag]
            if 0.75 < worker.distance_to(target) < 2:
                print(f"Worker {worker.tag} optimized mining")
                worker.move(target)
                worker.smart(mineral, queue=True)
