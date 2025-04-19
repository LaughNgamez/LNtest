"""Builds for the bot to use."""
from typing import Dict, Optional
import json
import os
from pathlib import Path
import time

class Build:
    """Base class for builds."""
    DEFAULT_ARMY_AMOUNT: int = 10
    
    def __init__(self, name: str):
        self.name = name
        self._stats = self._load_stats()
        if self.name not in self._stats:
            self._stats[self.name] = {
                "opponent_history": {}  # Track results and army amounts per opponent
            }
        
        # Migrate existing records to include supply_history
        if self.name in self._stats:
            for opponent_id in self._stats[self.name]["opponent_history"]:
                opponent_stats = self._stats[self.name]["opponent_history"][opponent_id]
                if "supply_history" not in opponent_stats:
                    opponent_stats["supply_history"] = {}
                    # Initialize with current army amount if it exists
                    if "army_amount" in opponent_stats:
                        current_amount = str(opponent_stats["army_amount"])
                        opponent_stats["supply_history"][current_amount] = {
                            "wins": opponent_stats.get("wins", 0),
                            "losses": opponent_stats.get("losses", 0)
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
            
    def record_game(self, won: bool, opponent_id: str, army_supply: int):
        """Record the result of a game.
        
        Args:
            won: Whether the game was won
            opponent_id: ID of the opponent
            army_supply: The army supply amount used in this game
        """
        if self.name not in self._stats:
            self._stats[self.name] = {
                "opponent_history": {}
            }
            
        # Initialize opponent history if not exists
        if opponent_id not in self._stats[self.name]["opponent_history"]:
            self._stats[self.name]["opponent_history"][opponent_id] = {
                "wins": 0,
                "losses": 0,
                "army_amount": self.DEFAULT_ARMY_AMOUNT,
                "last_result": None,
                "timestamp": None,
                "supply_history": {}  # Track results per army supply amount
            }
            
        opponent_stats = self._stats[self.name]["opponent_history"][opponent_id]
        
        # Ensure keys exist for robustness
        if "wins" not in opponent_stats:
            opponent_stats["wins"] = 0
        if "losses" not in opponent_stats:
            opponent_stats["losses"] = 0
        if "army_amount" not in opponent_stats:
            opponent_stats["army_amount"] = self.DEFAULT_ARMY_AMOUNT
        if "supply_history" not in opponent_stats:
            opponent_stats["supply_history"] = {}
            
        # Initialize or update supply history for this army amount
        supply_key = str(army_supply)  # Convert to string for JSON compatibility
        if supply_key not in opponent_stats["supply_history"]:
            opponent_stats["supply_history"][supply_key] = {"wins": 0, "losses": 0}
            
        # Update supply history
        if won:
            opponent_stats["supply_history"][supply_key]["wins"] += 1
            opponent_stats["wins"] += 1
        else:
            opponent_stats["supply_history"][supply_key]["losses"] += 1
            opponent_stats["losses"] += 1
            
        # Update last result and timestamp
        opponent_stats["last_result"] = "won" if won else "lost"
        opponent_stats["timestamp"] = time.time()
        
        # Save stats
        self._save_stats()
        
        # Find next viable army amount
        current_amount = opponent_stats["army_amount"]
        next_amount = current_amount
        
        while next_amount < 95:
            next_amount += 5
            # Check if this amount has 3+ losses
            str_amount = str(next_amount)
            if str_amount in opponent_stats["supply_history"]:
                supply_stats = opponent_stats["supply_history"][str_amount]
                if supply_stats["losses"] >= 3:
                    continue  # Skip this amount
            # Found a viable amount
            break
                
        # If we couldn't find a viable amount or hit 95, check if all amounts have 3+ losses
        if next_amount >= 95:
            all_losing = all(
                stats["losses"] >= 3
                for amount, stats in opponent_stats["supply_history"].items()
                if int(amount) >= self.DEFAULT_ARMY_AMOUNT
            )
            if all_losing:
                next_amount = self.DEFAULT_ARMY_AMOUNT
                
        opponent_stats["army_amount"] = next_amount
                
    def get_army_amount(self, opponent_id: str) -> int:
        """Get army amount for a specific opponent.
        
        Args:
            opponent_id: ID of the opponent
            
        Returns:
            Current army amount for this opponent
        """
        if (
            self.name in self._stats 
            and opponent_id in self._stats[self.name]["opponent_history"]
        ):
            return self._stats[self.name]["opponent_history"][opponent_id]["army_amount"]
        return self.DEFAULT_ARMY_AMOUNT
        
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
            total_wins += opponent_stats.get("wins", 0)
            total_losses += opponent_stats.get("losses", 0)
            
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
    def __init__(self):
        super().__init__("Dynamic ling build")
        
    async def on_step(self, bot):
        """Execute build logic each step."""
        # Build logic will be implemented here
        pass

class StandardBuild(Build):
    """Standard macro-focused build."""
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
