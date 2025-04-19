import argparse
from sc2 import maps
from sc2.player import Bot, Computer
from sc2.main import run_game
from sc2.data import Race, Difficulty
from bot import CompetitiveBot

def run():
    """Run the bot."""
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Run a game with the bot.",
    )
    
    parser.add_argument("--Map", type=str, help="Name of the map to use", default="2000AtmospheresAIE")
    parser.add_argument("--ComputerRace", type=str, help="Race for computer player", default="Terran")
    parser.add_argument("--ComputerDifficulty", type=str, help="Computer difficulty", default="Easy")
    parser.add_argument("--Build", type=str, help="Build to use", default=None)
    
    args = parser.parse_args()

    run_game(
        maps.get(args.Map),
        [
            Bot(Race.Zerg, CompetitiveBot(build_name=args.Build)),
            Computer(Race[args.ComputerRace], Difficulty[args.ComputerDifficulty]),
        ],
        realtime=True,
    )

if __name__ == "__main__":
    run()
