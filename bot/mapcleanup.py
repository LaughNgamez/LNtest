from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
import time

class Cleanup:
    def __init__(self, bot_ai):
        self.ai = bot_ai
        self.last_drone_time = 0
    
    async def update(self):
        """Check and build drones every 30 seconds if conditions are met."""
        current_time = time.time()
        
        # Only check every 30 seconds
        if current_time - self.last_drone_time >= 30:
            if self.ai.units(UnitTypeId.DRONE).amount < 12 and self.ai.larva and self.ai.can_afford(UnitTypeId.DRONE):
                # Train a drone from larva
                if self.ai.larva.exists:
                    self.ai.larva.first.train(UnitTypeId.DRONE)
                    self.last_drone_time = current_time