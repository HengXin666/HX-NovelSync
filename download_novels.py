#!/usr/bin/env python3
"""
番茄小说下载器 - 通过小说名+作者名自动搜索并下载
基于番茄小说API（参考 POf-L/Fanqie-novel-Downloader 项目）
用于 GitHub Actions 自动化工作流
"""

import os
import re
import json
import sys
import time
import asyncio
import aiohttp
from typing import Optional, Dict, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# ===================== 配置加载 =====================

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(WORK_DIR, "novels.json")
OUTPUT_DIR = os.path.join(WORK_DIR, "output")

# 默认UA
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def load_config() -> dict:
    """加载配置文件"""
    if not os.path.exists(CONFIG_FILE):
        print(f"❌ 配置文件不存在: {CONFIG_FILE}")
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# ===================== API 客户端 =====================


class FanqieAPI:
    """番茄小说 API 客户端"""

    def __init__(self, config: dict):
        self.api_sources: List[str] = config.get("api_sources", [])
        self.endpoints: dict = config.get("api_endpoints", {})
        self.download_config: dict = config.get("download", {})
        self.timeout: int = self.download_config.get("request_timeout", 60)
        self.max_retries: int = self.download_config.get("max_retries", 3)
        self.max_workers: int = self.download_config.get("max_workers", 10)
        self.chapter_delay: float = self.download_config.get("chapter_delay", 0.1)
        self.headers = {"User-Agent": USER_AGENT}
        self._current_source_index = 0
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def base_url(self) -> str:
        """当前使用的API节点"""
        if not self.api_sources:
            return ""
        return self.api_sources[self._current_source_index % len(self.api_sources)]

    def _next_source(self):
        """切换到下一个API节点"""
        self._current_source_index += 1
        if self._current_source_index >= len(self.api_sources):
            self._current_source_index = 0
        print(f"  🔄 切换API节点: {self.base_url}")

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建异步会话"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            connector = aiohttp.TCPConnector(limit=50, ssl=False)
            self._session = aiohttp.ClientSession(
                timeout=timeout, connector=connector, headers=self.headers
            )
        return self._session

    async def close(self):
        """关闭会话"""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(
        self, endpoint: str, params: dict, base_url: str = None
    ) -> Optional[dict]:
        """发送API请求，支持自动重试和节点切换"""
        session = await self._get_session()
        tried_sources = set()

        for attempt in range(self.max_retries * len(self.api_sources)):
            url_base = base_url or self.base_url
            if url_base in tried_sources and len(tried_sources) >= len(
                self.api_sources
            ):
                break

            url = f"{url_base.rstrip('/')}{endpoint}"
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("code") == 200:
                            return data
                        else:
                            print(
                                f"  ⚠️ API返回错误码 {data.get('code')}: {data.get('message', '')}"
                            )
                    else:
                        print(f"  ⚠️ HTTP {resp.status} from {url_base}")
            except asyncio.TimeoutError:
                print(f"  ⏱️ 请求超时: {url_base}")
            except Exception as e:
                print(f"  ⚠️ 请求失败 ({url_base}): {type(e).__name__}: {e}")

            tried_sources.add(url_base)
            self._next_source()
            base_url = None  # 使用下一个节点

        return None

    async def search_book(self, keyword: str) -> Optional[List[dict]]:
        """搜索小说，返回搜索结果列表"""
        endpoint = self.endpoints.get("search", "/api/search")
        params = {"key": keyword, "tab_type": "3", "offset": "0"}
        data = await self._request(endpoint, params)
        if data and "data" in data:
            # 兼容不同的返回格式
            result_data = data["data"]
            if isinstance(result_data, dict):
                return result_data.get(
                    "data", result_data.get("search_book_data_list", [])
                )
            elif isinstance(result_data, list):
                return result_data
        return None

    async def get_book_detail(self, book_id: str) -> Optional[dict]:
        """获取书籍详情"""
        endpoint = self.endpoints.get("detail", "/api/detail")
        params = {"book_id": book_id}
        data = await self._request(endpoint, params)
        if data and "data" in data:
            level1 = data["data"]
            if isinstance(level1, dict) and "data" in level1:
                return level1["data"]
            return level1
        return None

    async def get_chapter_list(self, book_id: str) -> Optional[List[dict]]:
        """获取章节列表"""
        endpoint = self.endpoints.get("book", "/api/book")
        params = {"book_id": book_id}
        data = await self._request(endpoint, params)
        if data and "data" in data:
            level1 = data["data"]
            if isinstance(level1, dict) and "data" in level1:
                return level1["data"]
            return level1
        return None

    async def get_chapter_content(self, item_id: str) -> Optional[dict]:
        """获取单个章节内容，优先使用 /api/chapter 接口"""
        # 先尝试 /api/chapter
        chapter_endpoint = self.endpoints.get("chapter", "/api/chapter")
        params = {"item_id": item_id}
        data = await self._request(chapter_endpoint, params)
        if data and "data" in data:
            return data["data"]

        # 回退到 /api/content
        content_endpoint = self.endpoints.get("content", "/api/content")
        params = {"tab": "小说", "item_id": item_id}
        data = await self._request(content_endpoint, params)
        if data and "data" in data:
            return data["data"]
        return None

    async def get_full_content(self, book_id: str) -> Optional[str]:
        """尝试使用整本下载接口获取完整内容"""
        raw_full_endpoint = self.endpoints.get("raw_full", "/api/raw_full")

        # 遍历所有节点尝试整本下载
        for i, source in enumerate(self.api_sources):
            url = f"{source.rstrip('/')}{raw_full_endpoint}"
            params = {"item_id": book_id}
            try:
                session = await self._get_session()
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("code") == 200 and "data" in data:
                            result = data["data"]
                            # 可能是字符串（整本内容）或字典（章节映射）
                            if isinstance(result, str) and len(result) > 100:
                                print(f"  ✅ 整本下载成功 (节点: {source})")
                                return result
                            elif isinstance(result, dict):
                                # 批量模式：{item_id: content} 或 {data: {item_id: content}}
                                nested = result.get("data", result)
                                if isinstance(nested, dict) and nested:
                                    # 合并所有章节内容
                                    contents = list(nested.values())
                                    if contents and all(
                                        isinstance(c, str) for c in contents
                                    ):
                                        full_text = "\n\n".join(contents)
                                        if len(full_text) > 100:
                                            print(
                                                f"  ✅ 整本下载成功（批量模式, 节点: {source}）"
                                            )
                                            return full_text
            except asyncio.TimeoutError:
                print(f"  ⏱️ 整本下载超时: {source}")
            except Exception as e:
                print(f"  ⚠️ 整本下载失败 ({source}): {e}")

        return None


