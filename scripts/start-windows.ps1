$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
Set-Location $repoRoot

function Write-Log {
    param([string]$Message)
    Write-Host "[wp5-launcher] $Message"
}

function Ensure-EnvFile {
    if (-not (Test-Path ".env")) {
        if (Test-Path ".env.example") {
            Copy-Item ".env.example" ".env"
            Write-Log "Created .env from .env.example"
        }
        else {
            throw "Missing .env and .env.example"
        }
    }
}

function Get-EnvValue {
    param(
        [string]$Key,
        [string]$Path = ".env"
    )

    if (-not (Test-Path $Path)) {
        return ""
    }

    foreach ($line in Get-Content $Path) {
        if ($line -match '^\s*#') { continue }
        if ($line -match "^$([regex]::Escape($Key))=(.*)$") {
            $value = $Matches[1].Trim()
            if ($value.StartsWith('"') -and $value.EndsWith('"')) {
                $value = $value.Trim('"')
            }
            if ($value.StartsWith("'") -and $value.EndsWith("'")) {
                $value = $value.Trim("'")
            }
            return $value
        }
    }

    return ""
}

# First-time setup wizard

function Set-EnvValue {
    param([string]$Key, [string]$Value, [string]$File = ".env")
    $content = Get-Content $File -Raw
    if ($content -match "(?m)^$([regex]::Escape($Key))=") {
        $content = $content -replace "(?m)^$([regex]::Escape($Key))=.*", "$Key=$Value"
    } else {
        $content = $content.TrimEnd() + "`n$Key=$Value`n"
    }
    Set-Content $File $content -NoNewline
}

function Test-NeedsSetup {
    $keys = @("ANTHROPIC_API_KEY","HF_API_KEY","GEMINI_API_KEY","MISTRAL_API_KEY","KONSTANZ_API_KEY")
    foreach ($key in $keys) {
        $val = Get-EnvValue -Key $key -Path ".env"
        if ($val -and $val -ne "your_api_key_here") { return $false }
    }
    return $true
}

function Invoke-SetupWizard {
    Write-Host ""
    Write-Host "============================================================"
    Write-Host "          WP5 Platform - First-time Setup"
    Write-Host "============================================================"
    Write-Host ""
    Write-Host "  You need at least ONE API key to run the platform."
    Write-Host "  You can change these later by editing the .env file."
    Write-Host ""

    $currentPass = Get-EnvValue -Key "ADMIN_PASSPHRASE" -Path ".env"
    if (-not $currentPass -or $currentPass -eq "changeme") {
        Write-Host "-- Admin panel password ------------------------------------"
        Write-Host "  This is the password to access the researcher admin panel."
        $adminPass = Read-Host "  Choose a password (Enter to keep 'changeme')"
        if ($adminPass) {
            Set-EnvValue -Key "ADMIN_PASSPHRASE" -Value $adminPass
            Write-Host "  OK - Password saved."
        }
        Write-Host ""
    }

    Write-Host "-- LLM API Keys --------------------------------------------"
    Write-Host "  Enter keys for the providers you want to use."
    Write-Host "  Press Enter to skip any provider."
    Write-Host ""

    $providers = @(
        @{ Key="ANTHROPIC_API_KEY"; Label="Anthropic (Claude) - Director agent (recommended)"; Url="https://console.anthropic.com/" },
        @{ Key="HF_API_KEY";        Label="HuggingFace - Performer agents (chat bots)";        Url="https://huggingface.co/settings/tokens" },
        @{ Key="GEMINI_API_KEY";    Label="Google Gemini - alternative provider";              Url="https://aistudio.google.com/app/apikey" },
        @{ Key="MISTRAL_API_KEY";   Label="Mistral - alternative provider";                    Url="https://console.mistral.ai/api-keys" },
        @{ Key="KONSTANZ_API_KEY";  Label="Konstanz vLLM - university-hosted model";           Url="(contact your institution)" }
    )

    $i = 1
    foreach ($p in $providers) {
        $current = Get-EnvValue -Key $p.Key -Path ".env"
        if ($current -and $current -ne "your_api_key_here") {
            Write-Host "  [$i] $($p.Label) - already set, skipping."
            Write-Host ""
        } else {
            Write-Host "  [$i] $($p.Label)"
            Write-Host "      Get key: $($p.Url)"
            $keyVal = Read-Host "      $($p.Key)"
            if ($keyVal) {
                Set-EnvValue -Key $p.Key -Value $keyVal
                Write-Host "      OK - Saved."
            }
            Write-Host ""
        }
        $i++
    }

    if (Test-NeedsSetup) {
        Write-Host "  WARNING - No API key was provided. The platform will not work without at least one."
        Write-Host "     You can add keys later by editing the .env file in the project folder."
        Write-Host ""
        $cont = Read-Host "  Continue anyway? (y/N)"
        if ($cont -ne "y" -and $cont -ne "Y") { exit 1 }
    } else {
        Write-Host "  OK - Setup complete - this wizard will not appear again."
    }
    Write-Host ""
}

