from re import X
from sc2.bot_ai import BotAI, Race
from sc2.data import AbilityId, Result

from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import BuffId
from sc2.units import Units
from .speedmining import SpeedMining
from .mapcleanup import Cleanup

class CompetitiveBot(BotAI):
    NAME: str = "Crawler"
    """This bot's name"""

    RACE: Race = Race.Zerg
    """This bot's Starcraft 2 race.
    Options are:
        Race.Terran
        Race.Zerg
        Race.Protoss
        Race.Random
    """

    async def on_start(self):
        """
        This code runs once at the start of the game
        Do things here before the game starts
        """
        print("Game started")
        await self.chat_send("GL HF!")
        # Initialize speed mining
        self.speed_mining = SpeedMining(self)
        # Initialize cleanup
        self.cleanup = Cleanup(self)
        # Distribute workers to minerals
        self.distribute_workers_initially()
    
    def distribute_workers_initially(self):
        """Distribute workers evenly among mineral patches at game start."""
        workers = self.workers
        mineral_fields = self.mineral_field.closer_than(10, self.townhalls.first)
        
        # Assign each worker to a mineral field, cycling through the fields
        for i, worker in enumerate(workers):
            target_mf = mineral_fields[i % len(mineral_fields)]
            worker.gather(target_mf)

    async def on_step(self, iteration: int):
        """
        This code runs every step of the game.
        Do things here during the game.
        """
        # Update speed mining
        self.speed_mining.update()
        # Update cleanup
        await self.cleanup.update()

        #builds spawning pool on 12 supply, positioned towards enemy base
        if self.supply_used >= 12:
            if self.structures(UnitTypeId.SPAWNINGPOOL).amount + self.already_pending(UnitTypeId.SPAWNINGPOOL) == 0:
                # Get positions
                our_base = self.townhalls.first.position
                enemy_base = self.enemy_start_locations[0]
                
                # Calculate position 6 distance away from our base towards enemy base
                pool_position = our_base.towards(enemy_base, 6)
                
                # Try to find a valid placement near our calculated position
                await self.build(UnitTypeId.SPAWNINGPOOL, near=pool_position)

        #build overlord
        if self.supply_left <= 3 and self.supply_used != 200 and self.already_pending(UnitTypeId.OVERLORD) == 0 and self.larva:
            self.train(UnitTypeId.OVERLORD, 1)  # Only make one overlord at a time

        #build zerglings
        if self.structures(UnitTypeId.SPAWNINGPOOL).ready and self.larva:
            if self.supply_left <= 2 and self.already_pending(UnitTypeId.OVERLORD) == 0:
                return  # Don't make zerglings if supply is low and no overlord is being built
            self.train(UnitTypeId.ZERGLING, self.larva.amount)

        # time to attack
        if not hasattr(self, "totalattacks"):
            self.totalattacks = 0
            self.attacked = False
            self.last_attack_frame = 0

        excluded_types = [UnitTypeId.OVERLORD, UnitTypeId.DRONE, UnitTypeId.QUEEN, UnitTypeId.LARVA, UnitTypeId.OVERSEER]
        army = self.units.exclude_type(excluded_types)

        # attack cooldown in game frames (22.4 frames per second)
        attack_cooldown = 30 * 22.4  # ~30 seconds

        if (
            army.amount > 30
            and self.time * 22.4 - self.last_attack_frame > attack_cooldown
        ):
            for unit in army:
                unit.attack(self.enemy_start_locations[0])
            await self.chat_send(f"Attack {self.totalattacks}")
            self.totalattacks += 1
            self.last_attack_frame = self.time * 22.4


        #train queen
        if self.structures(UnitTypeId.SPAWNINGPOOL).ready and self.units(UnitTypeId.QUEEN).amount == 0 and self.already_pending(UnitTypeId.QUEEN) == 0:
            self.train(UnitTypeId.QUEEN, 1)

        #inject larva with queens
        if self.units(UnitTypeId.QUEEN).ready:
            for queen in self.units(UnitTypeId.QUEEN).idle:
                if queen.energy >= 25 and not self.townhalls.first.has_buff(BuffId.QUEENSPAWNLARVATIMER):
                    queen(AbilityId.EFFECT_INJECTLARVA, self.townhalls.first)

        #build hatchery when minerals are available and drones are present
        if self.minerals >= 400 and self.units(UnitTypeId.DRONE).amount > 1:
            natural = await self.get_next_expansion()
            if natural:
                await self.build(UnitTypeId.HATCHERY, near=natural)

                
    pass

    async def on_end(self, result: Result):
        """
        This code runs once at the end of the game
        Do things here after the game ends
        """
        print("Game ended.")
