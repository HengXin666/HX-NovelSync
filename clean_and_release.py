#!/usr/bin/env python3
"""
下载小说、清理描述信息、提取元数据的脚本。
用于GitHub Actions自动化发布。
"""
import os
import re
import json
import zipfile
import shutil
import urllib.request
import ssl
import sys

# 配置
URL = "https://down7.ixdzs8.com/567128.zip"
WORK_DIR = os.path.dirname(os.path.abspath(__file__))
ZIP_PATH = os.path.join(WORK_DIR, "567128.zip")
EXTRACT_DIR = os.path.join(WORK_DIR, "extracted")
OUTPUT_DIR = os.path.join(WORK_DIR, "output")
META_FILE = os.path.join(OUTPUT_DIR, "meta.json")


def download_file(url, save_path):
    """下载文件"""
    print(f"正在下载: {url}")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/131.0.0.0 Safari/537.36"
    })
    with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(save_path, "wb") as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = downloaded / total * 100
                    print(f"\r下载进度: {pct:.1f}% ({downloaded}/{total} bytes)",
                          end="", flush=True)
    print("\n下载完成!")


def extract_zip(zip_path, extract_dir):
    """解压zip文件"""
    print(f"正在解压: {zip_path}")
    os.makedirs(extract_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)
    print("解压完成!")


def find_txt_files(directory):
    """递归查找所有txt文件"""
    txt_files = []
    for root, dirs, files in os.walk(directory):
        for f in files:
            if f.lower().endswith(".txt"):
                txt_files.append(os.path.join(root, f))
    return txt_files


def detect_and_read(file_path):
    """检测编码并读取文件内容"""
    with open(file_path, "rb") as f:
        raw = f.read()

    encodings = ["utf-8", "gbk", "gb2312", "gb18030", "big5"]
    for enc in encodings:
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue

    print(f"  [警告] 无法检测编码: {file_path}")
    return None, None


def extract_metadata(text):
    """从原始文本中提取元信息"""
    meta = {
        "title": "",
        "author": "",
        "status": "",
        "chapter_info": "",
        "total_chapters": 0,
    }

    # 提取书名和作者: 『全民巨鱼求生：我能听到巨鱼心声/作者:失控云』
    title_match = re.search(r"『(.+?)/作者:(.+?)』", text[:500])
    if title_match:
        meta["title"] = title_match.group(1).strip()
        meta["author"] = title_match.group(2).strip()

    # 提取状态: 『状态:更新到:第1422章 第19次寻宝试炼开始』
    status_match = re.search(r"『状态:(.+?)』", text[:500])
    if status_match:
        meta["status"] = status_match.group(1).strip()
        meta["chapter_info"] = status_match.group(0)

    # 统计章节数量（匹配"第xxx章"的模式）
    chapters = re.findall(r"^第(\d+)章", text, re.MULTILINE)
    if chapters:
        meta["total_chapters"] = max(int(c) for c in chapters)

    return meta


def clean_text(text):
    """清理文本，去除头尾描述信息"""
    # === 去除头部 ===
    # 头部格式：从开头到 "------章节内容开始-------" 之后
    header_pattern = r"^.*?------章节内容开始-------\s*"
    text = re.sub(header_pattern, "", text, count=1, flags=re.DOTALL)

    # === 去除尾部 ===
    # 尾部格式：『还在连载中...』\n更多电子书请访问...
    tail_patterns = [
        r"\n\s*『还在连载中\.{0,3}』.*$",
        r"\n\s*更多电子书请访问.*$",
    ]
    for pat in tail_patterns:
        text = re.sub(pat, "", text, flags=re.DOTALL)

    # 去除末尾多余空行
    text = text.rstrip() + "\n"

    return text


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. 下载
    download_file(URL, ZIP_PATH)

    # 2. 解压
    extract_zip(ZIP_PATH, EXTRACT_DIR)

    # 3. 查找txt文件
    txt_files = find_txt_files(EXTRACT_DIR)
    if not txt_files:
        print("未找到任何txt文件!")
        sys.exit(1)

    print(f"\n找到 {len(txt_files)} 个txt文件")

    # 4. 处理每个txt文件
    all_meta = {}
    for tf in txt_files:
        basename = os.path.basename(tf)
        print(f"\n处理: {basename}")

        # 读取
        text, enc = detect_and_read(tf)
        if text is None:
            continue
        print(f"  编码: {enc}")

        # 提取元信息（在清理之前）
        meta = extract_metadata(text)
        print(f"  书名: {meta['title']}")
        print(f"  作者: {meta['author']}")
        print(f"  状态: {meta['status']}")
        print(f"  章节数: {meta['total_chapters']}")

        # 清理
        cleaned = clean_text(text)

        # 保存清理后的文件
        output_path = os.path.join(OUTPUT_DIR, basename)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(cleaned)
        print(f"  已保存: {output_path}")

        all_meta[basename] = meta

    # 5. 保存元信息
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(all_meta, f, ensure_ascii=False, indent=2)
    print(f"\n元信息已保存: {META_FILE}")

    # 6. 输出到GitHub Actions环境变量
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        # 取第一个文件的元信息
        first_meta = list(all_meta.values())[0] if all_meta else {}
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"title={first_meta.get('title', '未知')}\n")
            f.write(f"author={first_meta.get('author', '未知')}\n")
            f.write(f"status={first_meta.get('status', '未知')}\n")
            f.write(f"total_chapters={first_meta.get('total_chapters', 0)}\n")
            # 文件名列表
            filenames = ",".join(all_meta.keys())
            f.write(f"filenames={filenames}\n")

    # 7. 清理临时文件
    if os.path.exists(ZIP_PATH):
        os.remove(ZIP_PATH)
    if os.path.exists(EXTRACT_DIR):
        shutil.rmtree(EXTRACT_DIR)
    print("\n已清理临时文件。处理完成!")


if __name__ == "__main__":
    main()
