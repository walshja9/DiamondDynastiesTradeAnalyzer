import sys

# Find the consensus weighting section (lines 300-320)
with open(r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer\dynasty_trade_analyzer_v2.py', 'r', encoding='utf-8-sig') as f:
    lines = f.readlines()
    
    # Find key sections
    for i, line in enumerate(lines):
        if i >= 290 and i <= 330:
            if 'for' in line or 'name' in line or 'weighted' in line.lower() or 'return' in line:
                print(f"{i+1}: {line.rstrip()}")
