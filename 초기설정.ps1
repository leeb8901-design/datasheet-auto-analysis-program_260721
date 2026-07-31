# 다른 컴퓨터에서 이 프로젝트를 처음 받았을 때, 실행 환경을 자동으로 세팅해주는 스크립트예요.
# 하는 일: ① Python 확인 -> ② 가상환경(.venv) 생성 -> ③ pip 패키지 설치 ->
#          ④ scrapling(Playwright) 브라우저 설치 -> ⑤ .env 등 직접 챙겨야 하는 파일 안내
#
# git으로 안 옮겨지는 것(.env의 MOUSER_API_KEY, Download_ datasheets 폴더)은 이 스크립트가
# 대신 만들어주지 않아요 - 비밀값이라 자동화하면 안 되고, 사용자가 직접 복사해와야 해요.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Write-Step($message) {
    Write-Host ""
    Write-Host "==> $message" -ForegroundColor Cyan
}

function Write-Warn($message) {
    Write-Host "[경고] $message" -ForegroundColor Yellow
}

function Write-Err($message) {
    Write-Host "[오류] $message" -ForegroundColor Red
}

# ---------------- ① Python 확인 ----------------
Write-Step "Python 확인 중..."

$pythonExe = $null

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.14 --version *> $null
    if ($LASTEXITCODE -eq 0) {
        $pythonExe = @("py", "-3.14")
    } else {
        $pythonExe = @("py")
    }
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonExe = @("python")
}

if ($null -eq $pythonExe) {
    Write-Err "Python을 찾을 수 없습니다. https://python.org 에서 Python 3.14를 설치한 뒤 다시 실행하세요."
    exit 1
}

$versionText = & $pythonExe[0] $pythonExe[1..($pythonExe.Length - 1)] --version
Write-Host "  찾음: $versionText"
if ($versionText -notmatch "3\.14") {
    Write-Warn "이 프로젝트는 Python 3.14 기준으로 만들어졌습니다. 버전이 다르면 일부 패키지 설치가 안 될 수 있어요."
}

# ---------------- ② 가상환경(.venv) 생성 ----------------
Write-Step "가상환경(.venv) 확인 중..."

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (Test-Path $venvPython) {
    Write-Host "  이미 있음 - 새로 만들지 않습니다."
} else {
    Write-Host "  .venv가 없어서 새로 만듭니다..."
    & $pythonExe[0] $pythonExe[1..($pythonExe.Length - 1)] -m venv .venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
        Write-Err "가상환경 생성에 실패했습니다."
        exit 1
    }
    Write-Host "  생성 완료."
}

# ---------------- ③ pip 패키지 설치 ----------------
Write-Step "pip 패키지 설치 중... (시간이 좀 걸릴 수 있어요)"

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Err "requirements.txt 설치 중 오류가 발생했습니다. 위 로그를 확인하세요."
    exit 1
}
Write-Host "  패키지 설치 완료."

# ---------------- ④ scrapling(Playwright) 브라우저 설치 ----------------
Write-Step "데이터시트 다운로드용 브라우저(Chromium) 설치 중... (최초 1회, 용량이 좀 커요)"

$scraplingExe = Join-Path $PSScriptRoot ".venv\Scripts\scrapling.exe"
if (Test-Path $scraplingExe) {
    & $scraplingExe install
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "브라우저 설치가 실패한 것 같습니다. 나중에 직접 '.venv\Scripts\scrapling.exe install'을 실행해보세요."
        Write-Warn "Windows에서 'side-by-side 구성이 잘못됨' 오류가 나면 Visual C++ 재배포 패키지가 없는 경우입니다:"
        Write-Warn "  winget install --id Microsoft.VCRedist.2015+.x64 -e"
    } else {
        Write-Host "  브라우저 설치 완료."
    }
} else {
    Write-Warn "scrapling.exe를 찾지 못했습니다. requirements.txt 설치가 제대로 됐는지 확인하세요."
}