# ===================== 核心逻辑 =====================


def match_author(
    search_results: List[dict], target_name: str, target_author: str
) -> Optional[dict]:
    """从搜索结果中匹配作者，返回匹配的书籍信息"""
    if not search_results:
        return None

    for book in search_results:
        # 兼容多种字段名
        book_name = book.get("book_name", book.get("title", book.get("name", "")))
        author = book.get("author", book.get("author_name", ""))
        book_id = book.get("book_id", book.get("id", ""))

        # 清理空白字符
        book_name = book_name.strip() if book_name else ""
        author = author.strip() if author else ""

        # 精确匹配作者名（忽略空格差异）
        name_match = target_name.replace(" ", "") in book_name.replace(" ", "")
        author_match = target_author.replace(" ", "") == author.replace(" ", "")

        if name_match and author_match:
            return {"book_id": str(book_id), "book_name": book_name, "author": author}

    # 如果精确匹配失败，尝试模糊匹配
    for book in search_results:
        book_name = book.get("book_name", book.get("title", book.get("name", "")))
        author = book.get("author", book.get("author_name", ""))
        book_id = book.get("book_id", book.get("id", ""))

        book_name = book_name.strip() if book_name else ""
        author = author.strip() if author else ""

        # 模糊匹配：书名包含关键词 + 作者包含关键词
        if target_author in author and (
            target_name[:4] in book_name or book_name in target_name
        ):
            return {"book_id": str(book_id), "book_name": book_name, "author": author}

    return None


