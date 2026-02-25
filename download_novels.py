#!/usr/bin/env python3
"""
小说下载器 - 基于 xbiqugu.la（笔趣阁）数据源
从笔趣阁爬取小说内容，内容完整，更新及时。
支持断点续传、多线程并行下载、GitHub Actions 自动化。
"""

import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from lxml import etree

# ===================== 常量 =====================

WORK_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = WORK_DIR / "novels.json"
OUTPUT_DIR = WORK_DIR / "output"
STATE_FILE = WORK_DIR / "state.json"

BASE_URL = "http://www.xbiqugu.la"

# ===================== 请求会话 =====================

session = requests.Session()

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
]

session.headers.update(
    {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }
)


# ===================== 工具函数 =====================


def sanitize_filename(filename):
    """清理文件名中的非法字符"""
    return re.sub(r'[\\/*?:"<>|]', "_", filename).strip()


def safe_request(url, retries=3, timeout=15):
    """带重试的安全请求"""
    for attempt in range(retries):
        try:
            session.headers["User-Agent"] = random.choice(USER_AGENTS)
            resp = session.get(url, timeout=timeout)
            if resp.status_code == 200:
                resp.encoding = resp.apparent_encoding
                return resp
            else:
                print(f"    ⚠️ HTTP {resp.status_code}: {url}")
        except requests.RequestException as e:
            if attempt < retries - 1:
                time.sleep(random.uniform(0.5, 1.5))
            else:
                print(f"    ⚠️ 请求失败: {url} - {e}")
    return None


def clean_content(text):
    """清洗章节内容，去除广告和多余空白"""
    # 去除常见广告文字
    ad_patterns = [
        r"最新网址：\S+\s*",
        r"www\.xbiqugu?\.\w+\s*",
        r"笔趣阁\S*\s*",
        r"手机版阅读网址：\S*\s*",
    ]
    for pattern in ad_patterns:
        text = re.sub(pattern, "", text)

    # 规范化空白
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 按段落整理
    paragraphs = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(paragraphs)


# ===================== 核心功能 =====================


def get_chapter_list(book_path):
    """
    获取完整的章节列表。
    book_path: 例如 /145/145857/
    返回 (book_name, author, chapters_list)
    chapters_list: [{title, href}, ...]
    """
    url = BASE_URL + book_path
    resp = safe_request(url)
    if not resp:
        return "", "", []

    tree = etree.HTML(resp.text)

    # 获取书名
    book_name = ""
    name_el = tree.xpath('//div[@id="info"]/h1')
    if name_el:
        book_name = name_el[0].xpath("string()").strip()

    # 获取作者
    author = ""
    author_el = tree.xpath('//div[@id="info"]/p[1]')
    if author_el:
        author_text = author_el[0].xpath("string()").strip()
        m = re.search(r"作\s*者[：:]\s*(.+)", author_text)
        if m:
            author = m.group(1).strip()

    # 获取章节列表 — 在 <div id="list"> 中
    chapters = []
    chapter_links = tree.xpath('//div[@id="list"]//dd/a[@href]')
    for link in chapter_links:
        title = link.xpath("string()").strip()
        href = link.get("href", "")
        if title and href:
            chapters.append(
                {
                    "title": title,
                    "href": href,
                }
            )

    return book_name, author, chapters


def download_chapter_content(chapter_href):
    """
    下载单章内容。
    chapter_href: 例如 /145/145857/53060022.html
    返回清洗后的纯文本内容。
    """
    url = BASE_URL + chapter_href
    # 随机短延迟，避免请求过于密集
    time.sleep(random.uniform(0.05, 0.2))

    resp = safe_request(url)
    if not resp:
        return ""

    try:
        tree = etree.HTML(resp.text)
        content_div = tree.xpath('//div[@id="content"]')
        if content_div:
            text = content_div[0].xpath("string()").strip()
            if text:
                return clean_content(text)
    except Exception as e:
        print(f"    ⚠️ 解析内容失败: {chapter_href} - {e}")

    return ""


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


# ===================== 主处理逻辑 =====================