function Ensure-Docker {
    $dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $dockerCmd) {
        Write-Log "Docker not found. Trying automatic install with winget..."
        $wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
        if (-not $wingetCmd) {
            throw "winget is unavailable. Install Docker Desktop manually: https://www.docker.com/products/docker-desktop/"
        }

        winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
    }

    try {
        docker compose version | Out-Null
    }
    catch {
        throw "docker compose plugin is unavailable. Reinstall Docker Desktop and rerun."
    }
}

function Ensure-DockerRunning {
    try {
        docker info | Out-Null
        return
    }
    catch {
        Write-Log "Starting Docker Desktop..."
        $dockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
        if (-not (Test-Path $dockerDesktop)) {
            $dockerDesktop = Join-Path $env:LocalAppData "Programs\Docker\Docker\Docker Desktop.exe"
        }

        if (Test-Path $dockerDesktop) {
            Start-Process $dockerDesktop
        }

        for ($i = 0; $i -lt 60; $i++) {
            Start-Sleep -Seconds 2
            try {
                docker info | Out-Null
                return
            }
            catch {
                continue
            }
        }

        throw "Docker daemon is not running. Start Docker Desktop and rerun this script."
    }
}

function Wait-Http {
    param([string]$Url)

    for ($i = 0; $i -lt 90; $i++) {
        try {
            Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3 | Out-Null
            return
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }

    Write-Log "Timeout waiting for $Url"
}

Ensure-EnvFile
if (Test-NeedsSetup) { Invoke-SetupWizard }
Ensure-Docker
Ensure-DockerRunning

Write-Log "Starting platform with docker compose..."
docker compose up -d --build

$frontendPort = Get-EnvValue -Key "FRONTEND_PORT" -Path ".env"
if (-not $frontendPort) { $frontendPort = "3000" }
$appPort = Get-EnvValue -Key "APP_PORT" -Path ".env"
if (-not $appPort) { $appPort = "8000" }

$adminUrl = "http://localhost:$frontendPort/admin"
$domain = Get-EnvValue -Key "DOMAIN" -Path ".env"
$participantUrl = "http://localhost:$frontendPort"
if ($domain -and $domain -ne "localhost") {
    $participantUrl = "https://$domain"
}

Write-Log "Waiting for frontend and backend..."
Wait-Http -Url "http://localhost:$frontendPort"
Wait-Http -Url "http://localhost:$appPort/health"

Start-Process $adminUrl
Start-Process $participantUrl

$adminPass = Get-EnvValue -Key "ADMIN_PASSPHRASE" -Path ".env"
if (-not $adminPass) {
    $adminPass = Get-EnvValue -Key "ADMIN_PASSPHRASE" -Path ".env.example"
}
if (-not $adminPass) {
    $adminPass = "<not set>"
}

Write-Log "Admin URL: $adminUrl"
Write-Log "Participant URL: $participantUrl"
Write-Log "Initial admin password: $adminPass"
