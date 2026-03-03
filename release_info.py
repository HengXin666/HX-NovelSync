#!/usr/bin/env python3
"""从 state.json 读取章节信息，输出 Markdown 格式的 Release 信息"""
import json
import sys
from pathlib import Path

state_file = Path(__file__).parent / "state.json"
if not state_file.exists():
    sys.exit(0)

try:
    with open(state_file, "r", encoding="utf-8") as f:
        state = json.load(f)
except Exception:
    sys.exit(0)

for book_id, info in state.items():
    name = info.get("name", "未知")
    total = info.get("chapter_count", 0)
    latest = info.get("latest_chapter", "")
    print(f"- **{name}**: 共 {total} 章")
    if latest:
        print(f"  - 最新章节: {latest}")
