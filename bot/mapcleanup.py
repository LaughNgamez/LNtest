from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
import time
import math

class Cleanup:
    def __init__(self, bot_ai):
        self.ai = bot_ai
        self.last_drone_time = 0
        self.last_attack_time = 0
        self.current_base_index = None  # Will be set when cleanup mode activates
        self.cleanup_mode_active = False
        self.ordered_bases = None
        self.gas_setup_complete = False
        self.tech_progression_started = False
        self.mutalisk_phase_started = False
        self.corner_attack_started = False
        self.last_corner_time = 0
        self.current_corner = 0
        # Grid search variables
        self.grid_positions = []
        self.current_muta_target = 0
        self.current_ling_target = 0
        self.grid_spacing = 16  # Doubled from 8 to 16
        # Building cooldowns - separate for each type
        self.last_extractor_attempt = 0
        self.last_pool_attempt = 0
        self.last_lair_attempt = 0
        self.last_spire_attempt = 0
        self.build_cooldowns = {
            UnitTypeId.EXTRACTOR: 30,
            UnitTypeId.SPAWNINGPOOL: 30,
            UnitTypeId.LAIR: 30,
            UnitTypeId.SPIRE: 30
        }
        # Attack tracking
        self.last_cleanup_check = 0
        self.cleanup_check_interval = 5  # Check every 5 seconds
        
    async def continue_building_drones(self):
        """Keep building drones during cleanup phase."""
        current_time = time.time()
        if (self.ai.supply_workers < 12 and 
            self.ai.can_afford(UnitTypeId.DRONE) and 
            self.ai.larva and 
            current_time - self.last_drone_time > 15):  # Only build a drone every 15 seconds
            self.ai.train(UnitTypeId.DRONE)
            self.last_drone_time = current_time
    
    def initialize_grid(self):
        """Create a grid of positions for units to systematically search."""
        if not self.grid_positions:
            # Get playable area bounds
            p_area = self.ai.game_info.playable_area
            # Create grid of points
            for x in range(p_area.x, p_area.x + p_area.width, self.grid_spacing):
                for y in range(p_area.y, p_area.y + p_area.height, self.grid_spacing):
                    pos = Point2((x, y))
                    # Only add if position is pathable
                    if self.ai.in_pathing_grid(pos):
                        self.grid_positions.append(pos)
            print(f"Initialized search grid with {len(self.grid_positions)} positions")
    
    def get_next_target(self, unit_type: str) -> Point2:
        """Get the next position for units to search."""
        if not self.grid_positions:
            self.initialize_grid()
            
        if self.grid_positions:
            if unit_type == "mutalisk":
                target = self.grid_positions[self.current_muta_target]
                self.current_muta_target = (self.current_muta_target + 1) % len(self.grid_positions)
                return target
            else:  # zergling
                target = self.grid_positions[self.current_ling_target]
                self.current_ling_target = (self.current_ling_target + 1) % len(self.grid_positions)
                return target
        return self.ai.game_info.map_center
    
    async def setup_gas(self):
        """Build extractor and assign workers to it."""
        if not self.gas_setup_complete:
            # Find a geyser near our main base
            geysers = self.ai.vespene_geyser.closer_than(10, self.ai.townhalls.first)
            if geysers and self.ai.can_afford(UnitTypeId.EXTRACTOR):
                # Check building cooldown
                current_time = time.time()
                if current_time - self.last_extractor_attempt > self.build_cooldowns[UnitTypeId.EXTRACTOR]:
                    # Build extractor
                    await self.ai.build(UnitTypeId.EXTRACTOR, geysers.first)
                    self.gas_setup_complete = True
                    print("Building extractor for tech progression")
                    self.last_extractor_attempt = current_time
                    
                # Assign 3 workers once extractor is built
                if self.ai.structures(UnitTypeId.EXTRACTOR).ready:
                    extractor = self.ai.structures(UnitTypeId.EXTRACTOR).first
                    if extractor.assigned_harvesters < 3:
                        workers = self.ai.workers.take(3 - extractor.assigned_harvesters)
                        for worker in workers:
                            worker.gather(extractor)
    
    async def start_tech_progression(self):
        """Start the tech progression to lair and spire."""
        if not self.tech_progression_started:
            current_time = time.time()
            
            # Try to build lair if we have spawning pool and resources
            if (self.ai.structures(UnitTypeId.SPAWNINGPOOL).ready and 
                self.ai.can_afford(UnitTypeId.LAIR) and 
                not self.ai.structures(UnitTypeId.LAIR).amount and 
                not self.ai.already_pending(UnitTypeId.LAIR)):
                
                hq = self.ai.townhalls.first
                if hq:
                    hq.build(UnitTypeId.LAIR)
                    print("Starting Lair construction")
                    self.last_lair_attempt = time.time()
                    self.tech_progression_started = True
            
            # If lair is already started or complete, mark tech progression as started
            if self.ai.structures(UnitTypeId.LAIR).amount > 0 or self.ai.already_pending(UnitTypeId.LAIR):
                self.tech_progression_started = True

            # Try to build spire if we have lair
            if (self.ai.structures(UnitTypeId.LAIR).ready and 
                self.ai.can_afford(UnitTypeId.SPIRE) and 
                not self.ai.structures(UnitTypeId.SPIRE).amount and 
                not self.ai.already_pending(UnitTypeId.SPIRE)):

                print(f"Attempting to build Spire - Lair ready: {self.ai.structures(UnitTypeId.LAIR).ready}, Can afford: {self.ai.can_afford(UnitTypeId.SPIRE)}")
                # Calculate position near our lair
                spire_position = self.ai.structures(UnitTypeId.LAIR).first.position.towards(self.ai.game_info.map_center, 6)
                placement_success = await self.ai.build(UnitTypeId.SPIRE, near=spire_position)
                print(f"Spire placement success: {placement_success}")
                if placement_success:
                    print("Starting Spire construction")
                    self.last_spire_attempt = time.time()
                else:
                    print("Failed to place Spire - might be a placement issue")
    
    def start_mutalisk_phase(self):
        """Start mutalisk production and map corner attacks."""
        if not self.mutalisk_phase_started and self.ai.structures(UnitTypeId.SPIRE).ready:
            # Start producing mutalisks
            if self.ai.can_afford(UnitTypeId.MUTALISK) and self.ai.larva:
                self.ai.train(UnitTypeId.MUTALISK)
                self.mutalisk_phase_started = True
                print("Starting Mutalisk production")

    def update_mutalisk_attacks(self):
        """Update mutalisk attack behavior."""
        if self.mutalisk_phase_started:
            current_time = time.time()
            
            # Check if we should attack corners
            if not self.corner_attack_started and self.ai.units(UnitTypeId.MUTALISK).amount >= 3:
                self.corner_attack_started = True
                print("Starting corner attacks with Mutalisks")
            
            # Update corner attacks
            if self.corner_attack_started and current_time - self.last_corner_time > 30:
                mutas = self.ai.units(UnitTypeId.MUTALISK)
                if mutas:
                    # Get next corner to attack
                    corners = [
                        Point2((0, 0)),
                        Point2((self.ai.game_info.map_size[0], 0)),
                        Point2((0, self.ai.game_info.map_size[1])),
                        Point2((self.ai.game_info.map_size[0], self.ai.game_info.map_size[1]))
                    ]
                    target = corners[self.current_corner]
                    
                    # Attack with all mutalisks
                    for muta in mutas:
                        muta.attack(target)
                    
                    # Update corner index and time
                    self.current_corner = (self.current_corner + 1) % 4
                    self.last_corner_time = current_time
    
    def get_ordered_base_locations(self):
        """Get base locations ordered by distance from enemy main."""
        enemy_main = self.ai.enemy_start_locations[0]
        our_main = self.ai.start_location
        
        # Sort expansions by distance from enemy main to our main
        return sorted(
            list(self.ai.expansion_locations.keys()),  # Convert dict keys to list
            key=lambda p: (
                # Primary sort by distance from enemy main
                p.distance_to(enemy_main),
                # Secondary sort by distance from our main (for equidistant bases)
                -p.distance_to(our_main)
            )
        )

    async def update(self):
        """Update the cleanup behavior."""
        current_time = time.time()

        # Check if we should enter cleanup mode
        if not self.cleanup_mode_active:
            # Enter cleanup mode if nothing has been killed in the last 3 minutes
            time_since_last_kill = current_time - self.ai.last_thing_killed_at
            print(f"Time since last kill: {time_since_last_kill:.1f} seconds")
            if time_since_last_kill > 180:  # 180 seconds = 3 minutes
                self.cleanup_mode_active = True
                self.initialize_grid()
                print("Activating cleanup mode after 3 minutes of no kills")
                await self.ai.chat_send("Entering cleanup mode")
                print("Initialized zergling search grid")

        if self.cleanup_mode_active:
            # Handle mutalisk scouting when in cleanup mode
            mutas = self.ai.units(UnitTypeId.MUTALISK)
            if mutas:
                # Initialize grid if needed
                if not self.grid_positions:
                    self.initialize_grid()
                    print("Initialized mutalisk search grid")
                
                # Only get new target if all mutas are idle or not attacking
                if all(not muta.is_attacking and not muta.is_moving for muta in mutas):
                    target = self.get_next_target("mutalisk")
                    print(f"Moving mutalisks to grid position {self.current_muta_target}")
                    for muta in mutas:
                        muta.attack(target)

            # Handle zergling scouting when in cleanup mode
            lings = self.ai.units(UnitTypeId.ZERGLING)
            if lings:
                # Initialize grid if needed
                if not self.grid_positions:
                    self.initialize_grid()
                    print("Initialized zergling search grid")
                
                # Only get new target if all lings are idle or not attacking
                if all(not ling.is_attacking and not ling.is_moving for ling in lings):
                    target = self.get_next_target("zergling")
                    print(f"Moving zerglings to grid position {self.current_ling_target}")
                    for ling in lings:
                        ling.attack(target)

            # Setup gas and tech progression
            await self.setup_gas()
            if self.gas_setup_complete:
                await self.start_tech_progression()
                print(f"Tech status - Lair: {self.ai.structures(UnitTypeId.LAIR).amount}, Spire: {self.ai.structures(UnitTypeId.SPIRE).amount}")
                self.start_mutalisk_phase()
                self.update_mutalisk_attacks()

            await self.continue_building_drones()