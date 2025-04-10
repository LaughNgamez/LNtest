from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
import time

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
    
    async def continue_building_drones(self):
        """Keep building drones during cleanup phase."""
        current_time = time.time()
        if (self.ai.supply_workers < 12 and 
            self.ai.can_afford(UnitTypeId.DRONE) and 
            self.ai.larva and 
            current_time - self.last_drone_time > 30):  # Only build a drone every 30 seconds
            self.ai.train(UnitTypeId.DRONE)
            self.last_drone_time = current_time
    
    async def setup_gas(self):
        """Build extractor and assign workers to it."""
        if not self.gas_setup_complete:
            # Find a geyser near our main base
            geysers = self.ai.vespene_geyser.closer_than(10, self.ai.townhalls.first)
            if geysers and self.ai.can_afford(UnitTypeId.EXTRACTOR):
                # Build extractor
                await self.ai.build(UnitTypeId.EXTRACTOR, geysers.first)
                self.gas_setup_complete = True
                print("Building extractor for tech progression")
                
                # Assign 3 workers once extractor is built
                if self.ai.structures(UnitTypeId.EXTRACTOR).ready:
                    extractor = self.ai.structures(UnitTypeId.EXTRACTOR).first
                    if extractor.assigned_harvesters < 3:
                        workers = self.ai.workers.take(3 - extractor.assigned_harvesters)
                        for worker in workers:
                            worker.gather(extractor)
    
    def start_tech_progression(self):
        """Start the tech progression to lair and spire."""
        if not self.tech_progression_started:
            # Pause zergling production for 120 seconds OR until lair is built
            if self.ai.structures(UnitTypeId.LAIR).ready:
                # If we already have a lair, just do the 30 second pause
                self.ai.add_production_pause(UnitTypeId.ZERGLING, 30)
                print("Lair already exists - Adding 30 second pause")
            else:
                # Add two separate pauses - whichever finishes first will unpause production
                self.ai.add_production_pause(UnitTypeId.ZERGLING, 120)  # 120 second pause
                self.ai.add_production_pause(UnitTypeId.ZERGLING, until_structure=UnitTypeId.LAIR)  # Until lair is built
                print("Starting tech progression - Pausing zergling production for 120s or until Lair")
            
            self.tech_progression_started = True

    def start_mutalisk_phase(self):
        """Start mutalisk production and map corner attacks."""
        if not self.mutalisk_phase_started and self.ai.structures(UnitTypeId.SPIRE).ready:
            # Pause zergling production for 120 seconds OR until we have 5 mutalisks
            self.ai.add_production_pause(UnitTypeId.ZERGLING, 120)
            print("Spire complete - Starting mutalisk phase")
            self.mutalisk_phase_started = True

            # Train mutalisks if we can afford them
            if self.ai.can_afford(UnitTypeId.MUTALISK) and self.ai.larva:
                self.ai.train(UnitTypeId.MUTALISK)

    def update_mutalisk_attacks(self):
        """Send mutalisks to attack map corners."""
        if self.mutalisk_phase_started:
            mutalisks = self.ai.units(UnitTypeId.MUTALISK)
            
            # If we have 5 or more mutalisks, start corner attacks
            if len(mutalisks) >= 5 and not self.corner_attack_started:
                self.corner_attack_started = True
                print("Starting map corner attacks with mutalisks")

            if self.corner_attack_started:
                current_time = time.time()
                
                # Attack a new corner every 30 seconds
                if current_time - self.last_corner_time >= 30:
                    # Get map corners (in clockwise order from top-left)
                    corners = [
                        (0, self.ai.game_info.map_size[1]),  # Top-left
                        (self.ai.game_info.map_size[0], self.ai.game_info.map_size[1]),  # Top-right
                        (self.ai.game_info.map_size[0], 0),  # Bottom-right
                        (0, 0)  # Bottom-left
                    ]
                    
                    target = corners[self.current_corner]
                    for mutalisk in mutalisks:
                        mutalisk.attack(self.ai.game_info.map_center.offset(target))
                    
                    print(f"Sending mutalisks to corner {self.current_corner + 1}/4")
                    
                    # Move to next corner
                    self.current_corner = (self.current_corner + 1) % 4
                    self.last_corner_time = current_time
    
    async def update(self):
        """Check conditions and perform cleanup actions."""
        current_time = time.time()

        # Check if we should activate cleanup mode
        if not self.cleanup_mode_active and getattr(self.ai, "totalattacks", 0) >= 10:
            self.cleanup_mode_active = True
            print("Cleanup mode activated!")
            
            # Order bases from enemy main to our main
            enemy_main = self.ai.enemy_start_locations[0]
            our_main = self.ai.start_location
            
            # Sort expansions by distance from enemy main to our main
            self.ordered_bases = sorted(
                self.ai.expansion_locations,
                key=lambda p: (
                    # Primary sort by distance from enemy main
                    p.distance_to(enemy_main),
                    # Secondary sort by distance from our main (for equidistant bases)
                    -p.distance_to(our_main)
                )
            )
            self.current_base_index = 0

        if not self.cleanup_mode_active or not self.ordered_bases:
            return

        # Setup gas and tech progression when cleanup mode is active
        await self.setup_gas()
        if self.gas_setup_complete:
            self.start_tech_progression()
            self.start_mutalisk_phase()
            self.update_mutalisk_attacks()

        # Only perform actions every 30 seconds
        if current_time - self.last_attack_time >= 30:
            if self.current_base_index < len(self.ordered_bases):
                target = self.ordered_bases[self.current_base_index]
                
                # Attack with all combat units except mutalisks
                combat_units = self.ai.units.exclude_type([UnitTypeId.DRONE, UnitTypeId.OVERLORD, UnitTypeId.LARVA, UnitTypeId.MUTALISK])
                if combat_units:
                    for unit in combat_units:
                        unit.attack(target)
                    print(f"Attacking base {self.current_base_index + 1} of {len(self.ordered_bases)} - Distance from enemy main: {target.distance_to(self.ai.enemy_start_locations[0]):.1f}")
                
                # Move to next base
                self.current_base_index += 1
                if self.current_base_index >= len(self.ordered_bases):
                    self.current_base_index = 0  # Reset back to enemy main
                    print("Completed full base sweep - Starting over from enemy main")
                self.last_attack_time = current_time

            await self.continue_building_drones()