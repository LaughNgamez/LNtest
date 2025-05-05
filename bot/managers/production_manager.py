"""Module for managing unit production and pauses."""

import time
from typing import Dict, List, Optional, Union

from sc2.ids.unit_typeid import UnitTypeId


class ProductionManager:
    """Manages unit production and production pauses."""

    def __init__(self, bot_instance):
        """Initialize the production manager.
        
        Args:
            bot_instance: The main bot instance
        """
        self.bot = bot_instance
        self.production_pauses: Dict[UnitTypeId, List[Dict]] = {}

    def add_production_pause(
        self,
        unit_type: UnitTypeId,
        duration_seconds: Optional[float] = None,
        until_structure: Optional[UnitTypeId] = None
    ) -> None:
        """Add a production pause for a specific unit type.
        
        Args:
            unit_type: The unit type to pause production for
            duration_seconds: Optional duration in game seconds
            until_structure: Optional structure to wait for before resuming
        """
        current_game_time = self.bot.time
        
        # Initialize list of pauses for this unit type if it doesn't exist
        if unit_type not in self.production_pauses:
            self.production_pauses[unit_type] = []
            
        # Add the new pause condition
        pause_info = {}
        if duration_seconds:
            pause_info['end_time'] = current_game_time + duration_seconds
        else:
            pause_info['end_time'] = float('inf')
            
        if until_structure:
            pause_info['wait_for_structure'] = until_structure
            
        self.production_pauses[unit_type].append(pause_info)

    def is_production_paused(self, unit_type: UnitTypeId) -> bool:
        """Check if production is paused for a unit type.
        
        Args:
            unit_type: The unit type to check
            
        Returns:
            True if production is paused, False otherwise
        """
        if unit_type not in self.production_pauses:
            return False
        
        current_game_time = self.bot.time
        pauses = self.production_pauses[unit_type]
        
        # Remove any expired pauses and check if any are still active
        active_pauses = []
        for pause in pauses:
            if current_game_time < pause['end_time']:
                # Check for structure requirement if it exists
                if 'wait_for_structure' in pause:
                    if not self.bot.structures(pause['wait_for_structure']).ready.exists:
                        active_pauses.append(pause)
                else:
                    active_pauses.append(pause)
                
        if not active_pauses:
            # All pauses expired
            del self.production_pauses[unit_type]
            return False
            
        # Update the list with only active pauses
        self.production_pauses[unit_type] = active_pauses
        return True
