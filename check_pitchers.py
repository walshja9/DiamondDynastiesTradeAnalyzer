import os
os.chdir(r"C:\Users\Alex\DiamondDynastiesTradeAnalyzer")

exec(open('dynasty_trade_analyzer_v2.py', encoding='utf-8').read().split('if __name__')[0])

# Check they're in correct dictionaries
print("Tarik Skubal in ELITE_YOUNG_PLAYERS:", "Tarik Skubal" in ELITE_YOUNG_PLAYERS)
print("Tarik Skubal in PROVEN_VETERAN_STARS:", "Tarik Skubal" in PROVEN_VETERAN_STARS)
print("Cristopher Sanchez in ELITE_YOUNG_PLAYERS:", "Cristopher Sanchez" in ELITE_YOUNG_PLAYERS)
print("Cristopher Sanchez in PROVEN_VETERAN_STARS:", "Cristopher Sanchez" in PROVEN_VETERAN_STARS)

# Calculate values
class MockPlayer:
    def __init__(self, name, position, age):
        self.name = name
        self.position = position
        self.age = age
    def is_pitcher(self):
        return self.position in ['SP', 'RP', 'P']
    def is_two_way(self):
        return False

print("\n=== Updated Values ===")
for name, pos, age in [("Tarik Skubal", "SP", 29), ("Cristopher Sanchez", "SP", 29)]:
    player = MockPlayer(name, pos, age)
    val = DynastyValueCalculator.calculate_player_value(player)
    print(f"{name}: {val:.1f}")
