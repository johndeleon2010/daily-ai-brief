param(
    [int]$MaxMinutes = 60,
    [int]$PollSeconds = 300,
    [string]$DataPath = "",
    [string]$ExpectedDate = "",
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"
$dataUrl = "https://johndeleon2010.github.io/daily-ai-brief/data/latest.json"
$dashboardUrl = "https://johndeleon2010.github.io/daily-ai-brief/"
$today = if ($ExpectedDate) { $ExpectedDate } else { Get-Date -Format "yyyy-MM-dd" }
$deadline = (Get-Date).AddMinutes($MaxMinutes)
$lastError = "The current brief is not ready."

do {
    try {
        if ($DataPath) {
            $brief = Get-Content -Path $DataPath -Raw | ConvertFrom-Json
        }
        else {
            $stamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            $brief = Invoke-RestMethod -Uri "$dataUrl?stamp=$stamp" -Headers @{ "Cache-Control" = "no-cache" }
        }
        if ($brief.date -eq $today) {
            if ($NoOpen) {
                Write-Host "Brief date check: PASS"
            }
            else {
                Start-Process "msedge.exe" "$dashboardUrl?date=$today"
            }
            exit 0
        }
        $lastError = "The published brief is dated $($brief.date)."
    }
    catch {
        $lastError = $_.Exception.Message
    }

    if ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds $PollSeconds
    }
} while ((Get-Date) -lt $deadline)

$message = "Daily AI Brief did not publish today. Last check: $lastError"
if ($NoOpen) {
    Write-Host "Brief date check: FAILED"
    exit 1
}
try {
    & msg.exe $env:USERNAME $message
}
catch {
    Write-Error $message
}
exit 1
