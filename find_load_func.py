import sys

# Find load_consensus_rankings function
with open(r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer\dynasty_trade_analyzer_v2.py', 'r', encoding='utf-8-sig') as f:
    lines = f.readlines()
    for i, line in enumerate(lines, 1):
        if 'def load_consensus_rankings' in line:
            print(f"Function starts at line {i}")
            # Print next 100 lines
            for j in range(i-1, min(i+100, len(lines))):
                print(f"{j+1}: {lines[j].rstrip()}")
            break
