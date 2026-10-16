# Volta os arquivos originais do Harvester a partir do backup feito pelo INSTALAR.ps1.
param([string]$Jogo)

$ErrorActionPreference = 'Stop'
if (-not $Jogo) {
    $padrao = 'C:\Program Files (x86)\Steam\steamapps\common\Harvester'
    $Jogo = Read-Host "Pasta do jogo (Enter para '$padrao')"
    if (-not $Jogo) { $Jogo = $padrao }
}
$Jogo = $Jogo.Trim('"')
$backup = Join-Path $Jogo 'BACKUP-ORIGINAL-PTBR'
if (-not (Test-Path $backup)) { throw "Backup nao encontrado em '$backup'." }
Get-ChildItem $backup -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($backup.Length + 1)
    Write-Host "Restaurando $rel ..."
    Copy-Item $_.FullName (Join-Path $Jogo $rel) -Force
}
Write-Host "Originais restaurados." -ForegroundColor Green
