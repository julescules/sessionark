param(
    [string]$Vault = 'D:\SessionArkVault',
    [string]$Label = "scheduled-$((Get-Date).ToString('yyyy-MM-dd'))"
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$env:PYTHONUTF8 = '1'

sessionark snapshot --provider codex --vault $Vault --label $Label
if ($LASTEXITCODE -ne 0) {
    throw "SessionArk snapshot failed with exit code $LASTEXITCODE"
}

sessionark verify --vault $Vault
if ($LASTEXITCODE -ne 0) {
    throw "SessionArk verification failed with exit code $LASTEXITCODE"
}
