Attribute VB_Name = "datasheet_helper"
Option Explicit

' ============================================================
' 데이터시트 다운로드 도우미 (datasheet_helper.bas)
'
' 파이썬 프로그램이 자동으로 못 받은 부품(부품리스트 시트의 "다운로드 상태" = "실패")을
' 대상으로, "데이터시트 링크" 칸의 URL을 "저장 경로" 칸이 가리키는 자리에 직접 받아옵니다.
'
' 동작 순서:
'   1) WinHttp로 Python 다운로더(datasheet/downloader.py)와 같은 헤더(User-Agent/Referer/Accept)를
'      붙여서 직접 받아봐요. 401/403이거나 받은 내용이 진짜 PDF가 아니면(맨 앞 4바이트가 "%PDF"가
'      아니면) 곧바로 포기하고, 타임아웃/5xx/429처럼 일시적으로 보이는 오류는 잠깐 기다렸다가
'      최대 2번 더 시도해요 (파이썬 다운로더의 재시도 정책과 같은 톤).
'   2) 그래도 실패하면, 그 링크를 기본 브라우저로 열어서 사람이 직접 "다른 이름으로 저장"할 수
'      있게 해줘요. (자동 요청은 막혀도, 사람이 직접 열면 정상적으로 보이는 사이트가 많아서예요.)
'
' 사용법:
'   1) 출력지 엑셀 파일을 엽니다.
'   2) Alt+F11 -> 메뉴 삽입(Insert) -> 모듈(Module) -> 이 파일 내용을 통째로 붙여넣습니다.
'      (또는 삽입 -> 파일 가져오기로 이 .bas 파일을 바로 import 해도 됩니다. 기존 datasheet_helper
'      모듈이 이미 있다면 먼저 지우고 새로 import 하세요.)
'   3) 커서를 DownloadFailedDatasheets 프로시저 안에 두고 F5를 누릅니다.
'   4) 매크로 보안 경고가 뜨면 "콘텐츠 사용/매크로 사용"을 눌러주세요.
'
' 이 파일은 WinHttp/ADODB(Windows 기본 제공 COM 컴포넌트)만 사용해요 - 별도 설치 필요 없어요.
' ============================================================

Private Const SHEET_NAME As String = "부품리스트"
Private Const STATUS_FAILED As String = "실패"
Private Const STATUS_SUCCESS_VBA As String = "성공 (VBA)"
Private Const STATUS_NEEDS_MANUAL As String = "실패 (브라우저로 확인 필요)"

Private Const MAX_RETRY As Long = 2
Private Const RETRY_DELAY_SECONDS As Long = 2
Private Const DOWNLOAD_USER_AGENT As String = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

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

    For r = 2 To lastRow
        status = Trim(ws.Cells(r, colStatus).Value)
        refUrl = Trim(ws.Cells(r, colLink).Value)
        savePath = Trim(ws.Cells(r, colSavePath).Value)

        If status <> STATUS_FAILED Or refUrl = "" Or savePath = "" Then
            skipCount = skipCount + 1
            GoTo NextRow
        End If

        EnsureFolderExists FolderOf(savePath)

        If TryDownload(refUrl, savePath) Then
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

' url을 최대 MAX_RETRY+1번까지 시도해서 savePath에 받아요. 성공하면 True.
Private Function TryDownload(url As String, savePath As String) As Boolean
    Dim attempt As Long, delaySec As Long, outcome As String
    delaySec = RETRY_DELAY_SECONDS

    For attempt = 0 To MAX_RETRY
        If attempt > 0 Then
            Application.Wait Now + TimeSerial(0, 0, delaySec)
            delaySec = delaySec * 2
        End If

        outcome = DownloadOnce(url, savePath)
        If outcome = "OK" Then
            TryDownload = True
            Exit Function
        ElseIf outcome = "STOP" Then
            TryDownload = False
            Exit Function
        End If
        ' outcome = "RETRY" -> 다음 시도로 넘어가요.
    Next attempt

    TryDownload = False
End Function

' 한 번 요청해봐요. "OK"(성공) / "STOP"(다시 해봐야 소용없음) / "RETRY"(일시적 오류로 보임) 중 하나를 돌려줘요.
Private Function DownloadOnce(url As String, savePath As String) As String
    On Error GoTo Fail

    Dim http As Object
    Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
    http.Open "GET", url, False
    http.SetRequestHeader "User-Agent", DOWNLOAD_USER_AGENT
    http.SetRequestHeader "Accept", "application/pdf,*/*;q=0.8"
    http.SetRequestHeader "Accept-Language", "ko-KR,ko;q=0.9,en;q=0.8"
    http.SetRequestHeader "Referer", RefererOf(url)
    http.Send

    Dim status As Long
    status = http.status

    If status = 401 Or status = 403 Then
        DownloadOnce = "STOP"
        Exit Function
    End If
    If status = 429 Or status >= 500 Then
        DownloadOnce = "RETRY"
        Exit Function
    End If
    If status <> 200 Then
        DownloadOnce = "STOP"
        Exit Function
    End If

    Dim body() As Byte
    body = http.responseBody

    If Not IsRealPdfBytes(body) Then
        DownloadOnce = "STOP"
        Exit Function
    End If

    SaveBytesToFile body, savePath
    DownloadOnce = "OK"
    Exit Function

Fail:
    ' 연결 실패/타임아웃 등은 일시적일 수 있으니 재시도해봐요.
    DownloadOnce = "RETRY"
End Function

' "https://host/path/file.pdf" -> "https://host/" (Python downloader.py의 Referer 규칙과 동일해요)
Private Function RefererOf(url As String) As String
    Dim posProtocol As Long, posSlash As Long, host As String
    posProtocol = InStr(url, "://")
    If posProtocol = 0 Then
        RefererOf = url
        Exit Function
    End If
    posSlash = InStr(posProtocol + 3, url, "/")
    If posSlash = 0 Then
        host = Mid(url, posProtocol + 3)
    Else
        host = Mid(url, posProtocol + 3, posSlash - posProtocol - 3)
    End If
    RefererOf = Left(url, posProtocol + 2) & host & "/"
End Function

Private Function IsRealPdfBytes(data() As Byte) As Boolean
    On Error GoTo NotPdf
    If (UBound(data) - LBound(data) + 1) < 4 Then GoTo NotPdf
    IsRealPdfBytes = (Chr(data(LBound(data))) = "%" And Chr(data(LBound(data) + 1)) = "P" And _
                       Chr(data(LBound(data) + 2)) = "D" And Chr(data(LBound(data) + 3)) = "F")
    Exit Function
NotPdf:
    IsRealPdfBytes = False
End Function

Private Sub SaveBytesToFile(data() As Byte, destPath As String)
    Dim stream As Object
    Set stream = CreateObject("ADODB.Stream")
    stream.Type = 1 ' adTypeBinary
    stream.Open
    stream.Write data
    stream.SaveToFile destPath, 2 ' adSaveCreateOverWrite
    stream.Close
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
