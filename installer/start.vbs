' 바로가기가 실행하는 시작 파일이에요. launch.ps1을 "완전히 숨김"으로 실행해서
' 검은 콘솔창이 전혀 보이지 않게 해요. (준비 중에는 progress.ps1의 GUI 진행창만 보여요.)
Option Explicit
Dim sh, fso, here, cmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & here & "\launch.ps1"""
' 두 번째 인자 0 = 창 숨김, 세 번째 False = 종료를 기다리지 않음
sh.Run cmd, 0, False
