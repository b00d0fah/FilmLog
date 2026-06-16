param(
    [switch]$NoBrowser,
    [switch]$Repair,
    [switch]$InstallPython
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$WaitressExe = Join-Path $VenvDir "Scripts\waitress-serve.exe"
$RequirementsStampPath = Join-Path $VenvDir ".filmlog_requirements.txt"
$EnvPath = Join-Path $ProjectRoot ".env"
$EnvExamplePath = Join-Path $ProjectRoot ".env.example"
$RequirementsPath = Join-Path $ProjectRoot "requirements.txt"
$LogPath = Join-Path $ProjectRoot "filmlog_start.log"

function Write-Step($Message) {
    Write-Host ""
    Write-Host "== $Message ==" -ForegroundColor Cyan
}

function Write-Info($Message) {
    Write-Host $Message
}

function Write-Warn($Message) {
    Write-Host $Message -ForegroundColor Yellow
}

function Test-Command($Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-SystemPython {
    if (Test-Command "py") {
        try {
            & py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) {
                return @("py", "-3")
            }
        } catch {}
    }

    if (Test-Command "python") {
        try {
            & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) {
                return @("python")
            }
        } catch {}
    }

    return $null
}

function Invoke-Python($PythonCmd, $Arguments) {
    if ($PythonCmd.Length -gt 1) {
        & $PythonCmd[0] $PythonCmd[1] @Arguments
    } else {
        & $PythonCmd[0] @Arguments
    }
}

function Install-PythonWithWinget {
    if (-not (Test-Command "winget")) {
        throw "没有找到 Python 3.10 或更高版本，并且当前系统没有 winget。请从 https://www.python.org/downloads/ 安装 Python，安装时勾选 Add python.exe to PATH，然后重新运行 FilmLog 本地启动器.bat。"
    }

    Write-Step "安装 Python"
    Write-Info "正在通过 winget 安装 Python 3。Windows 可能会弹出确认提示。"
    winget install --id Python.Python.3.12 -e --source winget
    if ($LASTEXITCODE -ne 0) {
        throw "Python 自动安装失败。请手动安装 Python 3.10 或更高版本，然后重新运行启动器。"
    }
}

function Ensure-EnvFile {
    if (Test-Path $EnvPath) {
        return
    }
    if (-not (Test-Path $EnvExamplePath)) {
        throw "没有找到 .env.example，无法创建本地配置文件。"
    }

    Copy-Item $EnvExamplePath $EnvPath
    $secret = [Guid]::NewGuid().ToString("N")
    $content = Get-Content $EnvPath -Raw
    $content = $content -replace "FILMLOG_SECRET_KEY=.*", "FILMLOG_SECRET_KEY=$secret"
    $content = $content -replace "FILMLOG_DEBUG=.*", "FILMLOG_DEBUG=0"
    Set-Content -Path $EnvPath -Value $content -Encoding UTF8
    Write-Info "已创建本地配置文件 .env。"
}

function Get-EnvValue($Name, $Default) {
    if (-not (Test-Path $EnvPath)) {
        return $Default
    }
    $line = Get-Content $EnvPath | Where-Object { $_ -match "^\s*$([Regex]::Escape($Name))\s*=" } | Select-Object -First 1
    if (-not $line) {
        return $Default
    }
    $value = ($line -split "=", 2)[1].Trim()
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $Default
    }
    return $value
}

function Set-EnvValue($Name, $Value) {
    $line = "$Name=$Value"
    if (-not (Test-Path $EnvPath)) {
        Set-Content -Path $EnvPath -Value $line -Encoding UTF8
        return
    }

    $content = Get-Content $EnvPath
    $pattern = "^\s*$([Regex]::Escape($Name))\s*="
    $updated = $false
    $next = foreach ($item in $content) {
        if ($item -match $pattern) {
            $updated = $true
            $line
        } else {
            $item
        }
    }
    if (-not $updated) {
        $next += $line
    }
    Set-Content -Path $EnvPath -Value $next -Encoding UTF8
}

function Read-ApiConfigFile($Path) {
    $result = @{
        ApiKey = ""
        BaseUrl = ""
    }

    try {
        $rows = Get-Content -LiteralPath $Path -Encoding UTF8
    } catch {
        return $result
    }

    foreach ($row in $rows) {
        $line = $row.Trim()
        if (-not $line) {
            continue
        }

        $parts = $line -split ",", 2
        if ($parts.Count -lt 2) {
            $parts = $line -split "=", 2
        }
        if ($parts.Count -lt 2) {
            continue
        }

        $key = $parts[0].Trim().Trim('"')
        $value = $parts[1].Trim().Trim('"')
        if ($key -eq "apiKey" -or $key -eq "DASHSCOPE_API_KEY") {
            $result.ApiKey = $value
        } elseif ($key -eq "openAiCompatible" -or $key -eq "QWEN_BASE_URL") {
            $result.BaseUrl = $value
        }
    }

    return $result
}

function Find-ApiConfig {
    $patterns = @("*apiKey*.csv", "*apikey*.csv", "*dashscope*.csv", "*qwen*.csv", "*api-key*.csv")
    $files = @()
    foreach ($pattern in $patterns) {
        $files += Get-ChildItem -LiteralPath $ProjectRoot -File -Filter $pattern -ErrorAction SilentlyContinue
    }

    foreach ($file in ($files | Sort-Object FullName -Unique)) {
        $config = Read-ApiConfigFile $file.FullName
        if (-not [string]::IsNullOrWhiteSpace($config.ApiKey)) {
            return @{
                ApiKey = $config.ApiKey
                BaseUrl = $config.BaseUrl
                FileName = $file.Name
            }
        }
    }

    return $null
}

