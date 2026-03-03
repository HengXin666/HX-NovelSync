#!/usr/bin/env python3
"""
HX-NovelSync - 小说自动同步
通过调用 Tomato-Novel-Downloader 命令行工具下载番茄小说。
参考: https://github.com/zhongbai2333/Tomato-Novel-Downloader

本脚本负责编排：
  1. 下载最新版 Tomato-Novel-Downloader Linux 二进制
  2. 生成 config.yml 配置
  3. 逐本调用 --download <book_id> 下载小说
  4. 收集结果并输出到 GitHub Actions
"""

import json
import os
import re
import sys
import glob
import shutil
import stat
import subprocess
import time
from pathlib import Path

import requests

# ===================== 常量 =====================

WORK_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = WORK_DIR / "novels.json"
OUTPUT_DIR = WORK_DIR / "output"
STATE_FILE = WORK_DIR / "state.json"

# Tomato-Novel-Downloader 相关
TOMATO_REPO = "zhongbai2333/Tomato-Novel-Downloader"
TOMATO_BIN_DIR = WORK_DIR / "bin"
TOMATO_DATA_DIR = WORK_DIR / "tomato_data"  # 工作目录，存放 config.yml 和下载内容
TOMATO_BIN_NAME = "tomato-novel-downloader"

# TTS 配置
DEFAULT_TTS_VOICE = "zh-CN-YunxiNeural"  # 默认发音人
DEFAULT_TTS_RATE = "+0%"
DEFAULT_TTS_FORMAT = "mp3"
DEFAULT_TTS_CONCURRENCY = 2


# ===================== 下载二进制 =====================


def get_latest_release_info():
    """获取最新 Release 信息"""
    url = f"https://api.github.com/repos/{TOMATO_REPO}/releases/latest"
    headers = {}
    # 如果有 GITHUB_TOKEN 则使用，避免限流
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"  ⚠️ 获取 Release 信息失败: {e}")

    # 如果 latest 失败，尝试列出所有 release 取第一个
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{TOMATO_REPO}/releases?per_page=1",
            headers=headers,
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data and isinstance(data, list):
                return data[0]
    except Exception:
        pass

    return None


