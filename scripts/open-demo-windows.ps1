# Opens the demo windows for recording: Control Room + one Mattermost window per persona, each in its own
# Chrome profile (so each stays logged in as a different person). Logins: secrets/demo-users.local.json.
# Usage: .\scripts\open-demo-windows.ps1 [-Mattermost http://127.0.0.1:8065] [-Team <team-slug>]
param(
  [string]$Mattermost = $(if ($env:MATTERMOST_URL) { $env:MATTERMOST_URL } else { "http://127.0.0.1:8065" }),
  [string]$Team = $env:MATTERMOST_TEAM
)
$root = Split-Path -Parent $PSScriptRoot
$chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) { Write-Error "Chrome not found"; exit 1 }
$profiles = "$root\.state\chrome-profiles"
New-Item -ItemType Directory -Force $profiles | Out-Null
$channel = if ($Team) { "$Mattermost/$Team" } else { $Mattermost }
# x, y, w, h on a 1920x1080 screen: Control Room left 60%, personas stacked right 40%
$windows = @(
  @{ name = "control-room"; url = "http://127.0.0.1:8700/"; pos = "0,0"; size = "1152,1080" },
  @{ name = "rohan";  url = $channel; pos = "1152,0";   size = "768,360" },
  @{ name = "asha";   url = $channel; pos = "1152,360"; size = "768,360" },
  @{ name = "meera";  url = $channel; pos = "1152,720"; size = "768,360" },
  @{ name = "vikram"; url = $channel; pos = "1152,720"; size = "768,360" }
)
foreach ($w in $windows) {
  Start-Process $chrome -ArgumentList "--user-data-dir=`"$profiles\$($w.name)`"", "--new-window", "--window-position=$($w.pos)", "--window-size=$($w.size)", "--no-first-run", $w.url
}
Write-Host "Opened. Log each persona window in once (logins in secrets\demo-users.local.json); profiles remember them."
