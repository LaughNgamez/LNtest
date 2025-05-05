"""Module for managing game statistics and opponent data."""

import csv
import json
import os
from datetime import datetime
from typing import Dict, Optional

from sc2.data import Result


class StatsManager:
    """Manages game statistics and opponent data."""

    def __init__(self, bot_instance):
        """Initialize the stats manager.
        
        Args:
            bot_instance: The main bot instance
        """
        self.bot = bot_instance
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # Go up two levels to get to main dir
        self.stats_dir = os.path.join(base_dir, "data")
        self.stats_file = os.path.join(self.stats_dir, "opponent_stats.json")
        self.history_file = os.path.join(self.stats_dir, "match_history.csv")
        self.opponent_stats = {}
        
        # Create data directory if it doesn't exist
        os.makedirs(self.stats_dir, exist_ok=True)
        
        # Load existing stats
        self.opponent_stats = self._load_opponent_stats()

    def _load_opponent_stats(self) -> Dict:
        """Load opponent statistics from JSON file.
        
        Returns:
            Dict containing opponent statistics
        """
        if os.path.exists(self.stats_file):
            with open(self.stats_file, 'r') as f:
                return json.load(f)
        return {}

    def save_opponent_stats(self) -> None:
        """Save opponent statistics to JSON file."""
        with open(self.stats_file, 'w') as f:
            json.dump(self.opponent_stats, f, indent=2)

    def log_match_history(self, result: Result) -> None:
        """Log match details to CSV file.
        
        Args:
            result: The game result (Victory, Defeat, or Tie)
        """
        write_header = not os.path.exists(self.history_file)
        
        with open(self.history_file, 'a', newline='') as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow([
                    'timestamp',
                    'opponent_id',
                    'opponent_name',
                    'opponent_race',
                    'map_name',
                    'result',
                    'game_duration_seconds',
                    'total_attacks'
                ])
            
            writer.writerow([
                datetime.now().isoformat(),
                self.bot.opponent_id,
                self.bot.opponent_name or "Unknown",
                self.bot.enemy_race,
                self.bot.game_info.map_name,
                result.name,
                int(self.bot.time - self.bot.start_time),
                self.bot.totalattacks
            ])

    def update_opponent_stats(self, result: Result) -> None:
        """Update opponent statistics.
        
        Args:
            result: The game result (Victory, Defeat, or Tie)
        """
        if self.bot.opponent_id not in self.opponent_stats:
            self.opponent_stats[self.bot.opponent_id] = {
                "name": self.bot.opponent_name or "Unknown",
                "wins": 0,
                "losses": 0,
                "ties": 0
            }
        
        stats = self.opponent_stats[self.bot.opponent_id]
        if result == Result.Victory:
            stats["wins"] += 1
        elif result == Result.Defeat:
            stats["losses"] += 1
        else:
            stats["ties"] += 1
            
        stats["name"] = self.bot.opponent_name or "Unknown"
        self.save_opponent_stats()

    def get_opponent_summary(self) -> str:
        """Get a summary of opponent statistics.
        
        Returns:
            A formatted string with opponent stats
        """
        stats = self.opponent_stats.get(
            self.bot.opponent_id,
            {"wins": 0, "losses": 0, "ties": 0}
        )
        total_games = stats["wins"] + stats["losses"] + stats["ties"]
        winrate = (stats["wins"] / total_games * 100) if total_games > 0 else 0
        
        return (f"GL HF! Total winrate {winrate:.1f}% "
                f"({stats['wins']}-{stats['losses']}-{stats['ties']})")

    async def send_chat(self, message: str) -> None:
        """Send a chat message to all players.
        
        Args:
            message: The message to send
        """
        # Send to all players
        await self.bot.chat_send(message, team_only=False)
