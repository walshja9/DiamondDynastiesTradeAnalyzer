
Set-Location "C:\Users\Alex\DiamondDynastiesTradeAnalyzer"
Write-Host "Current location: $(Get-Location)"
Write-Host "Checking git status..."
git status
Write-Host "`nAdding app.py..."
git add app.py
Write-Host "`nCommitting changes..."
git commit -m "Expand category tracking to 13 stats: add AVG, OPS, K/BB, L, ERA, WHIP, QS; consolidate SV->SV+HLD"
Write-Host "`nPushing to origin main..."
git push origin main
Write-Host "`nDone!"
