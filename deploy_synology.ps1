param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,
    [int]$SshPort = 22,
    [Parameter(Mandatory = $true)]
    [string]$User,
    [string]$RemoteDir = "/volume1/docker/filmlog",
    [int]$AppPort = 8000
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Archive = Join-Path $env:TEMP ("filmlog_deploy_{0}.tar.gz" -f (Get-Date -Format "yyyyMMddHHmmss"))

Write-Host "Packing project and data..."
Push-Location $ProjectRoot
tar --exclude "./venv" --exclude "./__pycache__" --exclude "./*.pyc" -czf $Archive .
Pop-Location

$Target = "$User@$HostName"
Write-Host "Preparing remote directory..."
ssh -p $SshPort $Target "mkdir -p '$RemoteDir'"

Write-Host "Uploading archive..."
scp -P $SshPort $Archive "${Target}:$RemoteDir/filmlog.tar.gz"

Write-Host "Installing and starting FilmLog..."
ssh -p $SshPort $Target @"
set -e
cd '$RemoteDir'
tar -xzf filmlog.tar.gz
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
pkill -f 'waitress-serve.*wsgi:app' || true
FILMLOG_HOST=0.0.0.0 FILMLOG_PORT=$AppPort FILMLOG_DEBUG=0 nohup waitress-serve --host=0.0.0.0 --port=$AppPort wsgi:app > filmlog.log 2>&1 &
"@

Remove-Item $Archive -Force
Write-Host "Done: http://$HostName`:$AppPort"
