with open(r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer\dynasty_trade_analyzer_v2.py', 'r', encoding='utf-8-sig') as f:
    lines = f.readlines()
    # Print lines 280-330 with full context
    for i in range(279, min(330, len(lines))):
        print(f"{i+1}: {lines[i].rstrip()}")
