# Instala a traducao PT-BR do Harvester (versao Steam, app 287020) aplicando patches de diferenca.
# Nao contem arquivos do jogo: os trechos traduzidos sao gravados por cima da SUA copia original.
param([string]$Jogo)

$ErrorActionPreference = 'Stop'
$Patch = Join-Path $PSScriptRoot 'PATCH'
$Itens = Import-Csv (Join-Path $Patch 'MANIFESTO.csv') -Header Arquivo, Hvp, Original, Traduzido, Tamanho

function Hash($p) { (Get-FileHash $p -Algorithm SHA256).Hash }

function Aplicar-Hvp($hvp, $alvo, $tamanho) {
    $gz = New-Object System.IO.Compression.GZipStream ([System.IO.File]::OpenRead($hvp)), ([System.IO.Compression.CompressionMode]::Decompress)
    $r = New-Object System.IO.BinaryReader $gz
    try {
        $magic = [System.Text.Encoding]::ASCII.GetString($r.ReadBytes(4))
        if ($magic -ne 'HVP1') { throw "Patch invalido: $hvp" }
        $final = $r.ReadUInt64()
        $n = $r.ReadUInt32()
        $fs = [System.IO.File]::Open($alvo, 'Open', 'ReadWrite')
        try {
            for ($i = 0; $i -lt $n; $i++) {
                $off = $r.ReadUInt64()
                $len = $r.ReadUInt32()
                $dados = $r.ReadBytes($len)
                if ($dados.Length -ne $len) { throw "Patch truncado: $hvp" }
                [void]$fs.Seek([int64]$off, 'Begin')
                $fs.Write($dados, 0, $len)
            }
            $fs.SetLength([int64]$final)
        } finally { $fs.Dispose() }
    } finally { $r.Dispose() }
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
$backup = Join-Path $Jogo 'BACKUP-ORIGINAL-PTBR'

Write-Host "Conferindo os arquivos do jogo (as ISOs demoram um pouco)..."
$plano = @()
$problemas = @()
foreach ($it in $Itens) {
    $alvo = Join-Path $Jogo $it.Arquivo
    $bk = Join-Path $backup $it.Arquivo
    if (-not (Test-Path $alvo)) { $problemas += "FALTA: $($it.Arquivo)"; continue }
    $h = Hash $alvo
    if ($h -eq $it.Traduzido) { Write-Host "  $($it.Arquivo) ja esta traduzido (versao atual)"; continue }
    if ($h -eq $it.Original) { Write-Host "  $($it.Arquivo) OK (original)"; $plano += @{It = $it; De = 'jogo' }; continue }
    if ((Test-Path $bk) -and (Hash $bk) -eq $it.Original) {
        Write-Host "  $($it.Arquivo) tem traducao antiga; sera atualizado a partir do backup"
        $plano += @{It = $it; De = 'backup' }; continue
    }
    $problemas += "VERSAO DIFERENTE: $($it.Arquivo)"
}
if ($problemas) {
    Write-Host ""
    $problemas | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    throw "Seus arquivos nao sao a versao Steam usada na traducao. Nada foi alterado. Veja o LEIA-ME."
}

foreach ($p in $plano) {
    $it = $p.It
    $alvo = Join-Path $Jogo $it.Arquivo
    $bk = Join-Path $backup $it.Arquivo
    New-Item -ItemType Directory -Force (Split-Path $bk) | Out-Null
    if ($p.De -eq 'jogo') {
        if (-not (Test-Path $bk)) { Write-Host "Backup de $($it.Arquivo) ..."; Copy-Item $alvo $bk }
    } else {
        Copy-Item $bk $alvo -Force
    }
    Write-Host "Traduzindo $($it.Arquivo) ..."
    Aplicar-Hvp (Join-Path $Patch $it.Hvp) $alvo $it.Tamanho
    if ((Hash $alvo) -ne $it.Traduzido) {
        Copy-Item $bk $alvo -Force
        throw "Falha ao traduzir $($it.Arquivo); o original foi restaurado."
    }
}
Write-Host ""
Write-Host "Traducao instalada. Originais guardados em: $backup" -ForegroundColor Green
