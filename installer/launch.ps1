# 프로그램 실행 조율 스크립트예요 (숨김으로 실행돼요 - 검은 콘솔창 없음).
# ① 최초면 GUI 진행창을 띄우고 환경 준비 -> ② API 키 없으면 입력 -> ③ 앱을 창 없이(pythonw) 실행
# Continue로 둬요: 자식 프로세스(setup_env/pip 등)의 stderr가 이 스크립트를 중단시키지 않도록.
# 성공 여부는 $rc(자식 종료코드)와 .setup_done 파일 존재로 직접 판단합니다.
$ErrorActionPreference = "Continue"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $Dir

$venvPython  = Join-Path $Dir ".venv\Scripts\python.exe"
$venvPythonW = Join-Path $Dir ".venv\Scripts\pythonw.exe"
$setupDone   = Join-Path $Dir ".setup_done"
$logDir      = Join-Path $Dir "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

# ---------------- ① 최초 환경 준비 ----------------
if (-not (Test-Path $venvPython) -or -not (Test-Path $setupDone)) {
    $stopFile    = Join-Path $logDir "setup.stop"
    $statusFile  = Join-Path $logDir "setup.status"
    $percentFile = Join-Path $logDir "setup.percent"
    Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue
    "준비를 시작합니다..." | Out-File -LiteralPath $statusFile -Encoding utf8
    "0" | Out-File -LiteralPath $percentFile -Encoding ascii

    # 진행창을 숨김 파워셸로 띄워요 (창 자체는 보이되, 콘솔은 없음)
    $progress = Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -PassThru -ArgumentList @(
        "-NoProfile","-ExecutionPolicy","Bypass","-File",(Join-Path $Dir "progress.ps1"),
        $stopFile, $statusFile, $percentFile
    )

    # 실제 준비 작업 (이 프로세스 자체가 이미 숨김이라 콘솔 없음)
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Dir "setup_env.ps1")
    $rc = $LASTEXITCODE

    # 진행창 닫기 신호
    "stop" | Out-File -LiteralPath $stopFile -Encoding utf8
    Start-Sleep -Milliseconds 800
    if ($progress -and -not $progress.HasExited) { try { $progress.CloseMainWindow() | Out-Null; $progress.Kill() } catch {} }

    if ($rc -ne 0 -or -not (Test-Path $setupDone)) {
        Add-Type -AssemblyName System.Windows.Forms
        $logPath = Join-Path $logDir "setup.log"
        [System.Windows.Forms.MessageBox]::Show(
            "초기 준비 중 문제가 발생했어요.`n`n인터넷 연결을 확인한 뒤 바로가기를 다시 실행하면 이어서 진행됩니다.`n`n자세한 기록: $logPath",
            "데이터시트 다운로더", "OK", "Warning") | Out-Null
        try { Start-Process notepad.exe $logPath } catch {}
        exit 1
    }
}

# ---------------- ② Mouser API 키(.env) 없으면 입력 ----------------
# .env는 프로그램 폴더(여기, $Dir)가 아니라 %AppData%\DatasheetDownloader 에 둬요(2026-09-04
# 수정 - set_api_key.ps1/utils/config.py와 같은 이유: 프로그램 폴더가 재설치/이동돼도 API 키가
# 안 사라지게 하려고 프로그램 설치 위치와 분리함). 예전 자리($Dir\.env)에 이미 있으면 그것도
# 유효한 걸로 봐요(구버전 설치에서 업그레이드한 경우 - utils/config.py가 그 경우 새 자리로
# 알아서 옮겨줌).
$userEnvPath = Join-Path $env:APPDATA "DatasheetDownloader\.env"
if (-not (Test-Path $userEnvPath) -and -not (Test-Path (Join-Path $Dir ".env"))) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Dir "set_api_key.ps1")
}

# ---------------- ③ 앱 실행 (창 없이) ----------------
$runner = if (Test-Path $venvPythonW) { $venvPythonW } else { $venvPython }
$errLog = Join-Path $logDir "app.err"
Start-Process -FilePath $runner -ArgumentList "main.py" -WorkingDirectory $Dir `
    -WindowStyle Hidden -RedirectStandardError $errLog
