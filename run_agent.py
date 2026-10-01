"""跨平台、与"当前工作目录"无关的入口。

Windows 计划任务、Linux systemd 等后台方式可能从任意目录启动本程序，
这里先把项目根目录加入模块搜索路径并切换到该目录，保证能找到 src 包与 .env。

用法:
    python  run_agent.py once   # 只扫描一次
    pythonw run_agent.py loop   # 后台长期运行(Windows 用 pythonw 不弹黑窗)
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from src.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
