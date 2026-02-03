import sys
sys.path.insert(0, r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer')

# Find the line that builds CONSENSUS_RANKINGS
with open(r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer\dynasty_trade_analyzer_v2.py', 'r', encoding='utf-8-sig') as f:
    lines = f.readlines()
    for i, line in enumerate(lines, 1):
        if 'CONSENSUS_RANKINGS' in line or 'consensus_ranks' in line.lower():
            print(f"Line {i}: {line.rstrip()}")
