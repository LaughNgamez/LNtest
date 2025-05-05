"""Builds for the bot to use."""
from typing import Dict, Optional
import json
import os
from pathlib import Path
import time

class Build:
    """Base class for builds."""
    DEFAULT_ARMY_AMOUNT: int = 10
    NAME: str = "Base Build"
    
    def __init__(self, name: str):
        self.name = name
        self._stats = self._load_stats()
        if self.name not in self._stats:
            self._stats[self.name] = {
                "opponent_history": {}  # Track results and army amounts per opponent
            }
            self._save_stats()
        
    def _get_stats_file(self) -> Path:
        """Get the path to the stats file."""
        return Path(__file__).parent.parent / "data" / "build_stats.json"
        
    def _load_stats(self) -> Dict:
        """Load build statistics from file."""
        stats_file = self._get_stats_file()
        if not stats_file.parent.exists():
            stats_file.parent.mkdir(parents=True)
            
        if not stats_file.exists():
            return {}
            
        try:
            with open(stats_file, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
            
    def _save_stats(self):
        """Save build statistics to file."""
        stats_file = self._get_stats_file()
        with open(stats_file, "w") as f:
            json.dump(self._stats, f, indent=2)
            
    def _find_next_valid_amount(self, opponent_stats: dict, current_amount: int) -> int:
        """Find the next army amount that hasn't lost 3+ times with no wins.
        
        Args:
            opponent_stats: Stats for this opponent
            current_amount: Current army amount
            
        Returns:
            Next valid army amount, or DEFAULT_ARMY_AMOUNT if all amounts have lost 3+ times
        """
        # Try each possible amount from current+5 to 50
        for amount in range(current_amount + 5, 55, 5):
            if amount > 50:
                break
                
            supply_key = str(amount)
            if supply_key not in opponent_stats["supply_history"]:
                return amount  # This amount hasn't been tried yet
                
            supply_stats = opponent_stats["supply_history"][supply_key]
            if supply_stats["losses"] < 3 or supply_stats["wins"] > 0:
                return amount  # This amount hasn't lost 3+ times or has at least 1 win
                
        # Check if all amounts from 10 to 50 have lost 3+ times with no wins
        all_lost = True
        for amount in range(10, 55, 5):
            if amount > 50:
                break
                
            supply_key = str(amount)
            if supply_key not in opponent_stats["supply_history"]:
                all_lost = False
                break
                
            supply_stats = opponent_stats["supply_history"][supply_key]
            if supply_stats["losses"] < 3 or supply_stats["wins"] > 0:
                all_lost = False
                break
                
        # If all amounts have lost 3+ times with no wins, reset to default
        if all_lost:
            return self.DEFAULT_ARMY_AMOUNT
            
        # Otherwise, wrap around to the first valid amount from 10
        for amount in range(10, current_amount, 5):
            supply_key = str(amount)
            if supply_key not in opponent_stats["supply_history"]:
                return amount
                
            supply_stats = opponent_stats["supply_history"][supply_key]
            if supply_stats["losses"] < 3 or supply_stats["wins"] > 0:
                return amount
                
        # Should never get here since we checked all_lost above
        return self.DEFAULT_ARMY_AMOUNT

    def record_game(self, won: bool, opponent_id: str, army_supply: int):
        """Record the result of a game.
        
        Args:
            won: Whether the game was won
            opponent_id: ID of the opponent
            army_supply: The army supply amount used in this game
        """
        if self.name not in self._stats:
            self._stats[self.name] = {"opponent_history": {}}
            
        if opponent_id not in self._stats[self.name]["opponent_history"]:
            self._stats[self.name]["opponent_history"][opponent_id] = {
                "army_amount": self.DEFAULT_ARMY_AMOUNT,
                "last_result": None,
                "last_army_amount": None,
                "timestamp": None,
                "supply_history": {}
            }
            
        opponent_stats = self._stats[self.name]["opponent_history"][opponent_id]
        
        # Initialize supply history for this amount if needed
        supply_key = str(army_supply)
        if supply_key not in opponent_stats["supply_history"]:
            opponent_stats["supply_history"][supply_key] = {
                "wins": 0,
                "losses": 0
            }
            
        # Update supply history
        if won:
            opponent_stats["supply_history"][supply_key]["wins"] += 1
            # Keep the same army amount after a win
        else:
            opponent_stats["supply_history"][supply_key]["losses"] += 1
            
            # Check if we've lost too many times at this supply
            supply_stats = opponent_stats["supply_history"][supply_key]
            if supply_stats["losses"] >= 3 and supply_stats["wins"] == 0:
                # Find next valid amount
                opponent_stats["army_amount"] = self._find_next_valid_amount(opponent_stats, army_supply)
            else:
                # Normal loss handling - increase by 5
                opponent_stats["army_amount"] = min(50, army_supply + 5)
            
        # Update last result and timestamp
        opponent_stats["last_result"] = "won" if won else "lost"
        opponent_stats["last_army_amount"] = army_supply
        opponent_stats["timestamp"] = time.time()
        
        # Save stats
        self._save_stats()
        
    def get_army_amount(self, opponent_id: str) -> int:
        """Get army amount for a specific opponent.
        
        Args:
            opponent_id: ID of the opponent
            
        Returns:
            Current army amount for this opponent
        """
        # Initialize opponent stats if needed
        if opponent_id not in self._stats[self.name]["opponent_history"]:
            self._stats[self.name]["opponent_history"][opponent_id] = {
                "army_amount": self.DEFAULT_ARMY_AMOUNT,
                "last_result": None,
                "timestamp": None,
                "supply_history": {}
            }
            self._save_stats()
            return self.DEFAULT_ARMY_AMOUNT
            
        # Get opponent-specific stats and return stored army amount
        opponent_stats = self._stats[self.name]["opponent_history"][opponent_id]
        return opponent_stats["army_amount"]
        
    def get_total_losses(self, opponent_id: str) -> int:
        """Get total number of losses against an opponent.
        
        Args:
            opponent_id: ID of the opponent
            
        Returns:
            Total number of losses
        """
        if (
            self.name in self._stats
            and opponent_id in self._stats[self.name]["opponent_history"]
        ):
            return sum(
                stats["losses"]
                for stats in self._stats[self.name]["opponent_history"][opponent_id]["supply_history"].values()
            )
        return 0
        
    def get_build_losses(self, opponent_id: str) -> int:
        """Get number of losses for this specific build against an opponent.
        
        Args:
            opponent_id: ID of the opponent
            
        Returns:
            Total number of losses for this build
        """
        if (
            self.name in self._stats
            and opponent_id in self._stats[self.name]["opponent_history"]
            and "supply_history" in self._stats[self.name]["opponent_history"][opponent_id]
        ):
            opponent_stats = self._stats[self.name]["opponent_history"][opponent_id]
            total_losses = 0
            for supply_stats in opponent_stats["supply_history"].values():
                total_losses += supply_stats["losses"]
            return total_losses
        return 0
        
    def get_supply_stats(self, opponent_id: str, army_supply: int) -> tuple[int, int, float]:
        """Get win/loss stats for a specific army supply amount.
        
        Args:
            opponent_id: ID of the opponent
            army_supply: The army supply amount
            
        Returns:
            Tuple of (wins, losses, winrate)
        """
        if (
            self.name in self._stats 
            and opponent_id in self._stats[self.name]["opponent_history"]
        ):
            opponent_stats = self._stats[self.name]["opponent_history"][opponent_id]
            if "supply_history" in opponent_stats:
                supply_key = str(army_supply)
                if supply_key in opponent_stats["supply_history"]:
                    stats = opponent_stats["supply_history"][supply_key]
                    wins = stats["wins"]
                    losses = stats["losses"]
                    total = wins + losses
                    winrate = (wins / total * 100) if total > 0 else 0
                    return wins, losses, winrate
        return 0, 0, 0  # Return zeros if no stats found for this supply amount
        
    def get_last_game_result(self, opponent_id: str) -> Optional[str]:
        """Get the result of the last game against this opponent."""
        if (
            self.name in self._stats 
            and opponent_id in self._stats[self.name]["opponent_history"]
        ):
            return self._stats[self.name]["opponent_history"][opponent_id]["last_result"]
        return None
        
    def get_last_army_amount(self, opponent_id: str) -> Optional[int]:
        """Get the army amount used in the last game against this opponent."""
        if (
            self.name in self._stats 
            and opponent_id in self._stats[self.name]["opponent_history"]
        ):
            return self._stats[self.name]["opponent_history"][opponent_id].get("last_army_amount")
        return None
        
    def get_status_text(self) -> str:
        """Get status text for the build."""
        return f"Using {self.name}"
        
    @property
    def stats(self) -> Dict:
        """Get overall build statistics."""
        if self.name not in self._stats:
            return {"wins": 0, "losses": 0}
            
        # Calculate total wins/losses across all opponents
        total_wins = 0
        total_losses = 0
        for opponent_stats in self._stats[self.name]["opponent_history"].values():
            for supply_stats in opponent_stats["supply_history"].values():
                total_wins += supply_stats["wins"]
                total_losses += supply_stats["losses"]
            
        return {"wins": total_wins, "losses": total_losses}
        
    @property
    def winrate(self) -> float:
        """Get the overall winrate for this build."""
        stats = self.stats
        total_games = stats["wins"] + stats["losses"]
        if total_games == 0:
            return 0.0
        return stats["wins"] / total_games * 100
        
    async def on_step(self, bot) -> None:
        """Called each game step. Override this to implement build-specific logic."""
        pass

class DynamicLingBuild(Build):
    """Dynamic ling-focused build that adapts army size based on performance."""
    NAME = "Dynamic Ling"
    
    def __init__(self):
        super().__init__(self.NAME)
        
    async def on_step(self, bot):
        """Execute build logic each step."""
        # Build logic will be implemented here
        pass

class StandardBuild(Build):
    """Standard macro-focused build."""
    NAME = "Standard"
    
    def __init__(self):
        super().__init__("Standard")
        
    async def on_step(self, bot) -> None:
        """Execute build logic each step."""
        # Will implement specific build logic later
        pass

# Add more build classes here as we create them

def get_build(name: Optional[str] = None) -> Build:
    """Get a build by name, or return the default build if no name provided.
    
    Args:
        name: Name of the build to get
        
    Returns:
        Build instance
    """
    if name is None:
        return DynamicLingBuild()
        
    builds = {
        "Dynamic ling build": DynamicLingBuild,
        "Standard": StandardBuild
    }
    
    build_class = builds.get(name)
    if build_class is None:
        print(f"Unknown build {name}, using default build")
        return DynamicLingBuild()
        
    return build_class()