function Ensure-ApiConfig {
    $currentKey = Get-EnvValue "DASHSCOPE_API_KEY" ""
    if (-not [string]::IsNullOrWhiteSpace($currentKey)) {
        Write-Info "DashScope API Key 已配置。"
        return
    }

    $config = Find-ApiConfig
    if ($config) {
        Set-EnvValue "DASHSCOPE_API_KEY" $config.ApiKey
        if (-not [string]::IsNullOrWhiteSpace($config.BaseUrl)) {
            Set-EnvValue "QWEN_BASE_URL" $config.BaseUrl
        }
        Write-Info "已找到 API Key 文件，并写入 DashScope 配置：$($config.FileName)"
    } else {
        Write-Warn "未配置 DashScope API Key。AI 评分、照片分析和胶卷总结功能将不可用。"
    }
}

function Test-PortAvailable($HostName, $Port) {
    $listener = $null
    try {
        $address = $null
        if (-not [System.Net.IPAddress]::TryParse($HostName, [ref]$address)) {
            $address = [System.Net.Dns]::GetHostAddresses($HostName) |
                Where-Object { $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork } |
                Select-Object -First 1
        }
        if (-not $address) {
            return $false
        }
        $listener = [System.Net.Sockets.TcpListener]::new($address, [int]$Port)
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($listener) {
            $listener.Stop()
        }
    }
}

function Test-DependenciesReady {
    if (-not (Test-Path $RequirementsStampPath)) {
        return $false
    }
    $current = Get-Content $RequirementsPath -Raw
    $installed = Get-Content $RequirementsStampPath -Raw
    if ($current -ne $installed) {
        return $false
    }

    & $VenvPython -c "import flask, PIL, openai, dotenv, waitress"
    return $LASTEXITCODE -eq 0
}

try {
    Write-Host "FilmLog 本地启动器" -ForegroundColor Green
    Write-Host "项目目录：$ProjectRoot"

    Write-Step "检查 Python"
    $pythonCmd = Get-SystemPython
    if (-not $pythonCmd -and $InstallPython) {
        Install-PythonWithWinget
        $pythonCmd = Get-SystemPython
    }
    if (-not $pythonCmd) {
        Write-Warn "没有找到 Python 3.10 或更高版本。"
        if (Test-Command "winget") {
            $answer = Read-Host "是否现在通过 winget 安装 Python 3？输入 Y 后按回车继续"
            if ($answer -match "^[Yy]") {
                Install-PythonWithWinget
                $pythonCmd = Get-SystemPython
            }
        }
    }
    if (-not $pythonCmd) {
        throw "无法继续。请先安装 Python 3.10 或更高版本，然后重新运行 FilmLog 本地启动器.bat。"
    }
    Write-Info "Python 已就绪。"

    Write-Step "检查本地配置"
    Ensure-EnvFile
    Ensure-ApiConfig

    Write-Step "检查虚拟环境"
    if ($Repair -and (Test-Path $VenvDir)) {
        Write-Info "修复模式：正在重建 .venv。"
        Remove-Item $VenvDir -Recurse -Force
    }
    if (-not (Test-Path $VenvPython)) {
        Write-Info "正在创建 .venv。首次运行可能需要一两分钟。"
        Invoke-Python $pythonCmd @("-m", "venv", $VenvDir)
        if ($LASTEXITCODE -ne 0) {
            throw "创建虚拟环境失败。"
        }
    }

    Write-Step "检查依赖"
    if ($Repair -or -not (Test-DependenciesReady)) {
        Write-Info "正在安装或更新依赖。"
        & $VenvPython -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) {
            throw "升级 pip 失败。请检查网络后重试。"
        }
        & $VenvPython -m pip install -r $RequirementsPath
        if ($LASTEXITCODE -ne 0) {
            throw "安装依赖失败。请检查网络，然后重新运行启动器。"
        }
        Copy-Item $RequirementsPath $RequirementsStampPath -Force
    } else {
        Write-Info "依赖已就绪。"
    }

    Write-Step "启动 FilmLog"
    $hostName = Get-EnvValue "FILMLOG_HOST" "127.0.0.1"
    $port = [int](Get-EnvValue "FILMLOG_PORT" "5000")
    $urlHost = if ($hostName -eq "0.0.0.0") { "127.0.0.1" } else { $hostName }
    $url = "http://${urlHost}:$port"

    if ($hostName -eq "127.0.0.1" -and -not (Test-PortAvailable $hostName $port)) {
        if (-not $NoBrowser) {
            Start-Process $url
        }
        throw "端口 $port 已被占用。如果浏览器已经打开 FilmLog，说明它已经在运行；否则请关闭占用该端口的程序，或编辑 .env，把 FILMLOG_PORT 改成 5001。"
    }

    if (-not $NoBrowser) {
        Start-Job -ScriptBlock {
            param($TargetUrl)
            Start-Sleep -Seconds 2
            Start-Process $TargetUrl
        } -ArgumentList $url | Out-Null
    }

    Write-Info "请在浏览器打开：$url"
    Write-Info "保持这个窗口打开，FilmLog 才会继续运行。关闭窗口即可停止 FilmLog。"
    Write-Info "启动日志：$LogPath"
    Write-Host ""

    Push-Location $ProjectRoot
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        if (Test-Path $WaitressExe) {
            & $WaitressExe --host=$hostName --port=$port wsgi:app 2>&1 | Tee-Object -FilePath $LogPath
        } else {
            & $VenvPython -m waitress --host=$hostName --port=$port wsgi:app 2>&1 | Tee-Object -FilePath $LogPath
        }
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        Pop-Location
    }
} catch {
    Write-Host ""
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
