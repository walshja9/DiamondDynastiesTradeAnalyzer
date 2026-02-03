with open(r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer\dynasty_trade_analyzer_v2.py', 'r', encoding='utf-8-sig') as f:
    lines = f.readlines()
    # Find HKB loading section
    for i in range(127, 145):
        print(f"{i+1}: {lines[i].rstrip()}")
