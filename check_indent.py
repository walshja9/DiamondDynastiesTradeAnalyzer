with open(r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer\dynasty_trade_analyzer_v2.py', 'r', encoding='utf-8-sig') as f:
    lines = f.readlines()
    # Check indentation around line 316-333
    for i in range(314, 335):
        print(f"{i+1}: {repr(lines[i][:30])}")
