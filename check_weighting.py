with open(r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer\dynasty_trade_analyzer_v2.py', 'r', encoding='utf-8-sig') as f:
    lines = f.readlines()
    # Check lines 303-330 (weighting logic)
    for i in range(302, 332):
        print(f"{i+1}: {lines[i].rstrip()}")
