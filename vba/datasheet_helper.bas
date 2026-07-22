Attribute VB_Name = "datasheet_helper"
Option Explicit

' ============================================================
' 데이터시트 다운로드 도우미 (datasheet_helper.bas)
'
' 파이썬 프로그램이 자동으로 못 받은 부품(부품리스트 시트의 "다운로드 상태" = "실패")을
' 대상으로, "데이터시트 링크" 칸의 URL을 "저장 경로" 칸이 가리키는 자리에 직접 받아옵니다.
' (이 칸은 다운로드 성공 시 로컬 파일 링크, 실패 시 웹 URL을 담는 통합 컬럼입니다 - 실패한
' 행에서는 항상 웹 URL이 들어있으므로 그대로 읽어도 안전합니다.)
'
' 동작 순서:
'   1) URLDownloadToFile(윈도우 기본 다운로드 API)로 조용히 한 번 받아봐요.
'   2) 받은 파일이 진짜 PDF인지 확인해요(맨 앞 4글자가 "%PDF"인지 - 아니면 차단 페이지일
'      가능성이 커요). 진짜 PDF면 "다운로드 상태"를 "성공 (VBA)"로 바꿔요.
'   3) 진짜 PDF가 아니면 그 파일은 지우고, 대신 기본 브라우저로 그 링크를 열어서 사람이
'      직접 "다른 이름으로 저장"할 수 있게 해줘요. (자동 요청은 막혀도, 사람이 직접 열면
'      정상적으로 보이는 사이트가 많아서예요 - 실제로 이 프로그램에서 그런 사례를 확인했어요.)
'
' 사용법:
'   1) 출력지 엑셀 파일을 엽니다.
'   2) Alt+F11 -> 메뉴 삽입(Insert) -> 모듈(Module) -> 이 파일 내용을 통째로 붙여넣습니다.
'      (또는 삽입 -> 파일 가져오기로 이 .bas 파일을 바로 import 해도 됩니다.)
'   3) 커서를 DownloadFailedDatasheets 프로시저 안에 두고 F5를 누릅니다.
'   4) 매크로 보안 경고가 뜨면 "콘텐츠 사용/매크로 사용"을 눌러주세요.
' ============================================================

' 가장 널리 검증되어 온(VB6 시절부터 쓰이던) ANSI 버전 선언이에요. 이 컴퓨터가 한글 Windows라
' ANSI 코드페이지(CP949)에 한글이 포함되어 있어서, 한글이 섞인 경로도 문제없이 동작해요.
Private Declare PtrSafe Function URLDownloadToFile Lib "urlmon" Alias "URLDownloadToFileA" _
    (ByVal pCaller As Long, ByVal szURL As String, ByVal szFileName As String, _
     ByVal dwReserved As Long, ByVal lpfnCB As Long) As Long

Private Const SHEET_NAME As String = "부품리스트"
Private Const STATUS_FAILED As String = "실패"
Private Const STATUS_SUCCESS_VBA As String = "성공 (VBA)"
Private Const STATUS_NEEDS_MANUAL As String = "실패 (브라우저로 확인 필요)"

