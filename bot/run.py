from sc2 import maps
from sc2.player import Bot, Computer
from sc2.main import run_game
from sc2.data import Race, Difficulty
from bot.bot import CompetitiveBot

def main():
    run_game(
        maps.get("2000AtmospheresAIE"),  # You can change this to any other map
        [
            Bot(Race.Zerg, CompetitiveBot()),
            Computer(Race.Terran, Difficulty.Easy)
        ],
        realtime=True
    )

if __name__ == "__main__":
    main()