def extract_chapter_text(chapter_data: dict) -> Tuple[str, str]:
    """从章节数据中提取标题和内容"""
    title = chapter_data.get("title", chapter_data.get("chapter_title", ""))
    content = chapter_data.get("content", chapter_data.get("novel_data", ""))

    # 如果内容是HTML格式，提取纯文本
    if content and "<" in content:
        # 移除HTML标签
        content = re.sub(r"<br\s*/?>", "\n", content)
        content = re.sub(r"<p>", "", content)
        content = re.sub(r"</p>", "\n", content)
        content = re.sub(r"<[^>]+>", "", content)

    # 清理空白
    if content:
        content = content.strip()
        # 合并过多空行
        content = re.sub(r"\n{3,}", "\n\n", content)

    return title, content


async def download_novel_chapters(
    api: FanqieAPI, book_id: str, chapters: List[dict]
) -> List[Tuple[str, str]]:
    """逐章下载小说内容"""
    results = []
    total = len(chapters)
    semaphore = asyncio.Semaphore(api.max_workers)

    async def download_one(idx: int, chapter: dict) -> Tuple[int, str, str]:
        item_id = str(chapter.get("item_id", chapter.get("id", "")))
        title = chapter.get("title", chapter.get("chapter_title", f"第{idx+1}章"))
        async with semaphore:
            for retry in range(api.max_retries):
                try:
                    data = await api.get_chapter_content(item_id)
                    if data:
                        t, c = extract_chapter_text(data)
                        return idx, t or title, c
                except Exception as e:
                    if retry < api.max_retries - 1:
                        await asyncio.sleep(1)
            return idx, title, ""

    # 并发下载
    tasks = [download_one(i, ch) for i, ch in enumerate(chapters)]

    completed = 0
    chapter_results = [None] * total
    for coro in asyncio.as_completed(tasks):
        idx, title, content = await coro
        chapter_results[idx] = (title, content)
        completed += 1
        if completed % 50 == 0 or completed == total:
            print(f"  📥 下载进度: {completed}/{total} ({completed*100//total}%)")

    return [r for r in chapter_results if r is not None]


def assemble_novel_text(
    chapters: List[Tuple[str, str]], book_name: str = "", author: str = ""
) -> str:
    """将章节列表组装成完整小说文本"""
    lines = []

    # 添加标题信息
    if book_name:
        lines.append(f"《{book_name}》")
    if author:
        lines.append(f"作者：{author}")
    if book_name or author:
        lines.append("")
        lines.append("=" * 40)
        lines.append("")

    for title, content in chapters:
        if title:
            lines.append(title)
            lines.append("")
        if content:
            lines.append(content)
        lines.append("")

    return "\n".join(lines)


def count_chapters_in_text(text: str) -> int:
    """统计文本中的章节数"""
    # 匹配常见章节格式
    patterns = [
        r"^第[一二三四五六七八九十百千万\d]+章",
        r"^第\d+章",
        r"^Chapter\s+\d+",
    ]
    count = 0
    for line in text.split("\n"):
        line = line.strip()
        for pat in patterns:
            if re.match(pat, line):
                count += 1
                break
    return count


