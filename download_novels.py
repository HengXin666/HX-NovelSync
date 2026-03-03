#!/usr/bin/env python3
"""
小说下载器 - 基于番茄小说API
从番茄小说获取小说内容，支持断点续传、GitHub Actions 自动化。
参考:
  - https://github.com/zhongbai2333/Tomato-Novel-Downloader (Rust版)
  - https://github.com/POf-L/Fanqie-novel-Downloader (Python版)
"""

import json
import os
import re
import sys
import time
import random
import html
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===================== 常量 =====================

WORK_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = WORK_DIR / "novels.json"
OUTPUT_DIR = WORK_DIR / "output"
STATE_FILE = WORK_DIR / "state.json"

# 番茄小说 Web 端
FANQIE_WEB_BASE = "https://fanqienovel.com"

# 第三方代理 API 节点 (POf-L 风格接口)
# 这些节点提供已解密的小说内容
# 端点格式: /api/detail, /api/book, /api/content, /api/chapter
THIRD_PARTY_NODES = [
    "https://bk.yydjtc.cn",
    "https://qkfqapi.vv9v.cn",
    "https://fq.shusan.cn",
]

# ===================== 请求会话 =====================

session = requests.Session()

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]

session.headers.update(
    {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
    }
)


# ===================== 工具函数 =====================


def sanitize_filename(filename):
    """清理文件名中的非法字符（含中文标点，确保GitHub Release兼容）"""
    # 替换常见非法字符和中文标点
    result = re.sub(r'[\\/*?:"<>|：；""''【】]', '_', filename)
    # 合并连续下划线
    result = re.sub(r'_+', '_', result)
    # 去除首尾下划线和空格
    result = result.strip('_ ')
    return result if result else "unknown"


def rotate_ua():
    """随机切换 User-Agent"""
    session.headers["User-Agent"] = random.choice(USER_AGENTS)


# ===================== 番茄小说官方 Web API =====================


def fanqie_get_book_info(book_id):
    """
    从番茄小说网页获取书籍信息
    返回: (book_name, author, chapter_count, latest_chapter_title)
    """
    url = f"{FANQIE_WEB_BASE}/page/{book_id}"
    try:
        rotate_ua()
        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            return None, None, None, None
    except Exception as e:
        print(f"    ⚠️ 访问番茄小说页面失败: {e}")
        return None, None, None, None

    html_text = resp.text

    # 解析 __INITIAL_STATE__
    pattern = r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;'
    match = re.search(pattern, html_text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1).strip())
            page = data.get("page", {})
            book_name = page.get("bookName", "")
            author = page.get("authorName", "")
            chapter_count = page.get("chapterTotal", 0)
            latest_chapter = page.get("lastChapterTitle", "")
            if book_name or author:
                return book_name, author, chapter_count, latest_chapter
        except json.JSONDecodeError:
            pass

    # 正则兜底
    book_name = _regex_field(html_text, "bookName")
    author = _regex_field(html_text, "authorName") or _regex_field(html_text, "author")
    chapter_count = _regex_int_field(html_text, "chapterTotal")
    latest_chapter = _regex_field(html_text, "lastChapterTitle")

    return book_name, author, chapter_count, latest_chapter


def fanqie_get_chapter_list(book_id):
    """
    从番茄小说官方API获取章节列表
    API: /api/reader/directory/detail?bookId={book_id}
    返回: [(item_id, title), ...]
    """
    # 预热：先访问页面获取Cookie
    try:
        rotate_ua()
        session.get(f"{FANQIE_WEB_BASE}/page/{book_id}", timeout=10)
    except Exception:
        pass
    time.sleep(random.uniform(0.3, 0.8))

    url = f"{FANQIE_WEB_BASE}/api/reader/directory/detail?bookId={book_id}"
    json_headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": f"{FANQIE_WEB_BASE}/page/{book_id}",
    }

    try:
        rotate_ua()
        resp = session.get(url, timeout=15, headers=json_headers)
        if resp.status_code != 200:
            print(f"    ⚠️ 章节列表API返回 HTTP {resp.status_code}")
            return []
        data = resp.json()
    except Exception as e:
        print(f"    ⚠️ 获取章节列表失败: {e}")
        return []

    root = data.get("data", {})
    if not isinstance(root, dict):
        return []

    result = []

    # 解析 chapterListWithVolume（番茄小说实际返回的格式）
    chapter_list_with_volume = root.get("chapterListWithVolume")
    if isinstance(chapter_list_with_volume, list):
        for volume in chapter_list_with_volume:
            if isinstance(volume, list):
                for ch in volume:
                    if isinstance(ch, dict):
                        item_id = ch.get("itemId") or ch.get("item_id")
                        title = ch.get("title", f"第{len(result)+1}章")
                        if item_id:
                            result.append((str(item_id), title))
        if result:
            return result

    # 兜底：使用 allItemIds
    all_item_ids = root.get("allItemIds", [])
    if isinstance(all_item_ids, list):
        for i, item_id in enumerate(all_item_ids):
            if isinstance(item_id, str) and item_id.strip():
                result.append((item_id.strip(), f"第{i+1}章"))

    return result


