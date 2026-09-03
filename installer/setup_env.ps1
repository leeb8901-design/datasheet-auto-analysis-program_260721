# 최초 1회 실행 환경을 자동으로 준비하는 워커 스크립트예요 (창을 직접 띄우지 않아요 - 진행창은 progress.ps1).
# 진행 상황은 logs\setup.status(현재 단계) / logs\setup.percent(진행률 0~100) / logs\setup.log(자세한 기록)에 남겨요.
# 하는 일: Python 확인/설치 -> 가상환경 -> pip 패키지(하나씩) -> scrapling/patchright 브라우저
#          -> Google Chrome 없으면 자동 설치 -> 완료 표시(.setup_done)
# 인터넷이 필요하고, 실패해도 다시 실행하면 이어서(멱등) 진행돼요.

# 주의: pip 등 네이티브 명령이 진행상황을 stderr로 출력하는데, ErrorActionPreference=Stop 이면
# PowerShell 5.1이 그 stderr를 '치명적 오류(NativeCommandError)'로 오해해 pip 도중 스크립트가
# 통째로 멈춰버려요(.setup_done 생성 실패 = 첫 실행 실패). 그래서 Continue로 두고, 진짜 실패는
# 각 단계의 $LASTEXITCODE / ExitCode 로 직접 확인해서 exit 1 합니다.
$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot

$LogDir = Join-Path $PSScriptRoot "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$LogFile = Join-Path $LogDir "setup.log"
$StatusFile = Join-Path $LogDir "setup.status"
$PercentFile = Join-Path $LogDir "setup.percent"

function Set-Progress([int]$pct, [string]$m) {
    # 진행창에 보여줄 진행률(%) + 현재 단계 + 로그 기록
    if ($pct -lt 0) { $pct = 0 } elseif ($pct -gt 100) { $pct = 100 }
    "$pct" | Out-File -LiteralPath $PercentFile -Encoding ascii
    $m | Out-File -LiteralPath $StatusFile -Encoding utf8
    "[{0}] ({1,3}%) {2}" -f (Get-Date -Format "HH:mm:ss"), $pct, $m | Out-File -LiteralPath $LogFile -Append -Encoding utf8
}
function Log($m) { "[{0}]        {1}" -f (Get-Date -Format "HH:mm:ss"), $m | Out-File -LiteralPath $LogFile -Append -Encoding utf8 }

"===== 준비 시작 $(Get-Date -Format o) =====" | Out-File -LiteralPath $LogFile -Append -Encoding utf8
Set-Progress 2 "준비를 시작합니다..."

# ---------------- ① Python 확인 / 없으면 내장 설치기로 설치 ----------------
Set-Progress 5 "Python 확인 중..."

function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.14 --version *> $null
        if ($LASTEXITCODE -eq 0) { return @("py", "-3.14") }
        & py --version *> $null
        if ($LASTEXITCODE -eq 0) { return @("py") }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        & python --version *> $null
        if ($LASTEXITCODE -eq 0) { return @("python") }
    }
    $userPy = Join-Path $env:LocalAppData "Programs\Python\Python314\python.exe"
    if (Test-Path $userPy) { return @($userPy) }
    return $null
}

$py = Find-Python
if ($null -eq $py) {
    Set-Progress 8 "Python 설치 중... (이 사용자 계정에만, 관리자 권한 불필요)"
    $pyInstaller = Join-Path $PSScriptRoot "_setup\python-3.14.6-amd64.exe"
    if (-not (Test-Path $pyInstaller)) { Log "내장 Python 설치기 없음: $pyInstaller"; exit 1 }
    $p = Start-Process -FilePath $pyInstaller -WindowStyle Hidden -Wait -PassThru -ArgumentList @(
        "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_launcher=1", "Include_pip=1", "AssociateFiles=0", "Shortcuts=0"
    )
    if ($p.ExitCode -ne 0) { Log "Python 설치 실패 (코드 $($p.ExitCode))"; exit 1 }
    $py = Find-Python
    if ($null -eq $py) { Log "Python 설치 후 실행 파일을 못 찾음. 재부팅 후 재시도 필요."; exit 1 }
}
$verText = & $py[0] $py[1..($py.Length-1)] --version 2>&1
Log "사용할 Python: $verText"

# ---------------- ② 가상환경(.venv) ----------------
Set-Progress 20 "가상환경 준비 중..."
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    & $py[0] $py[1..($py.Length-1)] -m venv .venv *>> $LogFile
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) { Log "가상환경 생성 실패"; exit 1 }
}

