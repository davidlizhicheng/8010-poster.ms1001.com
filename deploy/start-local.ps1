# Local dev: unified-auth + poster (Windows PowerShell)
# Note: Chrome blocks port 10080 (ERR_UNSAFE_PORT). Local auth uses 9080.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$AuthRoot = Join-Path (Split-Path -Parent $Root) "unified-auth"

function Import-DotEnvFile([string]$Path) {
  if (-not (Test-Path $Path)) { return $false }
  Get-Content $Path | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or $line -notmatch "=") { return }
    $parts = $line.Split("=", 2)
    $key = $parts[0].Trim()
    $val = $parts[1].Trim().Trim('"').Trim("'")
    if ($key -and -not [Environment]::GetEnvironmentVariable($key)) {
      [Environment]::SetEnvironmentVariable($key, $val, "Process")
    }
  }
  return $true
}

$envCandidates = @(
  (Join-Path $Root ".env"),
  (Join-Path $Root "deploy\.env.local"),
  (Join-Path (Split-Path -Parent $Root) "Gaokao\.env"),
  (Join-Path (Split-Path -Parent $Root) "brand\ip-card-ai\.env")
)
foreach ($candidate in $envCandidates) {
  if (Import-DotEnvFile $candidate) {
    Write-Host "Loaded env: $candidate"
    break
  }
}

if (-not $env:MINIMAX_API_KEY) {
  Write-Warning "MINIMAX_API_KEY not found. AI batch planning will fail until configured."
}

$AuthPort = if ($env:AUTH_PORT) { $env:AUTH_PORT } else { "3000" }
$PosterPort = if ($env:POSTER_PORT) { $env:POSTER_PORT } else { "8010" }
$env:AUTH_BASE_URL = if ($env:AUTH_BASE_URL) { $env:AUTH_BASE_URL } else { "http://127.0.0.1:$AuthPort" }
$env:POSTER_PLATFORM_URL = "http://127.0.0.1:$PosterPort"

function Stop-PortListener([int]$Port) {
  netstat -ano | Select-String ":$Port\s" | ForEach-Object {
    if ($_.Line -match 'LISTENING\s+(\d+)\s*$') {
      Stop-Process -Id ([int]$Matches[1]) -Force -ErrorAction SilentlyContinue
    }
  }
}

Write-Host "Stopping old listeners on $AuthPort / $PosterPort / 10080 ..."
Stop-PortListener ([int]$AuthPort)
Stop-PortListener ([int]$PosterPort)
Stop-PortListener 10080
Start-Sleep -Seconds 1

$authUrl = "http://127.0.0.1:$AuthPort"
$posterUrl = "http://127.0.0.1:$PosterPort"

Write-Host "Starting unified-auth on $authUrl ..."
Start-Process -FilePath "powershell" -ArgumentList @(
  "-NoProfile", "-Command",
  "Set-Location '$AuthRoot'; `$env:PORT='$AuthPort'; `$env:POSTER_PLATFORM_URL='$posterUrl'; node server.js"
) -WindowStyle Minimized

Write-Host "Starting poster on $posterUrl ..."
Start-Process -FilePath "powershell" -ArgumentList @(
  "-NoProfile", "-Command",
  "Set-Location '$Root'; `$env:PORT='$PosterPort'; `$env:AUTH_BASE_URL='$authUrl'; python server.py"
) -WindowStyle Minimized

Start-Sleep -Seconds 3

try {
  $auth = Invoke-WebRequest -Uri "$authUrl/api/auth/health" -UseBasicParsing -TimeoutSec 10
  Write-Host "unified-auth: $($auth.StatusCode)"
} catch {
  Write-Warning "unified-auth not ready: $($_.Exception.Message)"
}

try {
  $poster = Invoke-WebRequest -Uri "$posterUrl/api/config" -UseBasicParsing -TimeoutSec 10
  $cfg = $poster.Content | ConvertFrom-Json
  if (-not $cfg.minimax_ready) { Write-Warning "minimax_ready=false - check MINIMAX_API_KEY" }
  Write-Host "poster: $($poster.StatusCode) auth=$($cfg.unified_auth_url) minimax_ready=$($cfg.minimax_ready)"
} catch {
  Write-Warning "poster not ready: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "Open in browser:"
Write-Host "  Login:    $authUrl/login?redirect=$posterUrl/generate.html"
Write-Host "  Generate: $posterUrl/generate.html"
Write-Host "  Billing:  $authUrl/billing?platform=poster.ms1001.com&plan=pack_20"
Write-Host "  Boss:     18665898305 / test123456"
