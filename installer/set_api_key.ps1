# Mouser API 키를 입력받아 User_API\ 폴더에 파일로 만드는 스크립트예요.
# 키는 https://www.mouser.kr/api-search/ 에서 무료로 발급받을 수 있어요.
#
# API 키는 이제 .env가 아니라 프로그램 폴더 바로 밑 User_API\ 폴더에, API 하나당 파일 하나로
# 둬요(2026-09-09 수정 - .env 방식 폐지, utils/config.py의 USER_API_DIR/get_mouser_api_key()
# 참고). 파일 내용은 "KEY=VALUE" 한 줄이고, 파일 이름 자체는 그냥 이름표라 프로그램은 내용의
# KEY(MOUSER_API_KEY)로 찾아요 - 그래서 여기서는 편하게 "MOUSER_API_KEY.txt"로 만들어요.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$userApiDir = Join-Path $PSScriptRoot "User_API"
$keyPath = Join-Path $userApiDir "MOUSER_API_KEY.txt"
if (Test-Path $userApiDir) {
    $existing = Get-ChildItem -LiteralPath $userApiDir -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($existing) { return }  # 이미 키 파일이 하나라도 있으면(다른 이름이어도) 새로 안 물어봄
}
New-Item -ItemType Directory -Path $userApiDir -Force | Out-Null

$key = $null
try {
    Add-Type -AssemblyName Microsoft.VisualBasic
    $msg = "Mouser API 키를 입력하세요.`n`n" +
           "키는 https://www.mouser.kr/api-search/ 에서 무료로 발급받을 수 있어요.`n" +
           "(나중에 바꾸려면 프로그램의 'API 키 관리' 버튼을 쓰거나, $keyPath 파일을 열어 수정하세요.)"
    $key = [Microsoft.VisualBasic.Interaction]::InputBox($msg, "Mouser API 키 입력", "")
} catch {
    Write-Host "Mouser API 키를 입력하세요 (https://www.mouser.kr/api-search/ 에서 발급):"
    $key = Read-Host "MOUSER_API_KEY"
}

$key = ($key | Out-String).Trim()
if ([string]::IsNullOrWhiteSpace($key)) {
    Write-Host "[안내] 키를 입력하지 않았습니다. 나중에 $keyPath 파일에 직접 넣어도 됩니다." -ForegroundColor Yellow
    # 키가 없어도 프로그램은 뜨되, 다운로드 시 오류가 나요. 빈 파일은 만들지 않아요(다음 실행 때 다시 물어봄).
    return
}

"MOUSER_API_KEY=$key" | Out-File -FilePath $keyPath -Encoding ascii
Write-Host "[완료] User_API\MOUSER_API_KEY.txt 파일을 만들었습니다." -ForegroundColor Green
