#!/usr/bin/env bash
# 一键：创建虚拟环境 -> 安装依赖 -> 运行 Agent
# 用法:
#   ./run.sh          # 长期轮询运行
#   ./run.sh once     # 只扫描一次
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip >/dev/null
  ./.venv/bin/pip install -r requirements.txt
fi

exec ./.venv/bin/python -m src "${1:-loop}"
