"""A1 记号工具：列号 <-> 列字母 互转。"""
from __future__ import annotations


def col_to_a1(index: int) -> str:
    """1-based 列号 -> 列字母。1->A, 26->Z, 27->AA, 28->AB。"""
    if index < 1:
        raise ValueError(f"column index must be >= 1, got {index}")
    s = ""
    n = index
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def a1_to_col(letters: str) -> int:
    """列字母 -> 1-based 列号。A->1, AB->28。"""
    n = 0
    for ch in letters.strip().upper():
        if not ("A" <= ch <= "Z"):
            raise ValueError(f"invalid column letters: {letters!r}")
        n = n * 26 + (ord(ch) - 64)
    if n < 1:
        raise ValueError(f"invalid column letters: {letters!r}")
    return n
