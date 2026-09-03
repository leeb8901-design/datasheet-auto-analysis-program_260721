# Mouser API 키를 입력받아 .env 파일을 만드는 스크립트예요.
# 키는 https://www.mouser.kr/api-search/ 에서 무료로 발급받을 수 있어요.
#
# .env는 프로그램 폴더(%LocalAppData%\DatasheetDownloader) 안이 아니라, 그것과 완전히 분리된
# OS 표준 사용자별 설정 폴더(%AppData%\DatasheetDownloader, 로밍)에 만들어요(2026-09-04 수정 -
# 예전엔 프로그램 폴더 안에 만들어서, 프로그램을 재설치하거나 다른 위치로 옮기면 그 안의 .env가
# 새 프로그램과 분리돼 API 키를 다시 입력해야 하는 문제가 있었음). utils/config.py도 이 자리를
# 1순위로 찾도록 맞춰뒀어요 - 둘이 반드시 같은 경로를 써야 하니 여기 바꾸면 그쪽도 같이 바꿀 것.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$userConfigDir = Join-Path $env:APPDATA "DatasheetDownloader"
$envPath = Join-Path $userConfigDir ".env"
if (Test-Path $envPath) { return }
if (-not (Test-Path $userConfigDir)) { New-Item -ItemType Directory -Path $userConfigDir -Force | Out-Null }

$key = $null
try {
    Add-Type -AssemblyName Microsoft.VisualBasic
    $msg = "Mouser API 키를 입력하세요.`n`n" +
           "키는 https://www.mouser.kr/api-search/ 에서 무료로 발급받을 수 있어요.`n" +
           "(나중에 바꾸려면 $envPath 파일을 열어 수정하세요.)"
    $key = [Microsoft.VisualBasic.Interaction]::InputBox($msg, "Mouser API 키 입력", "")
} catch {
    Write-Host "Mouser API 키를 입력하세요 (https://www.mouser.kr/api-search/ 에서 발급):"
    $key = Read-Host "MOUSER_API_KEY"
}

$key = ($key | Out-String).Trim()
if ([string]::IsNullOrWhiteSpace($key)) {
    Write-Host "[안내] 키를 입력하지 않았습니다. 나중에 $envPath 파일에 직접 넣어도 됩니다." -ForegroundColor Yellow
    # 키가 없어도 프로그램은 뜨되, 다운로드 시 오류가 나요. 빈 .env는 만들지 않아요(다음 실행 때 다시 물어봄).
    return
}

"MOUSER_API_KEY=$key" | Out-File -FilePath $envPath -Encoding ascii
Write-Host "[완료] .env 파일을 만들었습니다." -ForegroundColor Green