async def process_novel(api: FanqieAPI, novel: dict) -> Optional[dict]:
    """处理单本小说：搜索 -> 匹配 -> 下载 -> 保存"""
    name = novel["name"]
    author = novel["author"]
    filename = f"{name}-{author}.txt"
    output_path = os.path.join(OUTPUT_DIR, filename)

    print(f"\n{'='*50}")
    print(f"📖 处理: 《{name}》 [作者: {author}]")
    print(f"{'='*50}")

    # 1. 搜索小说
    print(f"  🔍 搜索中: {name}")
    results = await api.search_book(name)
    if not results:
        print(f"  ❌ 搜索无结果")
        return None

    print(f"  📋 找到 {len(results)} 个结果")

    # 2. 匹配作者
    matched = match_author(results, name, author)
    if not matched:
        print(f"  ❌ 未找到匹配的书籍 (作者: {author})")
        # 打印搜索到的结果帮助调试
        for i, book in enumerate(results[:5]):
            bn = book.get("book_name", book.get("title", "?"))
            ba = book.get("author", book.get("author_name", "?"))
            bid = book.get("book_id", book.get("id", "?"))
            print(f"    [{i+1}] {bn} - {ba} (ID: {bid})")
        return None

    book_id = matched["book_id"]
    print(
        f"  ✅ 匹配成功: {matched['book_name']} - {matched['author']} (ID: {book_id})"
    )

    # 3. 先尝试整本下载
    print(f"  📦 尝试整本下载...")
    full_text = await api.get_full_content(book_id)

    if full_text and len(full_text) > 500:
        # 整本下载成功
        chapter_count = count_chapters_in_text(full_text)
        print(f"  📊 内容长度: {len(full_text)} 字符, 约 {chapter_count} 章")

        # 保存文件
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            # 添加头部信息
            f.write(f"《{matched['book_name']}》\n")
            f.write(f"作者：{matched['author']}\n\n")
            f.write("=" * 40 + "\n\n")
            f.write(full_text)

        file_size = os.path.getsize(output_path)
        print(f"  💾 已保存: {filename} ({file_size/1024/1024:.1f}MB)")
        return {
            "name": matched["book_name"],
            "author": matched["author"],
            "book_id": book_id,
            "chapters": chapter_count,
            "filename": filename,
            "file_size": file_size,
            "method": "full_download",
        }

    # 4. 整本下载失败，逐章下载
    print(f"  📑 获取章节列表...")
    chapters = await api.get_chapter_list(book_id)
    if not chapters:
        print(f"  ❌ 获取章节列表失败")
        return None

    print(f"  📋 共 {len(chapters)} 章，开始逐章下载...")
    chapter_contents = await download_novel_chapters(api, book_id, chapters)

    if not chapter_contents:
        print(f"  ❌ 下载章节内容失败")
        return None

    # 过滤空章节
    valid_chapters = [(t, c) for t, c in chapter_contents if c]
    print(f"  ✅ 成功下载 {len(valid_chapters)}/{len(chapters)} 章")

    # 组装文本
    novel_text = assemble_novel_text(
        valid_chapters, matched["book_name"], matched["author"]
    )

    # 保存文件
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(novel_text)

    file_size = os.path.getsize(output_path)
    print(f"  💾 已保存: {filename} ({file_size/1024/1024:.1f}MB)")

    return {
        "name": matched["book_name"],
        "author": matched["author"],
        "book_id": book_id,
        "chapters": len(valid_chapters),
        "filename": filename,
        "file_size": file_size,
        "method": "chapter_by_chapter",
    }


async def main():
    """主函数"""
    print("=" * 60)
    print("📚 HX-NovelSync - 番茄小说自动同步")
    print("=" * 60)

    # 加载配置
    config = load_config()
    novels = config.get("novels", [])

    if not novels:
        print("❌ 配置中没有定义任何小说")
        sys.exit(1)

    print(f"📋 共 {len(novels)} 本小说待处理")

    # 初始化API
    api = FanqieAPI(config)

    # 逐本处理
    results = []
    for novel in novels:
        try:
            result = await process_novel(api, novel)
            if result:
                results.append(result)
            else:
                print(f"  ⚠️ 《{novel['name']}》处理失败")
        except Exception as e:
            print(f"  ❌ 《{novel['name']}》处理异常: {e}")
            import traceback

            traceback.print_exc()

    await api.close()

    # 输出总结
    print(f"\n{'='*60}")
    print(f"📊 处理完成: {len(results)}/{len(novels)} 本成功")
    for r in results:
        print(
            f"  ✅ {r['name']} - {r['author']} ({r['chapters']}章, {r['file_size']/1024/1024:.1f}MB)"
        )
    print(f"{'='*60}")

    # 输出到 GitHub Actions 环境变量
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output and results:
        with open(github_output, "a", encoding="utf-8") as f:
            # 输出汇总信息
            f.write(f"total_books={len(results)}\n")
            f.write(f"total_novels={len(novels)}\n")

            # 输出详细信息（JSON格式）
            details_json = json.dumps(results, ensure_ascii=False)
            f.write(f"details={details_json}\n")

            # 输出文件名列表
            filenames = ",".join(r["filename"] for r in results)
            f.write(f"filenames={filenames}\n")

            # 为兼容性，输出第一本的信息
            first = results[0]
            f.write(f"title={first['name']}\n")
            f.write(f"author={first['author']}\n")
            f.write(f"total_chapters={first['chapters']}\n")

    if not results:
        print("❌ 没有成功下载任何小说")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
