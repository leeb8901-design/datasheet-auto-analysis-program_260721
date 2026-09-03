# 첫 실행 준비 중 보여줄 GUI 진행창이에요 (검은 콘솔창 대신).
# 인자: [0]=중지신호 파일, [1]=상태 텍스트 파일, [2]=진행률(%) 파일
# 중지신호 파일이 생기면 창을 닫아요. 상태/진행률 파일을 계속 읽어 갱신해요.
param([string]$StopFile, [string]$StatusFile, [string]$PercentFile)

$ErrorActionPreference = "SilentlyContinue"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$form = New-Object System.Windows.Forms.Form
$form.Text = "데이터시트 다운로더 준비 중"
$form.Size = New-Object System.Drawing.Size(470, 185)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.TopMost = $true
$form.ControlBox = $false

$title = New-Object System.Windows.Forms.Label
$title.Text = "처음 실행을 위한 준비를 하고 있어요."
$title.Font = New-Object System.Drawing.Font("Segoe UI", 11, [System.Drawing.FontStyle]::Bold)
$title.Location = New-Object System.Drawing.Point(20, 16)
$title.Size = New-Object System.Drawing.Size(430, 26)
$form.Controls.Add($title)

$status = New-Object System.Windows.Forms.Label
$status.Text = "잠시만 기다려 주세요..."
$status.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$status.Location = New-Object System.Drawing.Point(20, 46)
$status.Size = New-Object System.Drawing.Size(340, 22)
$form.Controls.Add($status)

# 오른쪽 위에 큰 퍼센트 숫자
$pctLabel = New-Object System.Windows.Forms.Label
$pctLabel.Text = "0%"
$pctLabel.Font = New-Object System.Drawing.Font("Segoe UI", 11, [System.Drawing.FontStyle]::Bold)
$pctLabel.TextAlign = "MiddleRight"
$pctLabel.Location = New-Object System.Drawing.Point(360, 44)
$pctLabel.Size = New-Object System.Drawing.Size(85, 24)
$form.Controls.Add($pctLabel)

$bar = New-Object System.Windows.Forms.ProgressBar
$bar.Style = "Continuous"
$bar.Minimum = 0
$bar.Maximum = 100
$bar.Value = 0
$bar.Location = New-Object System.Drawing.Point(20, 78)
$bar.Size = New-Object System.Drawing.Size(425, 22)
$form.Controls.Add($bar)

$note = New-Object System.Windows.Forms.Label
$note.Text = "인터넷으로 필요한 구성요소를 받는 중이라 수 분 걸릴 수 있어요. 이 창을 닫지 말아 주세요."
$note.Font = New-Object System.Drawing.Font("Segoe UI", 8)
$note.ForeColor = [System.Drawing.Color]::Gray
$note.Location = New-Object System.Drawing.Point(20, 108)
$note.Size = New-Object System.Drawing.Size(430, 30)
$form.Controls.Add($note)

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 400
$timer.Add_Tick({
    if (Test-Path $StopFile) { $timer.Stop(); $form.Close(); return }
    if (Test-Path $StatusFile) {
        $t = (Get-Content -LiteralPath $StatusFile -Raw -ErrorAction SilentlyContinue)
        if ($t) { $status.Text = $t.Trim([char]0xFEFF).Trim() }  # 앞의 BOM(﻿) 문자 제거
    }
    if (Test-Path $PercentFile) {
        $p = (Get-Content -LiteralPath $PercentFile -Raw -ErrorAction SilentlyContinue)
        $n = 0
        if ([int]::TryParse(($p -replace '\D',''), [ref]$n)) {
            if ($n -lt 0) { $n = 0 } elseif ($n -gt 100) { $n = 100 }
            $bar.Value = $n
            $pctLabel.Text = "$n%"
        }
    }
})
$timer.Start()

[void]$form.ShowDialog()
