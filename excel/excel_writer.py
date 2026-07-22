# 처리 결과(다운로드 상태, 분석 상태 등)를 원본 엑셀 파일에 다시 써넣는 파일이에요.

from pathlib import Path

import openpyxl
from openpyxl.styles import Font

from utils.config import COL_DATASHEET_LINK, COL_LANDING_PAGE, RESULT_COLUMNS

# 엑셀에서 링크처럼 보이도록 파란색 밑줄 글씨체를 만들어둬요.
_HYPERLINK_FONT = Font(color="0563C1", underline="single")


class ExcelResultWriter:
    """엑셀 파일을 한 번 열어두고, 행마다 결과를 채워 넣은 뒤 저장하는 역할을 해요."""

    def __init__(self, path: str, sheet_name: str):
        self.path = path
        self.sheet_name = sheet_name
        # read_only가 아니라 진짜로 "쓰기"가 가능한 모드로 열어요.
        # .xlsm(매크로 포함) 파일은 keep_vba=True로 열어야 해요. 이거 없이 열고 저장하면
        # openpyxl이 VBA 프로젝트(datasheet_helper.bas 매크로)를 통째로 지워버려서, 나중에
        # Import 양식에서 다운로드 도우미 매크로를 실행하려 해도 매크로 자체가 사라져 있는
        # 문제가 있었어요.
        keep_vba = str(path).lower().endswith(".xlsm")
        self.wb = openpyxl.load_workbook(path, keep_vba=keep_vba)
        self.ws = self.wb[sheet_name]
        self.column_map = self._ensure_result_columns()

    def _ensure_result_columns(self) -> dict[str, int]:
        # 제목 줄(1행)에 이미 있는 컬럼 이름과 번호를 읽어와요.
        header_row = 1
        headers: dict[str, int] = {}
        max_col = self.ws.max_column
        for col in range(1, max_col + 1):
            value = self.ws.cell(row=header_row, column=col).value
            if value:
                headers[str(value).strip()] = col

        # 결과 컬럼(다운로드 상태 등)이 없으면 새로 만들어요.
        next_col = max_col + 1
        for name in RESULT_COLUMNS:
            if name not in headers:
                self.ws.cell(row=header_row, column=next_col, value=name)
                headers[name] = next_col
                next_col += 1

        self.wb.save(self.path)
        return headers

    def write_row(
        self,
        row_index: int,
        values: dict[str, str],
        link_path: Path | None = None,
        reference_url: str | None = None,
        landing_url: str | None = None,
    ):
        # values 예: {"다운로드 상태": "성공 (Mouser)", "데이터시트 링크": "AD8030ARZ.pdf"}
        # link_path를 같이 주면, "데이터시트 링크" 칸이 그 로컬 파일을 여는 클릭 가능한 링크가 돼요.
        # (다운로드 성공 시) link_path가 없고 reference_url이 있으면, 같은 "데이터시트 링크" 칸이
        # 대신 그 웹 페이지를 여는 링크가 돼요. landing_url이 있으면 "제품 페이지 링크" 칸이 그
        # 제조사 제품/문서 페이지를 여는 링크가 돼요 (VBA 도우미가 직링크 재시도 실패 시 이 칸을
        # 읽어서 대신 열어요 — datasheet_helper.bas 참고).
        for key, value in values.items():
            col = self.column_map.get(key)
            if not col:
                continue
            cell = self.ws.cell(row=row_index, column=col, value=value)
            if key == COL_DATASHEET_LINK:
                if link_path is not None:
                    # 일반 윈도우 경로(C:\...) 형태로 넣어야 엑셀에서 클릭했을 때 바로 열려요.
                    # file:/// 형태(URI)로 넣으면 경로에 한글이 있을 때 인코딩이 깨져서 "파일을 열 수
                    # 없다"는 오류가 나는 경우가 있어서, 그냥 실제 경로 문자열을 그대로 써요.
                    cell.hyperlink = str(link_path.resolve())
                    cell.font = _HYPERLINK_FONT
                elif reference_url:
                    cell.hyperlink = reference_url
                    cell.font = _HYPERLINK_FONT
            elif key == COL_LANDING_PAGE and landing_url:
                cell.hyperlink = landing_url
                cell.font = _HYPERLINK_FONT

    def save(self):
        # 지금까지의 변경사항을 실제 파일에 저장해요. (Excel 자동 저장 요구사항)
        self.wb.save(self.path)

    def close(self):
        self.wb.close()
