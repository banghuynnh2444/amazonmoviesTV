param([switch]$StartApi, [switch]$StartSync)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = 'D:\AmazonMoviesTV\runtime'
$pythonPath = Join-Path $runtimeRoot 'venv\Scripts\python.exe'
$neoHome = Join-Path $runtimeRoot 'neo4j\neo4j-community-5.26.33'
$logRoot = Join-Path $runtimeRoot 'logs'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
function Test-LocalPort([int]$Port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try { $client.Connect('127.0.0.1',$Port); return $true } catch { return $false } finally { $client.Dispose() }
}
if (-not (Test-LocalPort 27028)) {
    $mongoBinary = (Get-ChildItem -LiteralPath 'C:\Program Files\MongoDB\Server' -Filter mongod.exe -File -Recurse | Sort-Object FullName -Descending | Select-Object -First 1).FullName
    if (-not $mongoBinary) { throw 'MongoDB Server not found. See README.md for setup.' }
    Start-Process -FilePath $mongoBinary -ArgumentList @('--dbpath',(Join-Path $runtimeRoot 'mongo-data'),'--port','27028','--bind_ip','127.0.0.1','--wiredTigerCacheSizeGB','2','--logpath',(Join-Path $logRoot 'mongod.log'),'--logappend') -WindowStyle Hidden | Out-Null
}
if (-not (Test-LocalPort 7698)) {
    $env:JAVA_HOME = 'D:\BigData\jdk17'
    $env:NEO4J_HOME = $neoHome
    Start-Process -FilePath (Join-Path $neoHome 'bin\neo4j.bat') -ArgumentList 'console' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot 'neo4j-start.log') -RedirectStandardError (Join-Path $logRoot 'neo4j-start-error.log') | Out-Null
}
$deadline = (Get-Date).AddSeconds(60)
while ((-not (Test-LocalPort 27028) -or -not (Test-LocalPort 7698)) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 1 }
if (-not (Test-LocalPort 27028) -or -not (Test-LocalPort 7698)) { throw 'Database not ready. Check D:\AmazonMoviesTV\runtime\logs.' }
Push-Location $projectRoot
try {
    & $pythonPath -X utf8 -m amazon_movies doctor
    if ($StartApi -and -not (Test-LocalPort 5055)) {
        Start-Process -FilePath $pythonPath -ArgumentList '-X','utf8','-m','amazon_movies','serve' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot 'api.log') -RedirectStandardError (Join-Path $logRoot 'api-error.log') | Out-Null
    }
    if ($StartSync) {
        # Ensure only one sync worker is running.
        $existing = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'amazon_movies sync --watch' }
        if (-not $existing) {
            Start-Process -FilePath $pythonPath -ArgumentList '-X','utf8','-m','amazon_movies','sync','--watch' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot 'sync.log') -RedirectStandardError (Join-Path $logRoot 'sync-error.log') | Out-Null
        }
    }
} finally { Pop-Location }
