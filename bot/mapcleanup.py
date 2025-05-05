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
        self.current_base_index = None
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
        self.grid_spacing = 8
        
        # Base search variables
        self.base_positions = []
        self.current_base_index = 0
        
        # Building cooldowns
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
        self.cleanup_check_interval = 2
        self.last_enemy_kill_time = 0
        self.last_enemy_kill_value = 0
        
        # Unit caps and timings
        self.max_zerglings = 100
        self.cleanup_production_pause = 240  # 240 second pause (in game time) when cleanup starts
        self.last_tech_status_time = 0
        
        # Cleanup phase tracking
        self.cleanup_phase = "inactive"  # inactive, active_threats, base_search, grid_search
        self.active_threat_start_time = 0
        self.last_enemy_sighting = 0
        self.last_attack_command = 0

    async def continue_building_drones(self):
        """Keep building drones during cleanup phase."""
        current_time = time.time()
        if (self.ai.supply_workers < 13 and 
            self.ai.can_afford(UnitTypeId.DRONE) and 
            self.ai.larva and 
            current_time - self.last_drone_time > 8):  # Only build a drone every 8 seconds
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
    
    def initialize_base_search(self):
        """Initialize the base-by-base search pattern starting from enemy base."""
        if not self.base_positions:
            # Start with enemy main base
            self.base_positions = [self.ai.enemy_start_locations[0]]
            # Add all possible base locations, sorted by distance from enemy main
            expansion_locs = list(self.ai.expansion_locations.keys())
            sorted_expansions = sorted(expansion_locs, 
                                    key=lambda x: x.distance_to(self.ai.enemy_start_locations[0]))
            self.base_positions.extend(sorted_expansions)
            print(f"Initialized base search with {len(self.base_positions)} bases")
            
    def get_visible_enemy_buildings(self):
        """Get all visible enemy buildings, sorted by distance to our closest unit."""
        enemy_structures = self.ai.enemy_structures
        if not enemy_structures or not self.ai.units:
            return []
            
        # Sort buildings by distance to our closest unit
        return sorted(
            enemy_structures,
            key=lambda structure: min(unit.distance_to(structure) for unit in self.ai.units)
        )
        
    def get_visible_enemy_ground_units(self):
        """Get all visible enemy ground units."""
        return self.ai.enemy_units.filter(lambda unit: not unit.is_flying)
        
    async def handle_active_threats(self):
        """Handle the active threat elimination phase."""
        current_time = self.ai.time
        
        # Check if we should exit this phase
        if current_time - self.active_threat_start_time > 600:  # 10 minutes max
            self.cleanup_phase = "base_search"
            await self.ai.chat_send("[CLEANUP] Active threat phase timeout reached, moving to base search")
            return
            
        # Get visible threats
        enemy_buildings = self.get_visible_enemy_buildings()
        enemy_ground_units = self.get_visible_enemy_ground_units()
        
        if enemy_buildings or enemy_ground_units:
            self.last_enemy_sighting = current_time
            
            # Only issue new attack commands every 10 seconds
            if current_time - self.last_attack_command > 10:
                # Prioritize attacking buildings
                if enemy_buildings:
                    target = enemy_buildings[0]  # Closest building
                    await self.ai.chat_send(f"[CLEANUP] Attacking enemy building at {target.position}")
                else:
                    target = enemy_ground_units[0]  # Take first ground unit
                    await self.ai.chat_send(f"[CLEANUP] Attacking enemy ground unit at {target.position}")
                
                # Command all combat units to attack
                combat_units = self.ai.units.filter(
                    lambda u: u.type_id in {UnitTypeId.ZERGLING, UnitTypeId.MUTALISK}
                )
                for unit in combat_units:
                    unit.attack(target.position)
                
                self.last_attack_command = current_time
        
        # If no enemies seen for 60 seconds, move to base search
        elif current_time - self.last_enemy_sighting > 60:
            self.cleanup_phase = "base_search"
            await self.ai.chat_send("[CLEANUP] No threats found for 60 seconds, moving to base search")
            
    async def handle_base_search(self):
        """Handle the base-by-base search phase."""
        # Check if we found any enemies during base search
        enemy_buildings = self.get_visible_enemy_buildings()
        enemy_ground_units = self.get_visible_enemy_ground_units()
        
        if enemy_buildings or enemy_ground_units:
            # Return to active threat phase
            self.cleanup_phase = "active_threats"
            self.active_threat_start_time = self.ai.time
            self.last_enemy_sighting = self.ai.time
            await self.ai.chat_send("[CLEANUP] Found new threats during base search, returning to active threat phase")
            return
            
        # If we've searched all bases, move to grid search
        if self.current_base_index >= len(self.base_positions):
            self.cleanup_phase = "grid_search"
            await self.ai.chat_send("[CLEANUP] Base search complete, moving to grid search")
            return
            
        # Only issue new attack commands every 10 seconds
        if self.ai.time - self.last_attack_command > 10:
            target = self.base_positions[self.current_base_index]
            await self.ai.chat_send(f"[CLEANUP] Searching base location {self.current_base_index + 1}/{len(self.base_positions)}")
            
            # Command all combat units to attack this base location
            combat_units = self.ai.units.filter(
                lambda u: u.type_id in {UnitTypeId.ZERGLING, UnitTypeId.MUTALISK}
            )
            for unit in combat_units:
                unit.attack(target)
            
            self.current_base_index += 1
            self.last_attack_command = self.ai.time
            
    async def handle_grid_search(self):
        """Handle the grid search phase."""
        # Check if we found any enemies during grid search
        enemy_buildings = self.get_visible_enemy_buildings()
        enemy_ground_units = self.get_visible_enemy_ground_units()
        
        if enemy_buildings or enemy_ground_units:
            # Return to active threat phase
            self.cleanup_phase = "active_threats"
            self.active_threat_start_time = self.ai.time
            self.last_enemy_sighting = self.ai.time
            await self.ai.chat_send("[CLEANUP] Found new threats during grid search, returning to active threat phase")
        else:
            # Continue with existing grid search logic
            if not self.grid_positions:
                self.initialize_grid()
            
            if self.grid_positions:
                if self.ai.units(UnitTypeId.MUTALISK).amount:
                    target = self.grid_positions[self.current_muta_target]
                    self.current_muta_target = (self.current_muta_target + 1) % len(self.grid_positions)
                    for muta in self.ai.units(UnitTypeId.MUTALISK):
                        muta.attack(target)
                else:  # zergling
                    target = self.grid_positions[self.current_ling_target]
                    self.current_ling_target = (self.current_ling_target + 1) % len(self.grid_positions)
                    for ling in self.ai.units(UnitTypeId.ZERGLING):
                        ling.attack(target)
            else:
                for unit in self.ai.units:
                    unit.attack(self.ai.game_info.map_center)
    
    async def setup_gas(self):
        """Build extractor and assign workers to it."""
        if not self.gas_setup_complete:
            # Check if we have any bases first
            if not self.ai.townhalls:
                return
                
            # Get our main base
            main_base = self.ai.townhalls.first
            
            # Check if we have workers in the main base
            workers_in_main = self.ai.workers.closer_than(10, main_base)
            if not workers_in_main:
                return
                
            # Find a geyser near our main base (reduced range from 10 to 5)
            geysers = self.ai.vespene_geyser.closer_than(5, main_base)
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
                        # Take workers from main base specifically
                        workers = workers_in_main.take(3 - extractor.assigned_harvesters)
                        for worker in workers:
                            worker.gather(extractor)
    
    async def start_tech_progression(self):
        """Start the tech progression to lair and spire."""
        current_time = time.time()
        
        # Try to build lair if we have spawning pool and resources
        if (not self.tech_progression_started and
            self.ai.structures(UnitTypeId.SPAWNINGPOOL).ready and 
            self.ai.can_afford(UnitTypeId.LAIR) and 
            not self.ai.structures(UnitTypeId.LAIR).amount and 
            not self.ai.already_pending(UnitTypeId.LAIR)):
            
            hq = self.ai.townhalls.first
            if hq:
                hq.build(UnitTypeId.LAIR)
                print("Starting Lair construction")
                self.last_lair_attempt = time.time()
                self.tech_progression_started = True
        
        # Try to build spire if we have lair
        if (self.tech_progression_started and  # Only try after lair has started
            self.ai.structures(UnitTypeId.LAIR).ready and 
            self.ai.can_afford(UnitTypeId.SPIRE) and 
            not self.ai.structures(UnitTypeId.SPIRE).amount and 
            not self.ai.already_pending(UnitTypeId.SPIRE) and
            current_time - self.last_spire_attempt > self.build_cooldowns[UnitTypeId.SPIRE]):  # Add cooldown check

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

    async def tech_status(self):
        """Check tech status and print debug info."""
        # Only print tech status when we're actually trying to build something
        if self.cleanup_mode_active and self.ai.can_afford(UnitTypeId.LAIR):
            current_time = time.time()
            if current_time - self.last_tech_status_time > 30:  # Only print every 30 seconds
                await self.ai.chat_send(f"Tech status - Lair: {len(self.ai.structures(UnitTypeId.LAIR))}, Spire: {len(self.ai.structures(UnitTypeId.SPIRE))}")
                self.last_tech_status_time = current_time

    async def update(self):
        """Update the cleanup behavior."""
        # Check if we should enter cleanup mode
        if self.cleanup_phase == "inactive":
            # Don't allow cleanup mode before 5 minutes
            if self.ai.time < 300:
                return
                
            # Track when we kill enemy units
            current_kills = self.ai.state.score.killed_value_units
            if current_kills > self.last_enemy_kill_value:
                self.last_enemy_kill_time = self.ai.time
                self.last_enemy_kill_value = current_kills
                
            # Enter cleanup mode if we haven't killed any enemy units for 3 minutes
            if self.ai.time - self.last_enemy_kill_time > 180:
                self.cleanup_mode_active = True
                self.cleanup_phase = "active_threats"
                self.active_threat_start_time = self.ai.time
                self.last_enemy_sighting = self.ai.time
                self.initialize_base_search()
                await self.ai.chat_send("[CLEANUP] Activating cleanup mode after 3 minutes of no kills")
                await self.ai.chat_send("[CLEANUP] Starting active threat elimination phase")
                self.ai.production_manager.add_production_pause(UnitTypeId.ZERGLING, duration_seconds=self.cleanup_production_pause)

        if self.cleanup_mode_active:
            # Handle the current cleanup phase
            if self.cleanup_phase == "active_threats":
                await self.handle_active_threats()
            elif self.cleanup_phase == "base_search":
                await self.handle_base_search()
            elif self.cleanup_phase == "grid_search":
                await self.handle_grid_search()

            # Setup gas and tech progression regardless of phase
            await self.setup_gas()
            if self.gas_setup_complete:
                await self.start_tech_progression()
                await self.tech_status()
                self.start_mutalisk_phase()
                self.update_mutalisk_attacks()

            await self.continue_building_drones()