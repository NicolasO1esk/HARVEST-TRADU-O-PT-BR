# Instala a traducao PT-BR do Harvester (versao Steam, app 287020).
# Confere se os arquivos do jogo sao a mesma versao, faz backup e copia os traduzidos.
param([string]$Jogo)

$ErrorActionPreference = 'Stop'
$Patch = $PSScriptRoot
$Arquivos = [ordered]@{
    'HARVEST\DIALOG.RSP'             = @('81C37E0711B42450A7CC5FEBAA748C2860C5304DD29BEE93E4EDDA34BDCBE85A', 'FFF47F8842C3B32F0FB1A2448C7F4C18D708FC16EC92F19174B90949AE3A0756')
    'HARVEST\MENU.INI'               = @('329D4692A8F8C940BCDA9D4DA4E5EBFF84CE07451170D6A01A9F94B4256B5DD1', '2F8B413F107CC3225F559AEDC5DDC9E89DD8998EF9C9DE0926CFCF07F33992F0')
    'HARVEST\HARVEST.EXE'            = @('6A9F3844254C6B18900685F10A83CA146BC1EEC1A396D68EB7DFF16CD217E72C', '1D6AA81DB6E8B74C020CFD51BD08E192BE15624A6854A76E6C58E16C1EA21ED4')
    'HARVEST_CD\HARVESTER_DISC1.ISO' = @('DC0F61FF1F62609F6D836D429E42BFBCDF8ABFCDC2D88F53A3B7A22E01397DF6', '3768B0ED0C1D0F628E660A481A62364B4B7436965F0EB724F29D0AE9DDF1579D')
    'HARVEST_CD\HARVESTER_DISC2.ISO' = @('7DD4830756FD56C4C07EAB0A18B92C115C0487E9D0E8F5784964CE6C5556C676', '944FB24414D23360AD68726E320A5C6FB1B15AF63E8636E1642F6011E504DCDA')
    'HARVEST_CD\HARVESTER_DISC3.ISO' = @('921F5C7EA6863A61834ED788C437B9F4323A68E062E1CE7E78F3BB03B3CEDFED', 'BDFF511F72B2F2546D8E54032AA10755D0E2E8DB83699E8DEBDBED3BFD79CAD8')
}

if (-not $Jogo) {
    $padrao = 'C:\Program Files (x86)\Steam\steamapps\common\Harvester'
    $Jogo = Read-Host "Pasta do jogo (Enter para '$padrao')"
    if (-not $Jogo) { $Jogo = $padrao }
}
$Jogo = $Jogo.Trim('"')
if (-not (Test-Path (Join-Path $Jogo 'HARVEST\HARVEST.EXE'))) {
    throw "Nao achei HARVEST\HARVEST.EXE em '$Jogo'. Informe a pasta que contem HARVEST e HARVEST_CD."
}

Write-Host "Conferindo os arquivos do jogo (as ISOs demoram um pouco)..."
$problemas = @()
foreach ($rel in $Arquivos.Keys) {
    $alvo = Join-Path $Jogo $rel
    if (-not (Test-Path $alvo)) { $problemas += "FALTA: $rel"; continue }
    $h = (Get-FileHash $alvo).Hash
    if ($h -eq $Arquivos[$rel][1]) { Write-Host "  $rel ja esta traduzido"; continue }
    if ($h -ne $Arquivos[$rel][0]) { $problemas += "VERSAO DIFERENTE: $rel" }
    else { Write-Host "  $rel OK (original)" }
}
if ($problemas) {
    Write-Host ""
    $problemas | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    throw "Seus arquivos nao sao a mesma versao usada na traducao. Nada foi alterado. Veja o LEIA-ME (secao 'Se a versao for diferente')."
}

$backup = Join-Path $Jogo 'BACKUP-ORIGINAL-PTBR'
foreach ($rel in $Arquivos.Keys) {
    $alvo = Join-Path $Jogo $rel
    if ((Get-FileHash $alvo).Hash -eq $Arquivos[$rel][0]) {
        $dest = Join-Path $backup $rel
        New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null
        if (-not (Test-Path $dest)) { Copy-Item $alvo $dest }
        Write-Host "Copiando $rel ..."
        Copy-Item (Join-Path $Patch $rel) $alvo -Force
        if ((Get-FileHash $alvo).Hash -ne $Arquivos[$rel][1]) { throw "Falha ao copiar $rel" }
    }
}
Write-Host ""
Write-Host "Traducao instalada. Originais guardados em: $backup" -ForegroundColor Green
