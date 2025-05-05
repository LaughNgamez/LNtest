"""Main bot implementation module."""

import time
from typing import Optional, Set

from sc2.bot_ai import BotAI
from sc2.data import Race, Result
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from .managers.expansion_manager import ExpansionManager
from .managers.production_manager import ProductionManager
from .managers.stats_manager import StatsManager
from .managers.unit_manager import UnitManager
from .mapcleanup import Cleanup
from .speedmining import SpeedMining
from .builds import get_build


class CompetitiveBot(BotAI):
    """Main bot class implementing a competitive Zerg strategy."""

    NAME: str = "Crawler"
    RACE: Race = Race.Zerg

    def __init__(self, build_name: Optional[str] = None):
        """Initialize the bot with managers."""
        super().__init__()
        self.start_time = None
        self.opponent_name = None
        self.totalattacks = 0
        self.last_kill_gameloop = 0
        self.last_attack_frame = 0  # Initialize last attack frame
        self.ignored_types = {
            UnitTypeId.MULE,
            UnitTypeId.LARVA,
            UnitTypeId.EGG,
            UnitTypeId.DRONE
        }

        # Initialize managers
        self.expansion_manager = ExpansionManager(self)
        self.production_manager = ProductionManager(self)
        self.unit_manager = UnitManager(self)
        
        # Initialize build strategy
        self.build_strategy = get_build(build_name)
        
        # Initialize stats manager
        self.stats_manager = StatsManager(self)
        
        # Track zergling attack status
        self.zergling_attack_status: dict[int, str] = {}
        self.all_armies = []  # Track army sizes throughout the game
        self.max_army_supply = 0  # Track maximum army supply in this game
        self.current_army_supply = self.build_strategy.DEFAULT_ARMY_AMOUNT  # Initialize with default amount

    async def on_start(self):
        """Called when the game starts.""" 
        print("Game started")
        
        # Store initial worker assignments for repeated commands
        self.initial_worker_assignments = []
        
        # Do initial worker split FIRST before anything else
        townhall = self.townhalls[0]  # Get main base
        mineral_fields = self.mineral_field.closer_than(10, townhall)
        if mineral_fields and self.workers:
            # Sort minerals by distance to townhall
            mineral_fields = sorted(mineral_fields, key=lambda x: x.distance_to(townhall))
            
            # Split into close (first 4) and far (next 4) patches
            close_patches = mineral_fields[:4]
            far_patches = mineral_fields[4:8]
            available_workers = set(self.workers.take(12))  # Get first 12 workers
            
            # For each close patch (first 4), assign 2 closest workers
            for patch in close_patches:
                if len(available_workers) < 2:
                    break
                    
                # Get 2 closest workers for this patch
                for _ in range(2):
                    if available_workers:
                        worker = min(available_workers, key=lambda w: w.distance_to(patch))
                        available_workers.remove(worker)
                        worker.gather(patch, queue=True)
                        self.initial_worker_assignments.append((worker, patch.position, patch))
            
            # For each far patch (next 4), assign 1 closest worker
            for patch in far_patches:
                if not available_workers:
                    break
                    
                worker = min(available_workers, key=lambda w: w.distance_to(patch))
                available_workers.remove(worker)
                worker.gather(patch, queue=True)
                self.initial_worker_assignments.append((worker, patch.position, patch))
            
            # Issue first set of gather commands
            self.worker_split_frame = 0
            for worker, pos, patch in self.initial_worker_assignments:
                worker.gather(patch)

        # Initialize remaining components
        self.start_time = time.time()
        self.opponent_name = str(self.enemy_race)  # Use enemy_race as name too
        self.cleanup = Cleanup(self)
        self.speed_mining = SpeedMining(self)
        
        # Initialize attack tracking
        self.previous_result_shown = False
        
        # Wait for game to fully initialize before sending chat
        await self._client.step()
        await self._client.step()
        
        # Show opponent summary in all chat
        await self.stats_manager.send_chat(self.stats_manager.get_opponent_summary())
        
        # Wait a bit between messages
        await self._client.step()
        
        # Show previous match result if we have one
        last_result = self.build_strategy.get_last_game_result(self.opponent_id)
        previous_army_amount = self.build_strategy.get_last_army_amount(self.opponent_id)  # Get previous game's army amount
        current_army_amount = self.build_strategy.get_army_amount(self.opponent_id)  # Get current game's army amount
        
        # Get stats for previous game's army amount
        prev_wins, prev_losses, prev_winrate = self.build_strategy.get_supply_stats(self.opponent_id, previous_army_amount) if previous_army_amount else (0, 0, 0)
        
        # Get stats for current game's army amount
        curr_wins, curr_losses, curr_winrate = self.build_strategy.get_supply_stats(self.opponent_id, current_army_amount)
        
        if last_result:
            result_msg = f"{self.NAME} {last_result} the previous match using {self.build_strategy.NAME} {previous_army_amount} build - {prev_winrate:.1f}% WR ({prev_wins}-{prev_losses})"
            await self.stats_manager.send_chat(result_msg)
        else:
            # If no previous game, show initial message with current stats
            result_msg = f"{self.NAME} starting first match using {self.build_strategy.NAME} build - {curr_winrate:.1f}% WR ({curr_wins}-{curr_losses})"
            await self.stats_manager.send_chat(result_msg)
            
        # Wait a bit between messages
        await self._client.step()
        
        # Show current match army supply target
        await self.stats_manager.send_chat(f"Crawler will be attacking with army supply amount of {current_army_amount} (Winrate {curr_winrate:.1f}% ({curr_wins}-{curr_losses}))")
        
        # Wait a bit between messages
        await self._client.step()
        
        # Announce build and stats
        await self.stats_manager.send_chat(self.build_strategy.get_status_text())
        
        # Initialize last attack frame
        self.last_attack_frame = 0
        self.attack_stage_time = 0.0
        
        # Complete parent initialization last
        await super().on_start()

    async def on_step(self, iteration: int):
        """Execute bot logic for each game step.
        
        Args:
            iteration: Current game iteration
        """
        # Re-issue worker split commands for the first few frames
        if hasattr(self, 'worker_split_frame'):
            if self.worker_split_frame < 5:  # First 5 frames
                # Issue gather commands every frame
                for worker, pos, patch in self.initial_worker_assignments:
                    worker.gather(patch)
                self.worker_split_frame += 1
            elif self.worker_split_frame == 5:
                # Cleanup after we're done
                del self.worker_split_frame
                del self.initial_worker_assignments
        
        # Track army size
        excluded_types = [UnitTypeId.OVERLORD, UnitTypeId.DRONE, UnitTypeId.QUEEN, UnitTypeId.LARVA, UnitTypeId.OVERSEER, UnitTypeId.MUTALISK]
        current_army = self.units.exclude_type(excluded_types)
        if current_army.amount > 0:
            self.all_armies.append(current_army)
            if current_army.amount > self.max_army_supply:
                self.max_army_supply = current_army.amount

        # Run build-specific logic
        await self.build_strategy.on_step(self)
        
        # Debug messages
        if iteration % 600 == 0:
            time_since_kill = self.time - self.last_kill_gameloop
            if time_since_kill > 30:
                await self.chat_send(
                    f"[DEBUG] Time since last kill: {time_since_kill:.1f}s"
                )
        
        # Update speed mining
        self.speed_mining.on_step()
        
        # Check for zergling cap before training
        current_zergling_count = len(self.units(UnitTypeId.ZERGLING))
        if current_zergling_count >= self.cleanup.max_zerglings:
            self.production_manager.add_production_pause(UnitTypeId.ZERGLING)
        elif current_zergling_count < self.cleanup.max_zerglings:
            # Remove pause if we're under the cap and not in cleanup mode
            if (UnitTypeId.ZERGLING in self.production_manager.production_pauses
                and not self.cleanup.cleanup_mode_active):
                del self.production_manager.production_pauses[UnitTypeId.ZERGLING]
        
        # Update cleanup and handle drone production
        await self.cleanup.update()
        await self.cleanup.continue_building_drones()

        # Maintain zergling status dict
        current_zerglings = self.units(UnitTypeId.ZERGLING)
        current_tags = set(z.tag for z in current_zerglings)
        # Remove dead zerglings
        self.zergling_attack_status = {tag: status for tag, status in self.zergling_attack_status.items() if tag in current_tags}
        # Add new zerglings
        for z in current_zerglings:
            if z.tag not in self.zergling_attack_status:
                self.zergling_attack_status[z.tag] = "not attacking"

        # Time to attack
        if not hasattr(self, "attacked"):
            self.attacked = False
            self.last_attack_frame = 0
            self.attack_staged = False
            self.attack_stage_time = 0.0

        excluded_types = [UnitTypeId.OVERLORD, UnitTypeId.DRONE, UnitTypeId.QUEEN, UnitTypeId.LARVA, UnitTypeId.OVERSEER, UnitTypeId.MUTALISK]
        army = self.units.exclude_type(excluded_types)
        army_supply = self.supply_army  # Use supply instead of unit count
        zerglings = self.units(UnitTypeId.ZERGLING)
        not_attacking_zerglings = [z for z in zerglings if self.zergling_attack_status.get(z.tag, "not attacking") == "not attacking"]

        # Attack cooldown in game frames (22.4 frames per second)
        attack_cooldown = 30 * 22.4  # ~30 seconds

        # Only print attack conditions every 30 seconds (about 672 frames)
        if self.time * 22.4 % 672 < 1:
            print(f"Army supply: {army_supply}, Target: {self.current_army_supply}")
            print(f"Time since last attack: {self.time * 22.4 - self.last_attack_frame}, Cooldown: {attack_cooldown}")
            print(f"Attack conditions: supply={army_supply >= self.current_army_supply}, cooldown={self.time * 22.4 - self.last_attack_frame > attack_cooldown}, not_cleanup={not self.cleanup.cleanup_mode_active}")
            print(f"Attack stage time: {self.attack_stage_time}, Stage 1 duration: {self.time - self.attack_stage_time if self.attack_stage_time != 0.0 else 0}")

        # Two-stage attack logic
        if (
            army_supply >= self.current_army_supply
            and self.time * 22.4 - self.last_attack_frame > attack_cooldown
            and not self.cleanup.cleanup_mode_active  # Don't do army attacks in cleanup mode
        ):
            # Stage 1: Move zerglings to the furthest friendly base
            if self.attack_stage_time == 0.0:
                self.attack_stage_time = self.time  # Use game time instead of wall clock time
                print("Stage 1: Zerglings staging at furthest friendly base")
                
                # Find furthest base from start location
                if self.townhalls:  # Only try to find furthest base if we have any
                    furthest_base = max(self.townhalls, key=lambda th: th.position.distance_to(self.start_location))
                    # Send zerglings to furthest base
                    for z in not_attacking_zerglings:
                        z.move(furthest_base.position)
                else:
                    # If no bases left, just attack from current position
                    for z in not_attacking_zerglings:
                        z.attack(self.enemy_start_locations[0])
            # Stage 2: After 10 seconds, attack main location and update status
            elif self.attack_stage_time != 0.0 and self.time - self.attack_stage_time >= 10.0:
                # Check if enemy main is cleared
                enemy_main = self.enemy_start_locations[0]
                enemy_structures_in_main = self.enemy_structures.closer_than(10, enemy_main)
                zerglings_in_main = self.units(UnitTypeId.ZERGLING).closer_than(10, enemy_main)
                enemy_main_cleared = len(enemy_structures_in_main) == 0 and len(zerglings_in_main) > 0

                # If main is cleared, look for other visible enemy structures
                attack_target = enemy_main
                if enemy_main_cleared and self.enemy_structures:
                    visible_structures = self.enemy_structures.filter(lambda s: self.is_visible(s.position))
                    if visible_structures:
                        attack_target = visible_structures.random.position
                        message = f"Attack #{self.totalattacks} redirected to enemy structure at {attack_target}"
                        print(message)
                        await self.chat_send(message)

                for z in not_attacking_zerglings:
                    z.attack(attack_target)
                    self.zergling_attack_status[z.tag] = "attacking"
                army_supply = self.supply_army
                self.totalattacks += 1
                self.last_attack_frame = self.time * 22.4  # Update last attack frame
                self.attack_stage_time = 0.0  # Reset attack stage time
                if not enemy_main_cleared:  # Only print default message if not redirected
                    message = f"Attack #{self.totalattacks} with {army_supply} supply"
                    print(message)
                    await self.chat_send(message)

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
            # Calculate position near our first hatchery
            pool_position = self.start_location.towards(self.game_info.map_center, 3)
            # Try to find a valid placement near our calculated position
            if await self.build_structure(UnitTypeId.SPAWNINGPOOL, near=pool_position):
                print(f"Spawning pool started")

        # Build expansion if we have enough minerals
        if self.minerals >= 350 and self.can_afford(UnitTypeId.HATCHERY):
            natural = await self.expansion_manager.get_next_expansion()
            if natural:
                print(f"Expanding to {natural}")  # Debug print
                if await self.build(UnitTypeId.HATCHERY, near=natural):
                    # Only set cooldown if build succeeded
                    self.expansion_manager.expansion_cooldown = time.time() + 60  # 1 minute cooldown

        # Build overlord
        if self.supply_left <= 3 and self.supply_used != 200 and self.already_pending(UnitTypeId.OVERLORD) == 0 and self.larva:
            self.train(UnitTypeId.OVERLORD, 1)  # Only make one overlord at a time

        # Set rally point for zerglings once we have 2 bases
        if not self.unit_manager.zergling_rally_point and self.townhalls.amount >= 2:
            # Rally between natural and enemy base
            natural = self.townhalls.sorted_by_distance_to(self.start_location)[1]
            enemy_base = self.enemy_start_locations[0]
            rally_point = natural.position.towards(enemy_base, 15)  # 15 units in front of natural
            self.unit_manager.zergling_rally_point = rally_point

        # Build zerglings if not paused
        if (self.structures(UnitTypeId.SPAWNINGPOOL).ready and self.larva and 
            not self.production_manager.is_production_paused(UnitTypeId.ZERGLING)):
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
                if queen.energy >= 25:
                    # Find closest townhall to this queen
                    closest_base = self.townhalls.closest_to(queen)
                    queen(AbilityId.EFFECT_INJECTLARVA, closest_base)

    def add_production_pause(
        self,
        unit_type: UnitTypeId,
        duration_seconds: Optional[float] = None,
        until_structure: Optional[UnitTypeId] = None
    ) -> None:
        """Add a production pause for a specific unit type.
        
        Args:
            unit_type: The unit type to pause production for
            duration_seconds: Optional duration in seconds
            until_structure: Optional structure to wait for before resuming
        """
        self.production_manager.add_production_pause(
            unit_type,
            duration_seconds=duration_seconds,
            until_structure=until_structure
        )

    async def build_structure(self, structure_type: UnitTypeId, near: Point2) -> bool:
        """Build a structure near a position.
        
        Args:
            structure_type: Type of structure to build
            near: Position to build near
            
        Returns:
            True if building was started, False otherwise
        """
        # Get position to build
        pos = await self.find_placement(structure_type, near)
        if pos is None:
            return False
            
        # Get builder
        worker = self.select_build_worker(pos)
        if worker is None:
            return False
            
        # Build structure
        worker.build(structure_type, pos)
        return True

    async def on_unit_created(self, unit: Unit):
        """Handle unit creation events.
        
        Args:
            unit: The newly created unit
        """
        await self.unit_manager.on_unit_created(unit)

    async def on_unit_destroyed(self, unit_tag: int):
        """Handle unit destruction events.
        
        Args:
            unit_tag: Tag of the destroyed unit
        """
        self.last_kill_gameloop = self.time

    async def on_end(self, result: Result):
        """Called at the end of a game."""
        self.stats_manager.update_opponent_stats(result)
        self.stats_manager.log_match_history(result)
        
        # Record game result with the army supply amount we were targeting
        self.build_strategy.record_game(result == Result.Victory, self.opponent_id, self.current_army_supply)

