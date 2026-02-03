with open(r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer\dynasty_trade_analyzer_v2.py', 'r', encoding='utf-8-sig') as f:
    lines = f.readlines()
    # Check lines around CFR hitters
    for i in range(244, 262):
        print(f"{i+1}: {repr(lines[i])}")
