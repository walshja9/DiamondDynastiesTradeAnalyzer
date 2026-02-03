import sys

# Find the consensus weighting calculation
with open(r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer\dynasty_trade_analyzer_v2.py', 'r', encoding='utf-8-sig') as f:
    lines = f.readlines()
    for i, line in enumerate(lines, 1):
        if 'def load_consensus_rankings' in line:
            # Print from this line until we find the return statement or next function
            for j in range(i-1, min(i+250, len(lines))):
                print(f"{j+1}: {lines[j].rstrip()}")
                if j > i and 'def ' in lines[j] and lines[j][0] not in [' ', '\t']:
                    break
            break