def _regex_field(text, field):
    """正则提取JSON字段的字符串值"""
    pattern = rf'"{re.escape(field)}"\s*:\s*"(.*?)"'
    match = re.search(pattern, text)
    if match:
        raw = match.group(1)
        try:
            return json.loads(f'"{raw}"')
        except json.JSONDecodeError:
            return raw
    return None


def _regex_int_field(text, field):
    """正则提取JSON字段的整数值"""
    pattern = rf'"{re.escape(field)}"\s*:\s*(\d+)'
    match = re.search(pattern, text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return None


# ===================== 第三方代理 API (POf-L 风格) =====================


class ThirdPartyAPI:
    """第三方代理API管理器，支持多节点自动切换"""

    def __init__(self, nodes=None):
        self.nodes = list(nodes or THIRD_PARTY_NODES)
        self._working_node = None
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://fanqienovel.com/",
            "Content-Type": "application/json",
        })

    def _request(self, endpoint, params, timeout=15):
        """
        带节点自动切换的请求
        优先使用上次成功的节点
        """
        nodes_to_try = []
        if self._working_node:
            nodes_to_try.append(self._working_node)
        nodes_to_try.extend(n for n in self.nodes if n != self._working_node)

        for node in nodes_to_try:
            url = f"{node.rstrip('/')}{endpoint}"
            try:
                resp = self._session.get(url, params=params, timeout=timeout, verify=False)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == 200:
                        self._working_node = node
                        return data
                elif resp.status_code == 500:
                    # 服务端错误，可能是临时的
                    continue
            except Exception:
                continue

        return None

    def probe_nodes(self):
        """探测可用节点"""
        print("  🔍 探测第三方API节点...")
        available = []
        for node in self.nodes:
            try:
                resp = self._session.get(
                    f"{node.rstrip('/')}/api/detail",
                    params={"book_id": "7404826300126333977"},
                    timeout=8,
                    verify=False,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == 200:
                        available.append(node)
                        print(f"    ✅ {node}")
                    else:
                        print(f"    ❌ {node} (code={data.get('code')})")
                else:
                    print(f"    ❌ {node} (HTTP {resp.status_code})")
            except Exception as e:
                print(f"    ❌ {node} ({type(e).__name__})")

        self.nodes = available
        if available:
            self._working_node = available[0]
        return len(available) > 0

    def get_book_detail(self, book_id):
        """获取书籍详情"""
        data = self._request("/api/detail", {"book_id": book_id})
        if not data:
            return None
        detail = data.get("data", {})
        if isinstance(detail, dict) and "data" in detail:
            return detail["data"]
        return detail

    def get_chapter_list(self, book_id):
        """获取章节列表（通过 /api/book）"""
        data = self._request("/api/book", {"book_id": book_id})
        if not data:
            return None
        level1 = data.get("data", {})
        if isinstance(level1, dict) and "data" in level1:
            return level1["data"]
        return level1

    def get_chapter_content(self, item_id):
        """获取单章内容"""
        # 优先 /api/chapter
        data = self._request("/api/chapter", {"item_id": item_id}, timeout=10)
        if data and data.get("data"):
            return data["data"]

        # 回退到 /api/content
        data = self._request("/api/content", {"tab": "小说", "item_id": item_id}, timeout=15)
        if data and data.get("data"):
            return data["data"]

        return None

    def get_full_book(self, book_id):
        """
        尝试整本下载（批量模式）
        返回: {item_id: content_text, ...} 或 None
        """
        nodes_to_try = []
        if self._working_node:
            nodes_to_try.append(self._working_node)
        nodes_to_try.extend(n for n in self.nodes if n != self._working_node)

        for node in nodes_to_try:
            # 尝试 "批量" 和 "下载" 两种 tab
            for tab in ["批量", "下载"]:
                url = f"{node.rstrip('/')}/api/content"
                params = {"tab": tab, "book_id": book_id}
                try:
                    resp = self._session.get(
                        url, params=params, timeout=120, verify=False, stream=True
                    )
                    if resp.status_code != 200:
                        continue

                    raw = resp.content
                    if len(raw) < 1000:
                        continue

                    data = json.loads(raw.decode("utf-8", errors="ignore"))
                    if data.get("code") != 200:
                        continue

                    payload = data.get("data", {})
                    # 批量模式返回 {data: {item_id: content, ...}}
                    if isinstance(payload, dict):
                        nested = payload.get("data")
                        if isinstance(nested, dict) and len(nested) > 0:
                            # 验证是 {item_id: content} 格式
                            sample_keys = list(nested.keys())[:5]
                            if all(str(k).isdigit() for k in sample_keys):
                                result = {}
                                for k, v in nested.items():
                                    if isinstance(v, str):
                                        result[str(k)] = v
                                    elif isinstance(v, dict):
                                        result[str(k)] = v.get("content", "") or v.get("text", "")
                                if result:
                                    self._working_node = node
                                    return result
                except Exception:
                    continue

        return None

    @property
    def available(self):
        """是否有可用节点"""
        return bool(self.nodes)


# ===================== 内容清洗 =====================


def clean_content(raw):
    """
    将 HTML/XHTML 内容清洗为纯文本
    """
    if not raw:
        return ""

    # 将 <br>, </p>, </div> 等视为换行
    text = re.sub(r'(?is)<br\s*/?>|</p\s*>|</div\s*>|</section\s*>|</h[1-6]\s*>', '\n', raw)
    # 将 <p> 开标签视为换行
    text = re.sub(r'(?is)<p\b[^>]*>', '\n', text)
    # 移除其余所有标签
    text = re.sub(r'<[^>]+>', '', text)
    # 统一换行符
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # 解码 HTML 实体
    text = html.unescape(text)

    # 按段落整理，添加缩进
    paragraphs = []
    for line in text.split('\n'):
        trimmed = line.strip()
        if trimmed:
            paragraphs.append(f"　　{trimmed}")

    return '\n'.join(paragraphs)


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


def process_novel(novel, state, third_party_api):
    """
    处理单本小说的完整流程
    """
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

    # ==================== 1. 获取书籍信息 ====================
    print("  🔍 获取书籍信息...")
    real_name = name  # 优先使用用户配置的名称
    real_author = author

    # 先尝试第三方API
    if third_party_api.available:
        detail = third_party_api.get_book_detail(book_id)
        if detail and isinstance(detail, dict):
            api_author = detail.get("author", "")
            if api_author:
                real_author = api_author
            api_name = detail.get("book_name", "")
            if api_name and api_name != name:
                print(f"  📝 API书名: {api_name}")

    # 从番茄网页获取补充信息
    web_name, web_author, web_chapter_count, web_latest = fanqie_get_book_info(book_id)
    if web_author and not real_author:
        real_author = web_author

    print(f"  📚 {real_name} - {real_author}")
    if web_chapter_count:
        print(f"  📊 页面显示共 {web_chapter_count} 章")

    # ==================== 2. 获取章节列表 ====================
    print("  📋 获取章节列表...")
    chapters = fanqie_get_chapter_list(book_id)
    total_chapters = len(chapters)

    if total_chapters == 0:
        print("  ❌ 未获取到章节列表")
        return {"name": real_name, "author": real_author, "success": False, "reason": "no_chapters"}

    print(f"  📊 共获取 {total_chapters} 章")

    latest_chapter_title = chapters[-1][1] if chapters else (web_latest or "")
    print(f"  📖 最新章节: {latest_chapter_title}")

    # ==================== 3. 检查增量更新 ====================
    state_key = str(book_id)
    prev_state = state.get(state_key, {})
    prev_count = prev_state.get("chapter_count", 0)
    prev_content_file = prev_state.get("content_file", "")

    if prev_count >= total_chapters:
        print(f"  ✅ 无新章节 (已有 {prev_count} 章)")
        target_filename = f"{sanitize_filename(real_name)}-{sanitize_filename(real_author)}.txt"
        target_path = OUTPUT_DIR / target_filename
        if prev_content_file and Path(prev_content_file).exists():
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            import shutil
            shutil.copy2(prev_content_file, target_path)
        return {
            "name": real_name, "author": real_author, "success": True,
            "filename": target_filename, "new_chapters": 0,
            "total_chapters": total_chapters, "latest_chapter": latest_chapter_title,
        }

    new_count = total_chapters - prev_count
    print(f"  🆕 新增 {new_count} 章 (从第 {prev_count+1} 章开始)")

    # ==================== 4. 下载内容 ====================
    target_filename = f"{sanitize_filename(real_name)}-{sanitize_filename(real_author)}.txt"
    target_path = OUTPUT_DIR / target_filename
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 加载已有内容（增量更新）
    existing_content = ""
    if prev_count > 0:
        content_loaded = False
        # 优先尝试 prev_content_file
        if prev_content_file and Path(prev_content_file).exists():
            try:
                with open(prev_content_file, "r", encoding="utf-8") as f:
                    existing_content = f.read()
                if existing_content.strip():
                    content_loaded = True
                    print(f"  📄 加载已有内容 ({prev_count} 章)")
            except Exception:
                pass
        # 如果 prev_content_file 不可用，尝试从 target_path 加载
        if not content_loaded and target_path.exists():
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    existing_content = f.read()
                if existing_content.strip():
                    content_loaded = True
                    print(f"  📄 从输出文件加载已有内容 ({prev_count} 章)")
            except Exception:
                pass
        # 如果仍然加载失败，从头下载
        if not content_loaded:
            prev_count = 0
            existing_content = ""
            print("  ⚠️ 已有内容文件不存在或无法加载，将从头下载全部章节")

    chapters_to_download = chapters[prev_count:]
    downloaded_content = [None] * len(chapters_to_download)
    fail_count = 0

    # ---- 策略1: 尝试第三方API整本下载（批量模式） ----
    full_book_data = None
    if third_party_api.available and prev_count == 0:
        print("  🚀 尝试极速下载模式（整本批量）...")
        full_book_data = third_party_api.get_full_book(book_id)
        if full_book_data:
            matched = 0
            for i, (item_id, title) in enumerate(chapters_to_download):
                raw = full_book_data.get(item_id, "")
                if raw and len(raw.strip()) > 20:
                    content = clean_content(raw)
                    downloaded_content[i] = f"\n{title}\n\n{content}\n"
                    matched += 1
            print(f"  📥 极速模式: 匹配到 {matched}/{len(chapters_to_download)} 章")
            if matched >= len(chapters_to_download) * 0.95:
                # 大多数章节成功，标记剩余为失败
                for i in range(len(chapters_to_download)):
                    if downloaded_content[i] is None:
                        downloaded_content[i] = f"\n{chapters_to_download[i][1]}\n\n[内容获取失败]\n"
                        fail_count += 1
                # 跳过后续下载
                full_book_data = "DONE"
            else:
                full_book_data = None
                downloaded_content = [None] * len(chapters_to_download)
                print("  ⚠️ 极速模式匹配率不足，切换到逐章下载")

    # ---- 策略2: 第三方API逐章下载 ----
    if full_book_data != "DONE" and third_party_api.available:
        print("  📥 使用第三方API逐章下载...")
        chapters_remaining = [(i, ch) for i, ch in enumerate(chapters_to_download) if downloaded_content[i] is None]

        for idx, (i, (item_id, title)) in enumerate(chapters_remaining):
            chapter_num = prev_count + i + 1
            try:
                ch_data = third_party_api.get_chapter_content(item_id)
                if ch_data and isinstance(ch_data, dict):
                    raw = ch_data.get("content", "")
                    api_title = ch_data.get("title", "") or ch_data.get("origin_chapter_title", "")
                    display_title = api_title if api_title else title

                    if raw and len(raw.strip()) > 20:
                        content = clean_content(raw)
                        downloaded_content[i] = f"\n{display_title}\n\n{content}\n"
                        if (idx + 1) % 50 == 0 or idx == 0:
                            print(f"  📥 [{chapter_num}/{total_chapters}] ✅ {display_title}")
                        continue
            except Exception:
                pass

            # 当前章节未获取到
            if (idx + 1) % 50 == 0:
                print(f"  📥 [{chapter_num}/{total_chapters}] ❌ {title}")

            # 适当延迟，避免限频
            if (idx + 1) % 20 == 0:
                time.sleep(random.uniform(0.2, 0.5))

    # ---- 策略3: 直接从番茄小说网页抓取章节内容（兜底，有字体混淆） ----
    chapters_still_missing = [(i, ch) for i, ch in enumerate(chapters_to_download) if downloaded_content[i] is None]
    if chapters_still_missing:
        print(f"  🌐 还有 {len(chapters_still_missing)} 章未获取，尝试从番茄网页直接抓取...")
        for idx, (i, (item_id, title)) in enumerate(chapters_still_missing):
            chapter_num = prev_count + i + 1
            try:
                rotate_ua()
                resp = session.get(f"{FANQIE_WEB_BASE}/reader/{item_id}", timeout=15)
                if resp.status_code == 200:
                    # 解析 __INITIAL_STATE__
                    pattern = r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;'
                    match = re.search(pattern, resp.text, re.DOTALL)
                    if match:
                        page_data = json.loads(match.group(1).strip())
                        reader = page_data.get("reader", {})
                        chapter_data = reader.get("chapterData", {})
                        raw = chapter_data.get("content", "")
                        page_title = chapter_data.get("title", "") or chapter_data.get("chapterTitle", "")
                        display_title = page_title if page_title else title

                        if raw and len(raw.strip()) > 20:
                            content = clean_content(raw)
                            downloaded_content[i] = f"\n{display_title}\n\n{content}\n"
                            if (idx + 1) % 50 == 0 or idx == 0:
                                print(f"  📥 [{chapter_num}/{total_chapters}] ✅ {display_title} (网页)")
                            # 延迟，避免被封
                            time.sleep(random.uniform(0.3, 0.8))
                            continue
            except Exception:
                pass

            # 最终标记为失败
            downloaded_content[i] = f"\n{title}\n\n[内容获取失败]\n"
            fail_count += 1
            if (idx + 1) % 50 == 0:
                print(f"  📥 [{chapter_num}/{total_chapters}] ❌ {title}")

            if (idx + 1) % 10 == 0:
                time.sleep(random.uniform(0.5, 1.0))

    # ==================== 5. 合并并保存 ====================
    # 过滤掉 None（不应存在，但以防万一）
    for i in range(len(downloaded_content)):
        if downloaded_content[i] is None:
            downloaded_content[i] = f"\n{chapters_to_download[i][1]}\n\n[内容获取失败]\n"
            fail_count += 1

    new_content = "".join(downloaded_content)
    if existing_content:
        full_content = existing_content + new_content
    else:
        full_content = f"《{real_name}》\n作者：{real_author}\n\n{'='*40}\n" + new_content

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
        "latest_chapter": latest_chapter_title,
        "content_file": str(target_path),
        "last_update": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    return {
        "name": real_name, "author": real_author, "success": True,
        "filename": target_filename, "file_size": file_size,
        "new_chapters": new_count, "total_chapters": total_chapters,
        "fail_count": fail_count, "latest_chapter": latest_chapter_title,
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
    print("   数据源: 番茄小说 (fanqienovel.com)")
    print("=" * 60)

    config = load_config()
    novels = config.get("novels", [])

    if not novels:
        print("❌ 配置中没有定义任何小说")
        sys.exit(1)

    print(f"📋 共 {len(novels)} 本小说待处理")

    # 初始化第三方API
    third_party_api = ThirdPartyAPI()
    third_party_api.probe_nodes()
    if not third_party_api.available:
        print("  ⚠️ 所有第三方API节点不可用，将使用番茄小说网页直接抓取（可能有字体混淆）")

    state = load_state()
    results = []

    for novel in novels:
        try:
            result = process_novel(novel, state, third_party_api)
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
                filenames = ",".join(r["filename"] for r in success_list)
                f.write(f"filenames={filenames}\n")

    if not success_list:
        print("❌ 没有成功下载任何小说")
        sys.exit(1)


if __name__ == "__main__":
    main()