class CrawlerBot(BotAI):
    """A StarCraft II bot using python-sc2."""
    
    async def on_start(self) -> None:
        """Called when the game starts."""
        self.client.game_step = 2  # Increase game speed
        self.start_time = time.time()
        # Note: opponent_id is already set from run.py, don't overwrite it
        self.opponent_name = self.opponent_data.name
        
        # Distribute workers
        await self.distribute_workers()
        
        # Build workers if we can afford them and need more
        await self.build_workers()
        
        # Build supply depots when needed
        await self.build_supply()
        
        # Expand when possible
        await self.expand()
    
    async def on_step(self, iteration: int) -> None:
        """Main game loop, called every game step.
        
        Args:
            iteration: Current game iteration
        """
        # Distribute workers
        await self.distribute_workers()
        
        # Build workers if we can afford them and need more
        await self.build_workers()
        
        # Build supply depots when needed
        await self.build_supply()
        
        # Expand when possible
        await self.expand()
    
    async def build_workers(self) -> None:
        """Build workers if we can afford them and need more."""
        if (
            len(self.workers) < self.townhalls.amount * 22
            and self.can_afford(UnitTypeId.SCV)
            and self.supply_left > 0
        ):
            for cc in self.townhalls.idle:
                if self.can_afford(UnitTypeId.SCV):
                    cc.train(UnitTypeId.SCV)
    
    async def build_supply(self) -> None:
        """Build supply depots when needed."""
        if (
            self.supply_left < 5
            and not self.already_pending(UnitTypeId.SUPPLYDEPOT)
            and self.can_afford(UnitTypeId.SUPPLYDEPOT)
        ):
            workers: Units = self.workers.gathering
            if workers:
                worker: Unit = workers.random
                placement: Point2 = await self.find_placement(
                    UnitTypeId.SUPPLYDEPOT,
                    near=worker.position.towards(self.game_info.map_center, 5)
                )
                if placement:
                    worker.build(UnitTypeId.SUPPLYDEPOT, placement)
    
    async def expand(self) -> None:
        """Expand to a new base when resources permit."""
        if (
            self.can_afford(UnitTypeId.COMMANDCENTER)
            and not self.already_pending(UnitTypeId.COMMANDCENTER)
            and self.townhalls.amount < 3
        ):
            await self.expand_now()