Sub DownloadFailedDatasheets()
    Dim ws As Worksheet
    On Error Resume Next
    Set ws = ThisWorkbook.Sheets(SHEET_NAME)
    On Error GoTo 0
    If ws Is Nothing Then
        MsgBox "'" & SHEET_NAME & "' 시트를 찾을 수 없습니다.", vbExclamation
        Exit Sub
    End If

    Dim colPart As Long, colStatus As Long, colLink As Long, colSavePath As Long
    colPart = FindColumn(ws, "품번")
    colStatus = FindColumn(ws, "다운로드 상태")
    colLink = FindColumn(ws, "데이터시트 링크")
    colSavePath = FindColumn(ws, "저장 경로")

    If colPart = 0 Or colStatus = 0 Or colLink = 0 Or colSavePath = 0 Then
        MsgBox "'" & SHEET_NAME & "' 시트에서 필요한 컬럼(품번/다운로드 상태/데이터시트 링크/저장 경로)을 " & _
               "찾지 못했습니다. 이 프로그램이 만든 출력지 엑셀이 맞는지 확인해주세요.", vbExclamation
        Exit Sub
    End If

    Dim lastRow As Long
    lastRow = ws.Cells(ws.Rows.Count, colPart).End(xlUp).Row

    Dim successCount As Long, manualCount As Long, skipCount As Long
    Dim r As Long
    Dim status As String, refUrl As String, savePath As String
    Dim dlResult As Long

    For r = 2 To lastRow
        status = Trim(ws.Cells(r, colStatus).Value)
        refUrl = Trim(ws.Cells(r, colLink).Value)
        savePath = Trim(ws.Cells(r, colSavePath).Value)

        If status <> STATUS_FAILED Or refUrl = "" Or savePath = "" Then
            skipCount = skipCount + 1
            GoTo NextRow
        End If

        EnsureFolderExists FolderOf(savePath)

        dlResult = URLDownloadToFile(0, refUrl, savePath, 0, 0)

        If dlResult = 0 And IsRealPdf(savePath) Then
            ws.Cells(r, colStatus).Value = STATUS_SUCCESS_VBA
            successCount = successCount + 1
        Else
            ' 진짜 PDF가 아니면(차단 페이지 등으로 추정) 지워버리고, 브라우저로 직접 열어서
            ' 사람이 눈으로 확인 후 저장할 수 있게 해줘요.
            If Dir(savePath) <> "" Then Kill savePath
            ws.Cells(r, colStatus).Value = STATUS_NEEDS_MANUAL
            Application.FollowHyperlink refUrl, NewWindow:=True
            manualCount = manualCount + 1
        End If

NextRow:
    Next r

    ThisWorkbook.Save
    MsgBox "완료." & vbCrLf & _
           "직접 다운로드 성공: " & successCount & "건" & vbCrLf & _
           "브라우저로 열어서 확인 필요: " & manualCount & "건" & vbCrLf & _
           "대상 아님(건너뜀): " & skipCount & "건", vbInformation
End Sub

Private Function FindColumn(ws As Worksheet, headerName As String) As Long
    Dim c As Long
    Dim lastCol As Long
    lastCol = ws.Cells(1, ws.Columns.Count).End(xlToLeft).Column
    For c = 1 To lastCol
        If Trim(ws.Cells(1, c).Value) = headerName Then
            FindColumn = c
            Exit Function
        End If
    Next c
    FindColumn = 0
End Function

Private Function FolderOf(filePath As String) As String
    FolderOf = Left(filePath, InStrRev(filePath, "\"))
End Function

Private Sub EnsureFolderExists(folderPath As String)
    Dim parts() As String
    Dim built As String
    Dim i As Long

    If folderPath = "" Then Exit Sub
    If Right(folderPath, 1) = "\" Then folderPath = Left(folderPath, Len(folderPath) - 1)

    parts = Split(folderPath, "\")
    built = parts(0) & "\"  ' 드라이브 문자(예: C:)부터 시작해요.
    For i = 1 To UBound(parts)
        built = built & parts(i) & "\"
        If Dir(built, vbDirectory) = "" Then
            MkDir built
        End If
    Next i
End Sub

Private Function IsRealPdf(filePath As String) As Boolean
    ' PDF 파일은 항상 "%PDF"로 시작해요. 차단 페이지(HTML)를 잘못 받은 경우를 걸러내려고 확인해요.
    If Dir(filePath) = "" Then
        IsRealPdf = False
        Exit Function
    End If

    Dim fileNum As Integer
    Dim header As String * 4
    fileNum = FreeFile
    Open filePath For Binary Access Read As #fileNum
    If LOF(fileNum) < 4 Then
        Close #fileNum
        IsRealPdf = False
        Exit Function
    End If
    Get #fileNum, 1, header
    Close #fileNum

    IsRealPdf = (header = "%PDF")
End Function