def process_novel(novel, state):
    """
    处理单本小说：
    1. 获取章节列表
    2. 与上次状态比较，找出新增章节
    3. 下载新章节（并行）
    4. 追加到已有文件
    """
    name = novel["name"]
    author = novel["author"]
    book_path = novel.get("book_path", "")

    print(f"\n{'='*50}")
    print(f"📖 处理: 《{name}》 [作者: {author}]")
    print(f"{'='*50}")

    if not book_path:
        print(f"  ❌ 未配置 book_path")
        return {
            "name": name,
            "author": author,
            "success": False,
            "reason": "no_book_path",
        }

    print(f"  📌 book_path: {book_path}")

    # 获取章节列表
    real_name, real_author, chapters = get_chapter_list(book_path)
    if not real_name:
        real_name = name
    if not real_author:
        real_author = author

    total_chapters = len(chapters)

    if total_chapters == 0:
        print(f"  ❌ 未获取到章节列表")
        return {
            "name": name,
            "author": author,
            "success": False,
            "reason": "no_chapters",
        }

    print(f"  📚 {real_name} - {real_author}")
    print(f"  📊 共 {total_chapters} 章")

    # 检查状态：上次下载到了第几章
    state_key = book_path
    prev_count = state.get(state_key, {}).get("chapter_count", 0)
    prev_content_file = state.get(state_key, {}).get("content_file", "")

    if prev_count >= total_chapters:
        print(f"  ✅ 无新章节 (已有 {prev_count} 章)")
        target_filename = (
            f"{sanitize_filename(real_name)}-{sanitize_filename(real_author)}.txt"
        )
        target_path = OUTPUT_DIR / target_filename
        if prev_content_file and Path(prev_content_file).exists():
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            import shutil

            shutil.copy2(prev_content_file, target_path)
        return {
            "name": real_name,
            "author": real_author,
            "success": True,
            "filename": target_filename,
            "new_chapters": 0,
            "total_chapters": total_chapters,
        }

    new_count = total_chapters - prev_count
    print(f"  🆕 新增 {new_count} 章 (从第 {prev_count+1} 章开始)")

    # 准备输出文件
    target_filename = (
        f"{sanitize_filename(real_name)}-{sanitize_filename(real_author)}.txt"
    )
    target_path = OUTPUT_DIR / target_filename
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 如果有已下载的内容，先加载
    existing_content = ""
    if prev_count > 0 and prev_content_file and Path(prev_content_file).exists():
        try:
            with open(prev_content_file, "r", encoding="utf-8") as f:
                existing_content = f.read()
            print(f"  📄 加载已有内容 ({prev_count} 章)")
        except Exception:
            prev_count = 0
            existing_content = ""
            print(f"  ⚠️ 加载已有内容失败，将从头下载")

    # 下载新章节（并行下载）
    chapters_to_download = chapters[prev_count:]
    downloaded_content = [None] * len(chapters_to_download)
    fail_count = 0
    max_workers = min(8, len(chapters_to_download))

    def _download_one(idx_chapter):
        """下载单章的线程任务"""
        idx, chapter = idx_chapter
        chapter_num = prev_count + idx + 1
        title = chapter["title"]
        content = download_chapter_content(chapter["href"])
        success = bool(content and len(content) > 50)
        text = (
            f"\n{title}\n\n{content}\n" if success else f"\n{title}\n\n[内容获取失败]\n"
        )
        return idx, chapter_num, title, text, success

    print(f"  🚀 并行下载 (线程数: {max_workers})")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_download_one, (idx, ch)): idx
            for idx, ch in enumerate(chapters_to_download)
        }
        for future in as_completed(futures):
            try:
                idx, chapter_num, title, text, success = future.result()
                downloaded_content[idx] = text
                status = "✅" if success else "❌"
                print(f"  📥 [{chapter_num}/{total_chapters}] {status} {title}")
                if not success:
                    fail_count += 1
            except Exception as e:
                idx = futures[future]
                chapter_num = prev_count + idx + 1
                title = chapters_to_download[idx]["title"]
                downloaded_content[idx] = f"\n{title}\n\n[内容获取失败]\n"
                fail_count += 1
                print(f"  📥 [{chapter_num}/{total_chapters}] ❌ {title} ({e})")

    # 过滤掉 None
    downloaded_content = [c for c in downloaded_content if c is not None]

    # 合并内容
    new_content = "".join(downloaded_content)
    full_content = (
        existing_content + new_content
        if existing_content
        else (f"《{real_name}》\n作者：{real_author}\n\n{'='*40}\n" + new_content)
    )

    # 保存到输出目录
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(full_content)

    file_size = target_path.stat().st_size
    print(f"  💾 已保存: {target_filename} ({file_size/1024/1024:.1f}MB)")
    print(f"  📊 下载 {len(chapters_to_download)} 章, 失败 {fail_count} 章")

    # 更新状态
    state[state_key] = {
        "name": real_name,
        "author": real_author,
        "chapter_count": total_chapters,
        "content_file": str(target_path),
        "last_update": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    return {
        "name": real_name,
        "author": real_author,
        "success": True,
        "filename": target_filename,
        "file_size": file_size,
        "new_chapters": new_count,
        "total_chapters": total_chapters,
        "fail_count": fail_count,
    }


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
    print(f"   数据源: xbiqugu.la（笔趣阁）")
    print("=" * 60)

    # 加载配置
    config = load_config()
    novels = config.get("novels", [])

    if not novels:
        print("❌ 配置中没有定义任何小说")
        sys.exit(1)

    print(f"📋 共 {len(novels)} 本小说待处理")

    # 加载上次状态
    state = load_state()

    # 逐本处理
    results = []

    for novel in novels:
        try:
            result = process_novel(novel, state)
            results.append(result)
        except Exception as e:
            print(f"  ❌ 《{novel['name']}》处理异常: {e}")
            import traceback

            traceback.print_exc()
            results.append(
                {
                    "name": novel["name"],
                    "author": novel["author"],
                    "success": False,
                    "reason": str(e),
                }
            )

    # 保存状态
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
        print(
            f"  ✅ {r['name']} - {r['author']} ({size_mb:.1f}MB, {new_ch}新/{total_ch}总)"
        )
    for r in fail_list:
        print(f"  ❌ {r['name']} - {r['author']} ({r.get('reason', 'unknown')})")
    print(f"{'='*60}")

    # 输出到 GitHub Actions
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"total_books={len(success_list)}\n")
            f.write(f"total_novels={len(novels)}\n")
            details_json = json.dumps(results, ensure_ascii=False)
            f.write(f"details={details_json}\n")
            if success_list:
                filenames = ",".join(r["filename"] for r in success_list)
                f.write(f"filenames={filenames}\n")

    if not success_list:
        print("❌ 没有成功下载任何小说")
        sys.exit(1)


if __name__ == "__main__":
    main()
