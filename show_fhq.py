with open(r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer\dynasty_trade_analyzer_v2.py', 'r', encoding='utf-8-sig') as f:
    lines = f.readlines()
    # Find FHQ loading section
    for i in range(108, 126):
        print(f"{i+1}: {lines[i].rstrip()}")
