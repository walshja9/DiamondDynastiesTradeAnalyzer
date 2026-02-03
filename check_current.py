with open(r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer\dynasty_trade_analyzer_v2.py', 'r', encoding='utf-8-sig') as f:
    lines = f.readlines()
    # Check around line 245-262
    for i in range(244, 264):
        print(f"{i+1}: {lines[i].rstrip()}")
