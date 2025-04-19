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
        self.start_time = time.time()
        self.last_kill_gameloop = 0
        
        # Get opponent name from game data
        if self._game_info and self._game_info.player_info:
            opponent_info = self._game_info.player_info[1]  # Index 1 is always opponent in 1v1
            self.opponent_name = opponent_info.name
            
        # Update current army supply based on opponent
        self.current_army_supply = self.build_strategy.get_army_amount(self.opponent_id)
        
        # Initialize components
        self.speed_mining = SpeedMining(self)
        self.cleanup = Cleanup(self)
        
        # Initialize attack tracking
        self.last_attack_frame = 0
        self.previous_result_shown = False
        
        # Announce build and stats
        await self.chat_send(self.build_strategy.get_status_text())

    async def on_step(self, iteration: int):
        """Execute bot logic for each game step.
        
        Args:
            iteration: Current game iteration
        """
        # Track army size
        excluded_types = [UnitTypeId.OVERLORD, UnitTypeId.DRONE, UnitTypeId.QUEEN, UnitTypeId.LARVA, UnitTypeId.OVERSEER, UnitTypeId.MUTALISK]
        current_army = self.units.exclude_type(excluded_types)
        if current_army.amount > 0:
            self.all_armies.append(current_army)
            if current_army.amount > self.max_army_supply:
                self.max_army_supply = current_army.amount

        # Show opponent summary and previous match result at 5 seconds
        if not self.previous_result_shown and iteration > 112:  # 5 seconds at 22.4 iterations/second
            # Show opponent summary
            await self.chat_send(self.stats_manager.get_opponent_summary())
            
            # Show previous match result if we have one
            last_result = self.build_strategy.get_last_game_result(self.opponent_id)
            if last_result:
                army_amount = self.build_strategy.get_army_amount(self.opponent_id)
                wins, losses, winrate = self.build_strategy.get_supply_stats(self.opponent_id, army_amount)
                result_msg = f"{self.NAME} {last_result} our previous match using army amount {army_amount} - {winrate:.1f}% WR ({wins}-{losses})"
                await self.chat_send(result_msg)
            else:
                # If no previous game, show initial message
                army_amount = self.build_strategy.get_army_amount(self.opponent_id)
                result_msg = f"{self.NAME} starting first match using army amount {army_amount} - 0.0% WR (0-0)"
                await self.chat_send(result_msg)
            self.previous_result_shown = True
        
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
        zerglings = self.units(UnitTypeId.ZERGLING)
        not_attacking_zerglings = [z for z in zerglings if self.zergling_attack_status.get(z.tag, "not attacking") == "not attacking"]

        # Attack cooldown in game frames (22.4 frames per second)
        attack_cooldown = 30 * 22.4  # ~30 seconds

        # Two-stage attack logic
        if (
            army.amount > self.current_army_supply
            and self.time * 22.4 - self.last_attack_frame > attack_cooldown
            and not self.cleanup.cleanup_mode_active  # Don't do army attacks in cleanup mode
        ):
            # Stage 1: Attack to furthest friendly base as staging point (do NOT update status)
            if not getattr(self, "attack_staged", False):
                # Find furthest friendly base relative to our start location
                furthest_base = max(self.townhalls, key=lambda th: th.position.distance_to(self.start_location))
                for z in not_attacking_zerglings:
                    z.attack(furthest_base.position)
                self.attack_staged = True
                self.attack_stage_time = self.time
                print("Stage 1: Zerglings staging at furthest friendly base")
            # Stage 2: After 10 seconds, attack main location and update status
            elif self.attack_staged and self.time - self.attack_stage_time >= 10.0:
                for z in not_attacking_zerglings:
                    z.attack(self.enemy_start_locations[0])
                    self.zergling_attack_status[z.tag] = "attacking"
                await self.chat_send(f"Attack {self.totalattacks + 1}")  # +1 since we increment after
                self.totalattacks += 1
                print(f"Main army attack #{self.totalattacks}")
                self.last_attack_frame = self.time * 22.4
                self.attack_staged = False
                self.attack_stage_time = 0.0

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
        self.opponent_id = str(self.opponent_data.player_id)
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
