with open(r'C:\Users\Alex\DiamondDynastiesTradeAnalyzer\dynasty_trade_analyzer_v2.py', 'r', encoding='utf-8-sig') as f:
    lines = f.readlines()
    # Print lines 244-280
    for i in range(243, min(280, len(lines))):
        print(f"{i+1}: {lines[i].rstrip()}")
