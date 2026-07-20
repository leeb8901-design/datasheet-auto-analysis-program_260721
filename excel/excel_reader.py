# 엑셀 파일을 열어서, 그 안에 적힌 부품번호/제조사를 읽어오는 파일이에요.

import openpyxl

from utils.config import MANUFACTURER_KEYWORDS, PART_LIST_SHEET_NAME, PART_NUMBER_KEYWORDS


def get_sheet_names(path: str) -> list[str]:
    # 엑셀 파일 안에는 시트(탭)가 여러 개 있을 수 있어요. 그 이름들을 전부 알려줘요.
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        return wb.sheetnames
    finally:
        wb.close()


def get_headers(path: str, sheet_name: str) -> list[str]:
    # 고른 시트의 맨 첫 줄(제목 줄)에 뭐라고 적혀있는지 읽어와요.
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet_name]
        header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
        return [str(h).strip() if h is not None else "" for h in header_row]
    finally:
        wb.close()


def find_column(headers: list[str], keywords: list[str]) -> int | None:
    # 제목 줄에서 힌트 단어가 들어있는 칸을 찾아요. 못 찾으면 None을 돌려줘요.
    for i, h in enumerate(headers):
        low = h.lower()
        if any(k in low for k in keywords):
            return i
    return None


def guess_part_number_column(headers: list[str]) -> int:
    # find_column과 비슷하지만, 못 찾으면 0번째 칸을 기본값으로 써요 (수동 선택 팝업용).
    col = find_column(headers, PART_NUMBER_KEYWORDS)
    return col if col is not None else 0


def read_part_list_sheet(path: str) -> list[dict] | None:
    """'부품리스트' 시트에서 '부품번호'와 '제조사' 컬럼을 찾아 읽어온다.
    이 시트가 없거나 부품번호 컬럼을 찾을 수 없으면 None을 반환한다.
    각 행은 {"row": 엑셀상의 실제 행 번호, "part_number": ..., "manufacturer": ... 또는 None} 형태다.
    같은 부품번호가 여러 번 나오면 처음 것만 남기고 건너뛴다(중복 제거).
    """
    sheets = get_sheet_names(path)
    if PART_LIST_SHEET_NAME not in sheets:
        return None

    headers = get_headers(path, PART_LIST_SHEET_NAME)
    part_col = find_column(headers, PART_NUMBER_KEYWORDS)
    if part_col is None:
        return None
    mfr_col = find_column(headers, MANUFACTURER_KEYWORDS)

    return _read_rows(path, PART_LIST_SHEET_NAME, part_col, mfr_col, has_header=True)


def read_custom_sheet(
    path: str, sheet_name: str, part_col: int, mfr_col: int | None, has_header: bool = True
) -> list[dict]:
    # 사용자가 팝업에서 직접 시트/컬럼을 고른 경우 쓰는 함수예요.
    return _read_rows(path, sheet_name, part_col, mfr_col, has_header)


def _read_rows(path, sheet_name, part_col, mfr_col, has_header) -> list[dict]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet_name]
        start_row = 2 if has_header else 1
        rows = []
        seen = set()  # 이미 넣은 부품번호를 기억해서 중복을 걸러내요.
        for row_idx, row in enumerate(ws.iter_rows(min_row=start_row, values_only=True), start=start_row):
            if part_col >= len(row):
                continue
            part_value = row[part_col]
            if part_value is None:
                continue
            part_text = str(part_value).strip()
            if not part_text:
                continue
            key = part_text.lower()
            if key in seen:
                continue  # 중복 품번은 건너뛰어요.
            seen.add(key)

            mfr_text = None
            if mfr_col is not None and mfr_col < len(row) and row[mfr_col] is not None:
                mfr_text = str(row[mfr_col]).strip() or None

            rows.append({"row": row_idx, "part_number": part_text, "manufacturer": mfr_text})
        return rows
    finally:
        wb.close()
