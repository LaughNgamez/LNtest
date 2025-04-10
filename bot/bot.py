from sc2.bot_ai import BotAI
from sc2.data import Race, Result
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.buff_id import BuffId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.units import Units
import json
import os
import time
import csv
from datetime import datetime
from .mapcleanup import Cleanup
from .speedmining import SpeedMining

class CompetitiveBot(BotAI):
    NAME: str = "Crawler"
    """This bot's name"""

    RACE: Race = Race.Zerg
    """This bot's Starcraft 2 race."""

    def __init__(self):
        super().__init__()
        self.production_pauses = {}  # Dict to store production pauses with end times
        self.start_time = None
        # Move up one directory from __file__ using os.path.dirname twice
        self.stats_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "opponent_stats.json")
        self.history_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "match_history.csv")
        self.opponent_stats = self.load_opponent_stats()
        self.zergling_rally_point = None
        self.opponent_name = None
        self.expansion_cooldown = 0
        self.totalattacks = 0  # Initialize attack counter
        self.last_kill_gameloop = 0  # Game time of last unit killed
        self.ignored_types = {UnitTypeId.MULE, UnitTypeId.LARVA, UnitTypeId.EGG, UnitTypeId.DRONE}

    def load_opponent_stats(self) -> dict:
        """Load opponent statistics from JSON file."""
        if os.path.exists(self.stats_file):
            with open(self.stats_file, 'r') as f:
                return json.load(f)
        return {}

    def save_opponent_stats(self):
        """Save opponent statistics to JSON file."""
        with open(self.stats_file, 'w') as f:
            json.dump(self.opponent_stats, f, indent=2)

    def log_match_history(self, result: Result):
        """Log match details to CSV file."""
        # Create header if file doesn't exist
        write_header = not os.path.exists(self.history_file)
        
        with open(self.history_file, 'a', newline='') as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(['timestamp', 'opponent_id', 'opponent_name', 'opponent_race', 'map_name', 'result', 'game_duration_seconds', 'total_attacks'])
            
            writer.writerow([
                datetime.now().isoformat(),
                self.opponent_id,
                self.opponent_name or "Unknown",
                self.enemy_race,
                self.game_info.map_name,
                result.name,  # Victory, Defeat, or Tie
                int(time.time() - self.start_time),
                self.totalattacks
            ])

    def update_opponent_stats(self, result: Result):
        """Update opponent statistics."""
        if self.opponent_id not in self.opponent_stats:
            self.opponent_stats[self.opponent_id] = {
                "name": self.opponent_name or "Unknown",
                "wins": 0, 
                "losses": 0,
                "ties": 0
            }
        
        if result == Result.Victory:
            self.opponent_stats[self.opponent_id]["wins"] += 1
        elif result == Result.Defeat:
            self.opponent_stats[self.opponent_id]["losses"] += 1
        elif result == Result.Tie:
            self.opponent_stats[self.opponent_id]["ties"] += 1
        
        # Always update name in case it changed
        self.opponent_stats[self.opponent_id]["name"] = self.opponent_name or "Unknown"
        self.save_opponent_stats()

    async def on_start(self):
        """
        This code runs once at the start of the game
        Do things here before the game starts
        """
        print("Game started")
        self.start_time = time.time()
        self.last_kill_gameloop = 0  # Start at 0 game seconds
        await self.chat_send("[DEBUG] Combat timer starting at 0")
        
        # Get opponent name from opponent_id or use "Computer" for AI
        self.opponent_name = self.opponent_id if not self.opponent_id.startswith("Computer") else "Computer"
        
        # Get opponent stats
        stats = self.opponent_stats.get(self.opponent_id, {"wins": 0, "losses": 0, "ties": 0})
        total_games = stats["wins"] + stats["losses"] + stats["ties"]
        winrate = (stats["wins"] / total_games * 100) if total_games > 0 else 0
        
        # Send winrate message with ties
        await self.chat_send(f"GL HF! Winrate {winrate:.1f}% ({stats['wins']}-{stats['losses']}-{stats['ties']})")
        
        # Initialize components
        self.speed_mining = SpeedMining(self)
        self.cleanup = Cleanup(self)
        self.distribute_workers_initially()
    
    def distribute_workers_initially(self):
        """Distribute workers evenly among mineral patches at game start."""
        workers = self.workers
        mineral_fields = self.mineral_field.closer_than(10, self.townhalls.first)
        
        # Assign each worker to a mineral field, cycling through the fields
        for i, worker in enumerate(workers):
            target_mf = mineral_fields[i % len(mineral_fields)]
            worker.gather(target_mf)

    def add_production_pause(self, unit_type: UnitTypeId, duration_seconds: float = None, until_structure: UnitTypeId = None):
        """Add a production pause for a specific unit type.
        
        Args:
            unit_type: The unit type to pause production for
            duration_seconds: Optional duration in seconds
            until_structure: Optional structure to wait for before resuming
        """
        current_time = time.time()
        
        # Initialize list of pauses for this unit type if it doesn't exist
        if unit_type not in self.production_pauses:
            self.production_pauses[unit_type] = []
            
        # Add the new pause condition
        pause_info = {}
        if duration_seconds:
            pause_info['end_time'] = current_time + duration_seconds
        else:
            pause_info['end_time'] = float('inf')
            
        if until_structure:
            pause_info['wait_for_structure'] = until_structure
            
        self.production_pauses[unit_type].append(pause_info)

    def is_production_paused(self, unit_type: UnitTypeId) -> bool:
        """Check if production is paused for a unit type."""
        if unit_type not in self.production_pauses:
            return False
        
        current_time = time.time()
        pauses = self.production_pauses[unit_type]
        
        # Remove any expired pauses and check if any are still active
        active_pauses = []
        for pause in pauses:
            if current_time < pause['end_time']:
                active_pauses.append(pause)
                
        if not active_pauses:
            # All pauses expired
            del self.production_pauses[unit_type]
            return False
            
        # Update the list with only active pauses
        self.production_pauses[unit_type] = active_pauses
        return True

    async def on_unit_created(self, unit: Unit):
        """Handles newly created units."""
        if unit.type_id == UnitTypeId.ZERGLING and self.zergling_rally_point and not self.cleanup.cleanup_mode_active:
            # First move to rally point
            unit.move(self.zergling_rally_point)
            # Then patrol between rally point and main base
            unit.patrol(self.start_location, queue=True)

    async def on_unit_destroyed(self, unit_tag: int):
        """Called when a unit is destroyed."""
        # First check our own units for drone morphing
        if unit_tag in self.units.tags:
            unit = self.units.find_by_tag(unit_tag)
            if unit and unit.type_id == UnitTypeId.DRONE:
                return  # Skip drone morphing
        
        # If it was in our enemy_units last frame, it's a valid enemy death
        if unit_tag in self._enemy_units_previous_map:
            unit = self._enemy_units_previous_map[unit_tag]
            if unit.type_id not in self.ignored_types:
                self.last_kill_gameloop = self.time

    async def on_step(self, iteration: int):
        """
        This code runs every step of the game.
        Do things here during the game.
        """
        # Show debug message every ~30 seconds instead of every 10
        if iteration % 600 == 0:
            time_since_kill = self.time - self.last_kill_gameloop
            if time_since_kill > 30:  # Only show if more than 30 seconds passed
                await self.chat_send(f"[DEBUG] Time since last kill: {time_since_kill:.1f}s")
        
        # Update speed mining
        self.speed_mining.on_step()
        
        # Check for zergling cap before training
        if len(self.units(UnitTypeId.ZERGLING)) >= self.cleanup.max_zerglings:
            self.add_production_pause(UnitTypeId.ZERGLING)
        elif UnitTypeId.ZERGLING in self.production_pauses and not self.cleanup.cleanup_mode_active:
            # Only unpause if we're under cap and not in cleanup mode
            del self.production_pauses[UnitTypeId.ZERGLING]
        
        # Update cleanup and handle drone production
        await self.cleanup.update()  # Update cleanup mode first
        await self.cleanup.continue_building_drones()  # Then handle drone production
        
        # Time to attack
        if not hasattr(self, "attacked"):
            self.attacked = False
            self.last_attack_frame = 0

        excluded_types = [UnitTypeId.OVERLORD, UnitTypeId.DRONE, UnitTypeId.QUEEN, UnitTypeId.LARVA, UnitTypeId.OVERSEER, UnitTypeId.MUTALISK]
        army = self.units.exclude_type(excluded_types)

        # Attack cooldown in game frames (22.4 frames per second)
        attack_cooldown = 30 * 22.4  # ~30 seconds

        if (
            army.amount > 30
            and self.time * 22.4 - self.last_attack_frame > attack_cooldown
            and not self.cleanup.cleanup_mode_active  # Don't do army attacks in cleanup mode
        ):
            for unit in army:
                unit.attack(self.enemy_start_locations[0])
            await self.chat_send(f"Attack {self.totalattacks + 1}")  # +1 since we increment after
            self.totalattacks += 1
            print(f"Main army attack #{self.totalattacks}")
            self.last_attack_frame = self.time * 22.4

        # Assign workers to gas
        for assimilator in self.gas_buildings.ready:
            if assimilator.assigned_harvesters < assimilator.ideal_harvesters:
                # First try to find idle workers
                workers = self.workers.filter(
                    lambda w: not w.is_carrying_vespene and 
                             not w.is_carrying_minerals and 
                             (not w.orders or w.is_idle)
                )
                
                # If no idle workers, get mineral workers
                if not workers:
                    workers = self.workers.filter(
                        lambda w: not w.is_carrying_vespene and
                                w.orders and
                                w.orders[0].ability.id in [AbilityId.HARVEST_GATHER] and
                                isinstance(w.orders[0].target, int) and
                                self.mineral_field.find_by_tag(w.orders[0].target) is not None
                    )
                
                if workers:  # If we have any workers (idle or mineral)
                    # Take up to 3 workers
                    needed = min(assimilator.ideal_harvesters - assimilator.assigned_harvesters, 3)
                    for _ in range(needed):
                        if workers:
                            workers.random.gather(assimilator)

        # Build spawning pool
        if (not self.structures(UnitTypeId.SPAWNINGPOOL) and 
            not self.already_pending(UnitTypeId.SPAWNINGPOOL) and 
            self.can_afford(UnitTypeId.SPAWNINGPOOL)):
            
            current_time = time.time()
            if current_time - self.cleanup.last_pool_attempt > self.cleanup.build_cooldowns[UnitTypeId.SPAWNINGPOOL]:
                # Calculate position near our first hatchery
                pool_position = self.start_location.towards(self.game_info.map_center, 5)
                # Try to find a valid placement near our calculated position
                await self.build(UnitTypeId.SPAWNINGPOOL, near=pool_position)
                self.cleanup.last_pool_attempt = current_time

        # Build overlord
        if self.supply_left <= 3 and self.supply_used != 200 and self.already_pending(UnitTypeId.OVERLORD) == 0 and self.larva:
            self.train(UnitTypeId.OVERLORD, 1)  # Only make one overlord at a time

        # Calculate zergling rally point if not set
        if not self.zergling_rally_point and self.townhalls.amount >= 2:
            natural = min(self.townhalls, key=lambda th: th.distance_to(self.start_location) if th.position != self.start_location else float('inf'))
            if natural and natural.position != self.start_location:
                self.zergling_rally_point = natural.position.towards(self.enemy_start_locations[0], 5)
        
        # Build zerglings if not paused
        if (self.structures(UnitTypeId.SPAWNINGPOOL).ready and self.larva and 
            not self.is_production_paused(UnitTypeId.ZERGLING)):
            if self.supply_left <= 2 and self.already_pending(UnitTypeId.OVERLORD) == 0:
                return  # Don't make zerglings if supply is low and no overlord is being built
            
            self.train(UnitTypeId.ZERGLING, self.larva.amount)

        # Build mutalisks when spire is ready
        if (self.structures(UnitTypeId.SPIRE).ready and self.larva and 
            self.can_afford(UnitTypeId.MUTALISK) and 
            self.units(UnitTypeId.MUTALISK).amount < 5):
            self.train(UnitTypeId.MUTALISK)

        # Update cleanup last (may override attack commands)
        # await self.cleanup.update()
        
        # Train queen
        if self.structures(UnitTypeId.SPAWNINGPOOL).ready and self.units(UnitTypeId.QUEEN).amount == 0 and self.already_pending(UnitTypeId.QUEEN) == 0:
            self.train(UnitTypeId.QUEEN, 1)

        # Inject larva with queens
        if self.units(UnitTypeId.QUEEN).ready:
            for queen in self.units(UnitTypeId.QUEEN).idle:
                if queen.energy >= 25 and not self.townhalls.first.has_buff(BuffId.QUEENSPAWNLARVATIMER):
                    queen(AbilityId.EFFECT_INJECTLARVA, self.townhalls.first)

        # Build hatchery when minerals are available and drones are present
        if self.minerals >= 350 and self.units(UnitTypeId.DRONE).amount > 1:
            # Check building cooldown
            current_time = time.time()
            if current_time - self.expansion_cooldown > 60:  # 1 minute cooldown
                natural = await self.get_next_expansion()
                if natural:
                    await self.build(UnitTypeId.HATCHERY, near=natural)
                    self.expansion_cooldown = current_time

    async def get_next_expansion(self):
        """Get the next expansion location."""
        # Get all possible expansion locations
        expansion_locations = self.expansion_locations
        
        # Filter out locations that already have a hatchery or are being built on
        taken_locations = {hatch.position for hatch in self.townhalls}
        taken_locations.update(building.position for building in self.structures(UnitTypeId.HATCHERY))
        
        # Start with locations closest to our start
        by_distance = sorted(expansion_locations.keys(), 
                           key=lambda p: p.distance_to(self.start_location))
        
        # Return first untaken location
        for pos in by_distance:
            if pos not in taken_locations:
                return pos
        return None

    async def on_end(self, result: Result):
        """
        This code runs once at the end of the game
        Do things here after the game ends
        """
        print("Game ended.")
        # Log match history
        self.log_match_history(result)
        
        # Update opponent stats
        self.update_opponent_stats(result)