# ---------------- ③ pip 패키지 (하나씩 설치하며 진행률 증가) ----------------
Set-Progress 25 "pip 준비 중..."
& $venvPython -m pip install --upgrade pip *>> $LogFile

# requirements.txt에서 실제 패키지 줄만 뽑아요 (빈 줄/주석 제외).
$reqLines = @()
if (Test-Path "requirements.txt") {
    $reqLines = Get-Content "requirements.txt" | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith("#") }
}
$total = [Math]::Max($reqLines.Count, 1)
$startPct = 25; $endPct = 68   # pip 구간이 차지하는 진행률 범위
for ($i = 0; $i -lt $reqLines.Count; $i++) {
    $pkg = $reqLines[$i]
    $pct = $startPct + [int](($endPct - $startPct) * ($i) / $total)
    Set-Progress $pct ("패키지 설치 중... ({0}/{1}) {2}" -f ($i+1), $total, $pkg)
    & $venvPython -m pip install $pkg *>> $LogFile
    if ($LASTEXITCODE -ne 0) { Log "패키지 설치 실패: $pkg - 인터넷 확인 후 재시도"; exit 1 }
}
Set-Progress $endPct "패키지 설치 완료"

# ---------------- ④ scrapling / patchright 브라우저 ----------------
Set-Progress 72 "다운로드용 브라우저 설치 중... (1/2, 용량이 커요)"
$scraplingExe = Join-Path $PSScriptRoot ".venv\Scripts\scrapling.exe"
if (Test-Path $scraplingExe) { & $scraplingExe install *>> $LogFile } else { Log "scrapling.exe 없음" }
Set-Progress 85 "다운로드용 브라우저 설치 중... (2/2)"
$patchrightExe = Join-Path $PSScriptRoot ".venv\Scripts\patchright.exe"
if (Test-Path $patchrightExe) { & $patchrightExe install chromium *>> $LogFile } else { Log "patchright.exe 없음" }

# ---------------- ⑤ Google Chrome 없으면 자동 설치 ----------------
function Find-Chrome {
    $paths = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LocalAppData\Google\Chrome\Application\chrome.exe"
    )
    return ($paths | Where-Object { Test-Path $_ } | Select-Object -First 1)
}

Set-Progress 92 "Google Chrome 확인 중..."
if (Find-Chrome) {
    Log "Google Chrome 이미 있음: $(Find-Chrome)"
} else {
    Set-Progress 93 "데이터시트 다운로드에 필요한 Google Chrome 설치 중..."
    $installed = $false
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        try {
            Start-Process -FilePath "winget" -WindowStyle Hidden -Wait -ArgumentList @(
                "install","--id","Google.Chrome","-e","--silent",
                "--accept-source-agreements","--accept-package-agreements"
            )
        } catch { Log "winget Chrome 설치 예외: $_" }
        if (Find-Chrome) { $installed = $true; Log "winget으로 Chrome 설치 완료" }
    }
    if (-not $installed) {
        try {
            $chromeSetup = Join-Path $env:TEMP "ChromeStandaloneSetup64.exe"
            Log "Chrome 공식 설치기 다운로드 중..."
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri "https://dl.google.com/chrome/install/standalonesetup64.exe" `
                -OutFile $chromeSetup -UseBasicParsing
            if (Test-Path $chromeSetup) {
                Start-Process -FilePath $chromeSetup -WindowStyle Hidden -Wait -ArgumentList @("/silent","/install")
                Remove-Item -LiteralPath $chromeSetup -Force -ErrorAction SilentlyContinue
            }
        } catch { Log "Chrome 자동 설치 예외: $_" }
        if (Find-Chrome) { $installed = $true; Log "공식 설치기로 Chrome 설치 완료" }
    }
    if (-not $installed) {
        Log "Chrome 자동 설치 실패 - 사용자가 https://www.google.com/chrome 에서 직접 설치 필요."
    }
}

# ---------------- 완료 ----------------
"OK $(Get-Date -Format o)" | Out-File -LiteralPath (Join-Path $PSScriptRoot ".setup_done") -Encoding utf8
$setupDir = Join-Path $PSScriptRoot "_setup"
if (Test-Path $setupDir) { Remove-Item -Recurse -Force $setupDir -ErrorAction SilentlyContinue }
Set-Progress 100 "준비 완료!"
Log "===== 준비 완료 ====="
exit 0
