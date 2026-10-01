"""Google Sheets API v4 客户端封装。

对外暴露的最小接口(FakeSheetsClient 在测试里实现同样的方法):
    read_range(a1)            -> List[List[str]]
    batch_get([a1, ...])      -> List[List[List[str]]]   # 每个 range 一份二维值
    batch_update([{range, values}, ...])  -> None         # 原子的一次 HTTP 写入

注意：Sheets API v4 的写入是“最后写入者获胜(last-write-wins)”，
不提供针对单元格的 ETag / compare-and-swap。并发安全靠 registrar 里的
读-校验-写-再校验 + 随机位置 + 抖动重试来逼近，而不是靠这一层。
"""
from __future__ import annotations

import random
import time
from typing import List

VALUE_INPUT_OPTION = "RAW"


class SheetsError(Exception):
    pass


class GoogleSheetsClient:
    _SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

    def __init__(self, spreadsheet_id: str, credentials_file: str, max_api_retries: int = 5):
        self.spreadsheet_id = spreadsheet_id
        self.max_api_retries = max_api_retries
        # 延迟导入，测试环境不装 google 库也能跑 FakeSheetsClient
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_service_account_file(credentials_file, scopes=self._SCOPES)
        self._service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self._values = self._service.spreadsheets().values()

    # ---- 内部：对瞬时错误(429/5xx)做指数退避重试 ----
    def _call(self, request):
        from googleapiclient.errors import HttpError

        last_exc = None
        for attempt in range(self.max_api_retries):
            try:
                return request().execute()
            except HttpError as e:  # noqa: PERF203
                status = getattr(e, "status_code", None) or getattr(e.resp, "status", None)
                last_exc = e
                if status in (429, 500, 502, 503, 504):
                    sleep = (2 ** attempt) + random.uniform(0, 0.5)
                    time.sleep(min(sleep, 30))
                    continue
                raise SheetsError(str(e)) from e
            except Exception as e:  # 网络类错误
                last_exc = e
                sleep = (2 ** attempt) + random.uniform(0, 0.5)
                time.sleep(min(sleep, 30))
        raise SheetsError(f"API failed after {self.max_api_retries} retries: {last_exc}")

    def read_range(self, a1: str) -> List[List[str]]:
        resp = self._call(lambda: self._values.get(
            spreadsheetId=self.spreadsheet_id, range=a1,
            valueRenderOption="FORMATTED_VALUE",
        ))
        return resp.get("values", [])

    def batch_get(self, ranges: List[str]) -> List[List[List[str]]]:
        if not ranges:
            return []
        resp = self._call(lambda: self._values.batchGet(
            spreadsheetId=self.spreadsheet_id, ranges=ranges,
            valueRenderOption="FORMATTED_VALUE",
        ))
        vrs = resp.get("valueRanges", [])
        return [vr.get("values", []) for vr in vrs]

    def batch_update(self, updates: List[dict]) -> None:
        if not updates:
            return
        body = {
            "valueInputOption": VALUE_INPUT_OPTION,
            "data": [{"range": u["range"], "values": u["values"]} for u in updates],
        }
        self._call(lambda: self._values.batchUpdate(
            spreadsheetId=self.spreadsheet_id, body=body,
        ))
