param(
    [int]$MaxMinutes = 60,
    [int]$PollSeconds = 300,
    [string]$DataPath = "",
    [string]$ExpectedDate = "",
    [switch]$CheckBrowser,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"
$dataUrl = "https://johndeleon2010.github.io/daily-ai-brief/data/latest.json"
$dashboardUrl = "https://johndeleon2010.github.io/daily-ai-brief/"
$dataRoot = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { [System.IO.Path]::GetTempPath() }
$installDir = Join-Path $dataRoot "DailyAIBrief"
$logPath = Join-Path $installDir "delivery.log"
$today = if ($ExpectedDate) { $ExpectedDate } else { Get-Date -Format "yyyy-MM-dd" }
$deadline = (Get-Date).AddMinutes($MaxMinutes)
$lastError = "The current brief is not ready."

New-Item -ItemType Directory -Path $installDir -Force | Out-Null

function Write-DeliveryLog {
    param([string]$Message)
    try {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Add-Content -Path $logPath -Value "$timestamp $Message" -Encoding UTF8
    }
    catch {
    }
}

function Get-EdgePath {
    $candidates = @()
    if (${env:ProgramFiles(x86)}) {
        $candidates += Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"
    }
    if ($env:ProgramFiles) {
        $candidates += Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe"
    }
    if ($env:LOCALAPPDATA) {
        $candidates += Join-Path $env:LOCALAPPDATA "Microsoft\Edge\Application\msedge.exe"
    }
    $installedPath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($installedPath) {
        return $installedPath
    }
    $command = Get-Command "msedge.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    throw "Microsoft Edge was not found."
}

if ($CheckBrowser) {
    $edgePath = Get-EdgePath
    Write-Host "Microsoft Edge check: PASS. Path: $edgePath"
    exit 0
}

Write-DeliveryLog "Delivery check started. Expected date: $today"

do {
    try {
        if ($DataPath) {
            $brief = Get-Content -Path $DataPath -Raw | ConvertFrom-Json
        }
        else {
            $stamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            $requestUrl = $dataUrl + "?stamp=" + $stamp
            $brief = Invoke-RestMethod -Uri $requestUrl -Headers @{ "Cache-Control" = "no-cache" }
        }
        if ($brief.date -eq $today) {
            Write-DeliveryLog "Current brief found. Published date: $($brief.date)"
            if ($NoOpen) {
                Write-Host "Brief date check: PASS"
            }
            else {
                $edgePath = Get-EdgePath
                $briefUrl = $dashboardUrl + "?date=" + $today
                Start-Process -FilePath $edgePath -ArgumentList $briefUrl
                Write-DeliveryLog "Microsoft Edge started. URL: $briefUrl"
            }
            exit 0
        }
        $lastError = "The published brief is dated $($brief.date)."
        Write-DeliveryLog $lastError
    }
    catch {
        $lastError = $_.Exception.Message
        Write-DeliveryLog "Check failed. $lastError"
    }

    if ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds $PollSeconds
    }
} while ((Get-Date) -lt $deadline)

$message = "Daily AI Brief did not publish today. Last check: $lastError"
if ($NoOpen) {
    Write-Host "Brief date check: FAILED. Last check: $lastError"
    exit 1
}
try {
    & msg.exe $env:USERNAME $message
}
catch {
    Write-Error $message
}
exit 1