# scrapling의 StealthyFetcher는 실제로는 patchright(패치된 Playwright)로 브라우저를 띄워요.
# 'scrapling install'만으로는 patchright 전용 Chromium(chrome-win64\chrome.exe)이 빠져서
# 실행 시 "Executable doesn't exist ... chromium-xxxx\chrome-win64\chrome.exe" 오류가 나요.
# 그래서 patchright 브라우저를 반드시 따로 설치해줘야 해요 (이미 있으면 즉시 통과).
$patchrightExe = Join-Path $PSScriptRoot ".venv\Scripts\patchright.exe"
if (Test-Path $patchrightExe) {
    & $patchrightExe install chromium
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "patchright 브라우저 설치가 실패했습니다. 나중에 직접 '.venv\Scripts\patchright.exe install chromium'을 실행해보세요."
    } else {
        Write-Host "  patchright용 Chromium 설치 완료."
    }
} else {
    Write-Warn "patchright.exe를 찾지 못했습니다. requirements.txt(scrapling[fetchers]) 설치가 제대로 됐는지 확인하세요."
}

# ---------------- ⑤ 데이터시트 다운로드용 브라우저(실제 Chrome) 점검 ----------------
Write-Step "데이터시트 다운로드용 브라우저(실제 Google Chrome) 확인 중..."

# [중요 - 2026-07-31에 실제로 겪은 문제와 해결법]
# scrapling이 내려받는 'Chrome for Testing' 번들 브라우저(chrome.exe)가 일부 Windows에서
# side-by-side(SxS) 오류로 아예 실행되지 않습니다.
#   - 증상(로그): "side-by-side configuration is incorrect" / "spawn UNKNOWN" /
#                 "Executable doesn't exist ... chromium-xxxx\chrome-win64\chrome.exe"
#   - 원인: chrome.exe 매니페스트가 요구하는 SxS 어셈블리(예: 149.0.7827.55)를 Windows가 못 만듦.
#           번들 브라우저를 지우고 새로 받아도, VC++ 재배포판을 복구해도 안 고쳐짐.
#           (검증됨: headless_shell은 되지만 스텔스용 '풀 chrome.exe'만 실패.)
#   - 해결: 프로그램은 이 문제를 피하려고 기본적으로 '시스템에 설치된 진짜 Google Chrome'을
#           사용합니다 (datasheet/downloader.py 의 real_chrome=True). 그래서 실제 Chrome이 필요해요.
$chromePaths = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LocalAppData\Google\Chrome\Application\chrome.exe"
)
$chromeFound = $chromePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($chromeFound) {
    Write-Host "  실제 Google Chrome 찾음: $chromeFound"
    Write-Host "  다운로드는 이 Chrome으로 실행돼요 (번들 브라우저 SxS 문제를 피함)."
} else {
    Write-Warn "실제 Google Chrome이 설치되어 있지 않습니다. 데이터시트 다운로드가 실패할 수 있어요."
    Write-Warn "권장 해결: Google Chrome을 설치하세요 ->  winget install --id Google.Chrome -e"
    Write-Warn "Chrome을 못 쓰는 환경이면, 번들 브라우저를 강제로 쓰도록 환경변수를 켤 수 있어요(이 PC에서"
    Write-Warn "번들 브라우저가 SxS로 실패하면 소용없음):  setx SCRAPLING_REAL_CHROME 0"
}

# ---------------- ⑥ 직접 챙겨야 하는 파일 안내 ----------------
Write-Step "직접 옮겨와야 하는 파일 확인 중..."

$envPath = Join-Path $PSScriptRoot ".env"
if (Test-Path $envPath) {
    Write-Host "  .env 파일이 있습니다."
} else {
    Write-Warn ".env 파일이 없습니다! MOUSER_API_KEY가 없으면 프로그램이 바로 오류를 냅니다."
    Write-Warn "원래 컴퓨터의 .env 파일을 이 폴더($PSScriptRoot)에 직접 복사해서 넣어주세요 (git으로는 안 옮겨져요)."
}

$dlDir = Join-Path $PSScriptRoot "Download_ datasheets"
if (-not (Test-Path $dlDir)) {
    Write-Host "  (참고) 'Download_ datasheets' 폴더가 아직 없습니다 - 처음 다운로드할 때 자동으로 만들어져요."
}

Write-Step "세팅 완료!"
if (Test-Path $envPath) {
    Write-Host "이제 '프로그램_실행.bat'을 실행하면 됩니다." -ForegroundColor Green
} else {
    Write-Host "'.env' 파일만 채워 넣으면 '프로그램_실행.bat'으로 바로 시작할 수 있습니다." -ForegroundColor Green
}