def download_tomato_binary():
    """下载最新版 Tomato-Novel-Downloader Linux amd64 二进制"""
    print("  📥 获取 Tomato-Novel-Downloader 最新版本...")

    release = get_latest_release_info()
    if not release:
        print("  ❌ 无法获取 Release 信息")
        return None

    tag = release.get("tag_name", "unknown")
    print(f"  📌 最新版本: {tag}")

    # 查找 Linux amd64 二进制（不是 musl 版，也不是 arm64）
    target_asset = None
    for asset in release.get("assets", []):
        name = asset["name"]
        # 匹配 TomatoNovelDownloader-Linux_amd64-xxx 但排除 musl 和 arm64
        if "Linux" in name and "amd64" in name and "musl" not in name and "arm" not in name:
            target_asset = asset
            break

    if not target_asset:
        print("  ❌ 未找到 Linux amd64 二进制")
        print(f"  可用 assets: {[a['name'] for a in release.get('assets', [])]}")
        return None

    download_url = target_asset["browser_download_url"]
    file_name = target_asset["name"]
    file_size = target_asset.get("size", 0)

    print(f"  📦 下载: {file_name} ({file_size / 1024 / 1024:.1f}MB)")

    os.makedirs(TOMATO_BIN_DIR, exist_ok=True)
    bin_path = TOMATO_BIN_DIR / TOMATO_BIN_NAME

    try:
        resp = requests.get(download_url, timeout=120, stream=True)
        if resp.status_code != 200:
            print(f"  ❌ 下载失败: HTTP {resp.status_code}")
            return None

        with open(bin_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        # 设置可执行权限
        bin_path.chmod(bin_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        # 验证二进制
        result = subprocess.run(
            [str(bin_path), "--version"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            version_info = result.stdout.strip() or result.stderr.strip()
            print(f"  ✅ 二进制验证通过: {version_info}")
            return bin_path
        else:
            print(f"  ⚠️ 二进制验证失败 (rc={result.returncode}): {result.stderr.strip()}")
            return bin_path  # 仍然返回，可能只是版本输出格式不同

    except Exception as e:
        print(f"  ❌ 下载二进制失败: {e}")
        return None


# ===================== 配置生成 =====================


def generate_config_yml(enable_tts=False):
    """
    生成 Tomato-Novel-Downloader 的 config.yml
    """
    config = {
        "old_cli": False,
        "max_workers": 1,
        "request_timeout": 15,
        "max_retries": 5,
        "max_wait_time": 1200,
        "min_wait_time": 1000,
        "novel_format": "txt",
        "bulk_files": False,
        "auto_clear_dump": True,
        "auto_open_downloaded_files": False,
        "save_path": str(TOMATO_DATA_DIR / "downloads"),
        "use_official_api": True,
        "api_endpoints": [],
        "enable_audiobook": enable_tts,
        "audiobook_voice": DEFAULT_TTS_VOICE,
        "audiobook_rate": DEFAULT_TTS_RATE,
        "audiobook_format": DEFAULT_TTS_FORMAT,
        "audiobook_concurrency": DEFAULT_TTS_CONCURRENCY,
        "audiobook_tts_provider": "edge",
        "allow_overwrite_files": True,
        "preferred_book_name_field": "book_name",
    }

    os.makedirs(TOMATO_DATA_DIR, exist_ok=True)
    config_path = TOMATO_DATA_DIR / "config.yml"

    # 手动写 YAML（避免引入 pyyaml 依赖）
    lines = []
    for key, value in config.items():
        if isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, (int, float)):
            lines.append(f"{key}: {value}")
        elif isinstance(value, str):
            # 对路径等含特殊字符的值用引号
            if any(c in value for c in ":/\\{}[]#&*!|>'\"%@`"):
                lines.append(f'{key}: "{value}"')
            else:
                lines.append(f"{key}: {value}")
        elif isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                for item in value:
                    lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {value}")

    with open(config_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"  📝 配置文件已生成: {config_path}")
    if enable_tts:
        print(f"  🔊 TTS 已启用 (发音人: {DEFAULT_TTS_VOICE}, 格式: {DEFAULT_TTS_FORMAT})")

    return config_path


# ===================== 执行下载 =====================


def run_download(bin_path, book_id, book_name=""):
    """
    调用 Tomato-Novel-Downloader 下载指定书籍
    返回: (success: bool, output: str)
    """
    cmd = [
        str(bin_path),
        "--download", str(book_id),
        "--data-dir", str(TOMATO_DATA_DIR),
    ]

    display_name = f"《{book_name}》" if book_name else f"book_id={book_id}"
    print(f"  🚀 执行下载: {display_name}")
    print(f"  💻 命令: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,  # 30分钟超时
            cwd=str(TOMATO_DATA_DIR),
            env={**os.environ, "RUST_LOG": "info"},
        )

        output = result.stdout + "\n" + result.stderr
        # 输出日志（逐行带前缀）
        for line in output.strip().split("\n"):
            if line.strip():
                print(f"    | {line}")

        if result.returncode == 0:
            print(f"  ✅ 下载完成: {display_name}")
            return True, output
        else:
            print(f"  ❌ 下载失败 (exit code={result.returncode}): {display_name}")
            return False, output

    except subprocess.TimeoutExpired:
        print(f"  ❌ 下载超时 (30分钟): {display_name}")
        return False, "timeout"
    except Exception as e:
        print(f"  ❌ 执行异常: {e}")
        return False, str(e)


def find_downloaded_files(book_id):
    """
    查找下载完成的文件
    Tomato-Novel-Downloader 的输出目录结构:
      {save_path}/{book_id}_{book_name}/
        ├── xxx.txt (或 xxx.epub)
        └── {book_name}_audio/  (如果启用了TTS)
            ├── 0001-第一章.mp3
            └── ...
    返回: {"txt_files": [...], "audio_dir": str|None, "book_dir": str|None}
    """
    downloads_dir = TOMATO_DATA_DIR / "downloads"
    if not downloads_dir.exists():
        return {"txt_files": [], "audio_dir": None, "book_dir": None}

    # 查找以 book_id 开头的目录
    book_dirs = []
    for item in downloads_dir.iterdir():
        if item.is_dir() and item.name.startswith(str(book_id)):
            book_dirs.append(item)

    if not book_dirs:
        # 也可能直接在 downloads_dir 下
        book_dirs = [downloads_dir]

    result = {"txt_files": [], "audio_dir": None, "book_dir": None}

    for book_dir in book_dirs:
        result["book_dir"] = str(book_dir)

        # 查找 txt 文件
        for txt in book_dir.glob("*.txt"):
            result["txt_files"].append(str(txt))

        # 查找 epub 文件（如果有的话也收集）
        for epub in book_dir.glob("*.epub"):
            result["txt_files"].append(str(epub))

        # 查找音频目录
        for audio_dir in book_dir.iterdir():
            if audio_dir.is_dir() and ("audio" in audio_dir.name.lower() or "tts" in audio_dir.name.lower()):
                audio_files = list(audio_dir.glob("*.mp3")) + list(audio_dir.glob("*.wav"))
                if audio_files:
                    result["audio_dir"] = str(audio_dir)
                    print(f"  🔊 找到 {len(audio_files)} 个音频文件: {audio_dir.name}")

    return result


# ===================== 状态管理 =====================


def load_state():
    """加载上次的下载状态"""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state):
    """保存下载状态"""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  ⚠️ 保存状态失败: {e}")


def sanitize_filename(filename):
    """清理文件名中的非法字符"""
    result = re.sub(r'[\\/*?:"<>|：；""''【】]', '_', filename)
    result = re.sub(r'_+', '_', result)
    result = result.strip('_ ')
    return result if result else "unknown"


# ===================== 主处理逻辑 =====================


def process_novel(novel, state, bin_path, enable_tts=False):
    """处理单本小说"""
    name = novel["name"]
    author = novel["author"]
    book_id = novel.get("book_id", "")

    print(f"\n{'='*50}")
    print(f"📖 处理: 《{name}》 [作者: {author}]")
    print(f"{'='*50}")

    if not book_id:
        print("  ❌ 未配置 book_id")
        return {"name": name, "author": author, "success": False, "reason": "no_book_id"}

    print(f"  📌 book_id: {book_id}")

    # 执行下载
    success, output = run_download(bin_path, book_id, name)

    if not success:
        return {
            "name": name, "author": author, "success": False,
            "reason": f"download_failed",
        }

    # 查找下载的文件
    files = find_downloaded_files(book_id)

    if not files["txt_files"]:
        print("  ⚠️ 未找到下载的文本文件")
        return {
            "name": name, "author": author, "success": False,
            "reason": "no_output_files",
        }

    # 将文件复制到 output 目录，以标准命名格式
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    target_filename = f"{sanitize_filename(name)}-{sanitize_filename(author)}.txt"
    target_path = OUTPUT_DIR / target_filename

    # 取第一个 txt 文件
    src_file = files["txt_files"][0]
    shutil.copy2(src_file, target_path)
    file_size = target_path.stat().st_size
    print(f"  💾 已复制到: {target_filename} ({file_size / 1024 / 1024:.1f}MB)")

    # 如果有音频文件，也打包复制到 output
    audio_info = None
    if files["audio_dir"]:
        audio_src = Path(files["audio_dir"])
        audio_dest = OUTPUT_DIR / f"{sanitize_filename(name)}-{sanitize_filename(author)}_audio"
        if audio_dest.exists():
            shutil.rmtree(audio_dest)
        shutil.copytree(audio_src, audio_dest)
        audio_count = len(list(audio_dest.glob("*.mp3"))) + len(list(audio_dest.glob("*.wav")))
        audio_info = {"dir": str(audio_dest), "count": audio_count}
        print(f"  🔊 音频已复制: {audio_count} 个文件")

    # 解析章节信息（从输出中提取或从文件统计）
    chapter_count = 0
    latest_chapter = ""

    # 尝试从下载输出中解析章节信息
    # Tomato-Novel-Downloader 会输出类似 "开始下载：xxx (1441 章)" 的信息
    ch_match = re.search(r'(\d+)\s*章', output)
    if ch_match:
        chapter_count = int(ch_match.group(1))

    # 尝试从 txt 文件中获取最后一个章节标题
    try:
        with open(target_path, "r", encoding="utf-8") as f:
            content = f.read()
        # 查找最后一个章节标题（通常格式为 "第xxx章 xxx"）
        chapter_titles = re.findall(r'(第\d+章\s+\S+)', content)
        if chapter_titles:
            latest_chapter = chapter_titles[-1].strip()
            if not chapter_count:
                chapter_count = len(chapter_titles)
    except Exception:
        pass

    print(f"  📊 章节数: {chapter_count}")
    if latest_chapter:
        print(f"  📖 最新章节: {latest_chapter}")

    # 更新状态
    state_key = str(book_id)
    state[state_key] = {
        "name": name,
        "author": author,
        "chapter_count": chapter_count,
        "latest_chapter": latest_chapter,
        "content_file": str(target_path),
        "last_update": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    result = {
        "name": name, "author": author, "success": True,
        "filename": target_filename, "file_size": file_size,
        "new_chapters": chapter_count,  # 首次下载时 new == total
        "total_chapters": chapter_count,
        "fail_count": 0, "latest_chapter": latest_chapter,
    }

    if audio_info:
        result["audio_count"] = audio_info["count"]

    return result


def load_config():
    """加载配置文件"""
    if not CONFIG_FILE.exists():
        print(f"❌ 配置文件不存在: {CONFIG_FILE}")
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    """主函数"""
    print("=" * 60)
    print("📚 HX-NovelSync - 小说自动同步")
    print("   数据源: 番茄小说 (fanqienovel.com)")
    print("   引擎: Tomato-Novel-Downloader")
    print("=" * 60)

    # 加载配置
    config = load_config()
    novels = config.get("novels", [])
    enable_tts = config.get("enable_tts", False)

    if not novels:
        print("❌ 配置中没有定义任何小说")
        sys.exit(1)

    print(f"📋 共 {len(novels)} 本小说待处理")
    if enable_tts:
        print(f"🔊 TTS 有声书生成: 已启用")

    # 步骤1: 下载 Tomato-Novel-Downloader 二进制
    print(f"\n{'='*50}")
    print("🔧 准备下载工具...")
    print(f"{'='*50}")
    bin_path = download_tomato_binary()
    if not bin_path:
        print("❌ 无法获取 Tomato-Novel-Downloader，尝试使用备用方案...")
        # 如果下载二进制失败，可以尝试使用旧的 Python 方式（但这里先不实现）
        sys.exit(1)

    # 步骤2: 生成配置文件
    generate_config_yml(enable_tts=enable_tts)

    # 步骤3: 逐本处理
    state = load_state()
    results = []

    for novel in novels:
        try:
            result = process_novel(novel, state, bin_path, enable_tts)
            results.append(result)
        except Exception as e:
            print(f"  ❌ 《{novel['name']}》处理异常: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                "name": novel["name"], "author": novel["author"],
                "success": False, "reason": str(e),
            })

    save_state(state)

    # 统计结果
    success_list = [r for r in results if r.get("success")]
    fail_list = [r for r in results if not r.get("success")]

    print(f"\n{'='*60}")
    print(f"📊 处理完成: {len(success_list)}/{len(novels)} 本成功")
    for r in success_list:
        size_mb = r.get("file_size", 0) / 1024 / 1024 if r.get("file_size") else 0
        new_ch = r.get("new_chapters", 0)
        total_ch = r.get("total_chapters", 0)
        latest = r.get("latest_chapter", "")
        fail = r.get("fail_count", 0)
        print(f"  ✅ {r['name']} - {r['author']} ({size_mb:.1f}MB, {new_ch}新/{total_ch}总, {fail}失败)")
        if latest:
            print(f"     📖 最新: {latest}")
        if r.get("audio_count"):
            print(f"     🔊 音频: {r['audio_count']} 个文件")
    for r in fail_list:
        print(f"  ❌ {r['name']} - {r['author']} ({r.get('reason', 'unknown')})")
    print(f"{'='*60}")

    # GitHub Actions 输出
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"total_books={len(success_list)}\n")
            f.write(f"total_novels={len(novels)}\n")
            details_json = json.dumps(results, ensure_ascii=False)
            f.write(f"details={details_json}\n")
            if success_list:
                filenames = ",".join(r["filename"] for r in success_list if r.get("filename"))
                f.write(f"filenames={filenames}\n")

    if not success_list:
        print("❌ 没有成功下载任何小说")
        sys.exit(1)


if __name__ == "__main__":
    main()
