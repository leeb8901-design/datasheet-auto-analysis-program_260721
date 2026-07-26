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

# ---------------- ⑤ 직접 챙겨야 하는 파일 안내 ----------------
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
