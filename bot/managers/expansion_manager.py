"""Module for managing base expansion and pathfinding."""

import time
from typing import List, Optional, Tuple

from sc2.position import Point2


class ExpansionManager:
    """Manages expansion locations and pathfinding."""

    def __init__(self, bot_instance):
        """Initialize the expansion manager.
        
        Args:
            bot_instance: The main bot instance
        """
        self.bot = bot_instance
        self._expansion_cooldown = 0

    @property
    def expansion_cooldown(self) -> float:
        """Get the current expansion cooldown timestamp."""
        return self._expansion_cooldown

    @expansion_cooldown.setter
    def expansion_cooldown(self, value: float) -> None:
        """Set the expansion cooldown timestamp.
        
        Args:
            value: The new cooldown timestamp
        """
        self._expansion_cooldown = value

    def _get_neighbors(self, pos: Point2) -> List[Point2]:
        """Get valid neighboring positions on the pathing grid.
        
        Args:
            pos: The position to get neighbors for
            
        Returns:
            List of valid neighboring positions
        """
        neighbors = []
        for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
            next_pos = Point2((pos.x + dx, pos.y + dy))
            if self.bot.in_pathing_grid(next_pos):
                # Create a tuple for indexing the pathing grid
                grid_pos = (int(next_pos.y), int(next_pos.x))
                if self.bot.game_info.pathing_grid[grid_pos]:
                    neighbors.append(next_pos)
        return neighbors

    def _manhattan_distance(self, pos1: Point2, pos2: Point2) -> float:
        """Calculate Manhattan distance between two points.
        
        Args:
            pos1: First position
            pos2: Second position
            
        Returns:
            Manhattan distance between the points
        """
        return abs(pos1.x - pos2.x) + abs(pos1.y - pos2.y)

    def find_path_distance(self, start: Point2, goal: Point2) -> float:
        """Find the shortest path distance between two points.
        
        Args:
            start: Starting position
            goal: Target position
            
        Returns:
            float: Path distance, or float('inf') if no path exists
        """
        # Convert to int coordinates for grid
        start_int = Point2((int(start.x), int(start.y)))
        goal_int = Point2((int(goal.x), int(goal.y)))
        
        # Check if points are walkable
        if not self.bot.in_pathing_grid(start_int) or not self.bot.in_pathing_grid(goal_int):
            return float('inf')
            
        # A* pathfinding
        open_nodes = {start_int}
        closed_nodes = set()
        came_from = {}
        g_score = {start_int: 0}
        
        while open_nodes:
            current = min(
                open_nodes,
                key=lambda p: g_score[p] + p.distance_to(goal_int)
            )
            
            if current.distance_to(goal_int) < 1:
                # Found the goal, return path length
                return g_score[current]
                
            open_nodes.remove(current)
            closed_nodes.add(current)
            
            # Check neighbors (8-directional)
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx == 0 and dy == 0:
                        continue
                        
                    neighbor = Point2((current.x + dx, current.y + dy))
                    
                    # Skip if not walkable or already evaluated
                    if (not self.bot.in_pathing_grid(neighbor) or
                        neighbor in closed_nodes):
                        continue
                        
                    # Calculate new path cost
                    move_cost = 1.4 if dx != 0 and dy != 0 else 1.0
                    tentative_g = g_score[current] + move_cost
                    
                    if (neighbor not in open_nodes or
                        tentative_g < g_score.get(neighbor, float('inf'))):
                        came_from[neighbor] = current
                        g_score[neighbor] = tentative_g
                        open_nodes.add(neighbor)
                        
        return float('inf')

    async def get_next_expansion(self) -> Optional[Point2]:
        """Get the next expansion location."""
        if not self.bot.townhalls:
            # No expansions yet, use start location
            return self.bot.start_location

        # Get all possible expansion locations
        expansion_locations = self.bot.expansion_locations
        if not expansion_locations:
            print("No expansion locations found")
            return None
            
        print(f"Found {len(expansion_locations)} possible expansion locations")

        # Get our main base position to path from
        start = self.bot.start_location
        print(f"Using main base at {start} as path start")

        # Track best expansion found
        best_location = None
        shortest_path = float('inf')

        # Check each expansion location
        for pos in expansion_locations:
            # Skip if we already have a base here
            if self.bot.townhalls.closer_than(6, pos):
                continue

            # Skip if enemy has a base here
            if self.bot.enemy_structures.closer_than(6, pos):
                continue

            # Get actual pathing distance a worker would need to travel
            path_distance = await self.bot._client.query_pathing(start, pos)
            
            # If path_distance is None or 0, it means no path was found
            if not path_distance:
                print(f"No path found to {pos}")
                continue
                
            print(f"Path distance to {pos}: {path_distance}")
            
            # Update best location if this path is shorter
            if path_distance < shortest_path:
                shortest_path = path_distance
                best_location = pos
                print(f"New best expansion found at {pos} with path distance {path_distance}")

        if best_location:
            print(f"Selected expansion location: {best_location}")
            return best_location
            
        print("No valid expansion location found")
        return None
