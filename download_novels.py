#!/usr/bin/env python3
"""
番茄小说下载器 - 直接爬取网页版
直接从 fanqienovel.com 网页版爬取小说内容，自带字体解密。
不依赖任何第三方 API 或外部项目。
"""

import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import parsel
import requests
from lxml import etree

# ===================== 常量 =====================

WORK_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = WORK_DIR / "novels.json"
OUTPUT_DIR = WORK_DIR / "output"
STATE_FILE = WORK_DIR / "state.json"

BASE_URL = "https://fanqienovel.com"

# 字体解密映射表（番茄小说字体加密 -> 真实字符）
FONT_DICT = {
    "58670": "0",
    "58413": "1",
    "58678": "2",
    "58371": "3",
    "58353": "4",
    "58480": "5",
    "58359": "6",
    "58449": "7",
    "58540": "8",
    "58692": "9",
    "58712": "a",
    "58542": "b",
    "58575": "c",
    "58626": "d",
    "58691": "e",
    "58561": "f",
    "58362": "g",
    "58619": "h",
    "58430": "i",
    "58531": "j",
    "58588": "k",
    "58440": "l",
    "58681": "m",
    "58631": "n",
    "58376": "o",
    "58429": "p",
    "58555": "q",
    "58498": "r",
    "58518": "s",
    "58453": "t",
    "58397": "u",
    "58356": "v",
    "58435": "w",
    "58514": "x",
    "58482": "y",
    "58529": "z",
    "58515": "A",
    "58688": "B",
    "58709": "C",
    "58344": "D",
    "58656": "E",
    "58381": "F",
    "58576": "G",
    "58516": "H",
    "58463": "I",
    "58649": "J",
    "58571": "K",
    "58558": "L",
    "58433": "M",
    "58517": "N",
    "58387": "O",
    "58687": "P",
    "58537": "Q",
    "58541": "R",
    "58458": "S",
    "58390": "T",
    "58466": "U",
    "58386": "V",
    "58697": "W",
    "58519": "X",
    "58511": "Y",
    "58634": "Z",
    "58611": "的",
    "58590": "一",
    "58398": "是",
    "58422": "了",
    "58657": "我",
    "58666": "不",
    "58562": "人",
    "58345": "在",
    "58510": "他",
    "58496": "有",
    "58654": "这",
    "58441": "个",
    "58493": "上",
    "58714": "们",
    "58618": "来",
    "58528": "到",
    "58620": "时",
    "58403": "大",
    "58461": "地",
    "58481": "为",
    "58700": "子",
    "58708": "中",
    "58503": "你",
    "58442": "说",
    "58639": "生",
    "58506": "国",
    "58663": "年",
    "58436": "着",
    "58563": "就",
    "58391": "那",
    "58357": "和",
    "58354": "要",
    "58695": "她",
    "58372": "出",
    "58696": "也",
    "58551": "得",
    "58445": "里",
    "58408": "后",
    "58599": "自",
    "58424": "以",
    "58394": "会",
    "58348": "家",
    "58426": "可",
    "58673": "下",
    "58417": "而",
    "58556": "过",
    "58603": "天",
    "58565": "去",
    "58604": "能",
    "58522": "对",
    "58632": "小",
    "58622": "多",
    "58350": "然",
    "58605": "于",
    "58617": "心",
    "58401": "学",
    "58637": "么",
    "58684": "之",
    "58382": "都",
    "58464": "好",
    "58487": "看",
    "58693": "起",
    "58608": "发",
    "58392": "当",
    "58474": "没",
    "58601": "成",
    "58355": "只",
    "58573": "如",
    "58499": "事",
    "58469": "把",
    "58361": "还",
    "58698": "用",
    "58489": "第",
    "58711": "样",
    "58457": "道",
    "58635": "想",
    "58492": "作",
    "58647": "种",
    "58623": "开",
    "58521": "美",
    "58609": "总",
    "58530": "从",
    "58665": "无",
    "58652": "情",
    "58676": "己",
    "58456": "面",
    "58581": "最",
    "58509": "女",
    "58488": "但",
    "58363": "现",
    "58685": "前",
    "58396": "些",
    "58523": "所",
    "58471": "同",
    "58485": "日",
    "58613": "手",
    "58533": "又",
    "58589": "行",
    "58527": "意",
    "58593": "动",
    "58699": "方",
    "58707": "期",
    "58414": "它",
    "58596": "头",
    "58570": "经",
    "58660": "长",
    "58364": "儿",
    "58526": "回",
    "58501": "位",
    "58638": "分",
    "58404": "爱",
    "58677": "老",
    "58535": "因",
    "58629": "很",
    "58577": "给",
    "58606": "名",
    "58497": "法",
    "58662": "间",
    "58479": "斯",
    "58532": "知",
    "58380": "世",
    "58385": "什",
    "58405": "两",
    "58644": "次",
    "58578": "使",
    "58505": "身",
    "58564": "者",
    "58412": "被",
    "58686": "高",
    "58624": "已",
    "58667": "亲",
    "58607": "其",
    "58616": "进",
    "58368": "此",
    "58427": "话",
    "58423": "常",
    "58633": "与",
    "58525": "活",
    "58543": "正",
    "58418": "感",
    "58597": "见",
    "58683": "明",
    "58507": "问",
    "58621": "力",
    "58703": "理",
    "58438": "尔",
    "58536": "点",
    "58384": "文",
    "58484": "几",
    "58539": "定",
    "58554": "本",
    "58421": "公",
    "58347": "特",
    "58569": "做",
    "58710": "外",
    "58574": "孩",
    "58375": "相",
    "58645": "西",
    "58592": "果",
    "58572": "走",
    "58388": "将",
    "58370": "月",
    "58399": "十",
    "58651": "实",
    "58546": "向",
    "58504": "声",
    "58419": "车",
    "58407": "全",
    "58672": "信",
    "58675": "重",
    "58538": "三",
    "58465": "机",
    "58374": "工",
    "58579": "物",
    "58402": "气",
    "58702": "每",
    "58553": "并",
    "58360": "别",
    "58389": "真",
    "58560": "打",
    "58690": "太",
    "58473": "新",
    "58512": "比",
    "58653": "才",
    "58704": "便",
    "58545": "夫",
    "58641": "再",
    "58475": "书",
    "58583": "部",
    "58472": "水",
    "58478": "像",
    "58664": "眼",
    "58586": "等",
    "58568": "体",
    "58674": "却",
    "58490": "加",
    "58476": "电",
    "58346": "主",
    "58630": "界",
    "58595": "门",
    "58502": "利",
    "58713": "海",
    "58587": "受",
    "58548": "听",
    "58351": "表",
    "58547": "德",
    "58443": "少",
    "58460": "克",
    "58636": "代",
    "58585": "员",
    "58625": "许",
    "58694": "稜",
    "58428": "先",
    "58640": "口",
    "58628": "由",
    "58612": "死",
    "58446": "安",
    "58468": "写",
    "58410": "性",
    "58508": "马",
    "58594": "光",
    "58483": "白",
    "58544": "或",
    "58495": "住",
    "58450": "难",
    "58643": "望",
    "58486": "教",
    "58406": "命",
    "58447": "花",
    "58669": "结",
    "58415": "乐",
    "58444": "色",
    "58549": "更",
    "58494": "拉",
    "58409": "东",
    "58658": "神",
    "58557": "记",
    "58602": "处",
    "58559": "让",
    "58610": "母",
    "58513": "父",
    "58500": "应",
    "58378": "直",
    "58680": "字",
    "58352": "场",
    "58383": "平",
    "58454": "报",
    "58671": "友",
    "58668": "关",
    "58452": "放",
    "58627": "至",
    "58400": "张",
    "58455": "认",
    "58416": "接",
    "58552": "告",
    "58614": "入",
    "58582": "笑",
    "58534": "内",
    "58701": "英",
    "58349": "军",
    "58491": "候",
    "58467": "民",
    "58365": "岁",
    "58598": "往",
    "58425": "何",
    "58462": "度",
    "58420": "山",
    "58661": "觉",
    "58615": "路",
    "58648": "带",
    "58470": "万",
    "58377": "男",
    "58520": "边",
    "58646": "风",
    "58600": "解",
    "58431": "叫",
    "58715": "任",
    "58524": "金",
    "58439": "快",
    "58566": "原",
    "58477": "吃",
    "58642": "妈",
    "58437": "变",
    "58411": "通",
    "58451": "师",
    "58395": "立",
    "58369": "象",
    "58706": "数",
    "58705": "四",
    "58379": "失",
    "58567": "满",
    "58373": "战",
    "58448": "远",
    "58659": "格",
    "58434": "士",
    "58679": "音",
    "58432": "轻",
    "58689": "目",
    "58591": "条",
    "58682": "呢",
}

# 请求头池
HEADERS_LIB = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    },
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
        "Gecko/20100101 Firefox/121.0"
    },
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    },
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
    },
]

# 全局 cookie
g_cookie = ""


# ===================== 工具函数 =====================


def get_random_headers() -> dict:
    """获取随机请求头（含 cookie）"""
    headers = dict(random.choice(HEADERS_LIB))
    headers["cookie"] = g_cookie
    return headers


def init_cookie(test_chapter_link: str = "") -> bool:
    """
    初始化一个有效的 cookie（novel_web_id）。
    如果提供了 test_chapter_link，会验证 cookie 能否获取到内容。
    否则只生成一个随机的 cookie。
    """
    global g_cookie
    # 直接生成一个随机的大数字作为 novel_web_id
    g_cookie = "novel_web_id=" + str(
        random.randint(6000000000000000000, 9000000000000000000)
    )

    if not test_chapter_link:
        return True

    # 验证 cookie 是否能获取到内容
    content = download_chapter_content(test_chapter_link)
    if content and len(content) > 50:
        return True

    # 如果验证失败，多尝试几次
    for _ in range(5):
        g_cookie = "novel_web_id=" + str(
            random.randint(6000000000000000000, 9000000000000000000)
        )
        time.sleep(random.uniform(0.3, 0.8))
        content = download_chapter_content(test_chapter_link)
        if content and len(content) > 50:
            return True

    return False


def decrypt_text(content: str) -> str:
    """使用字体映射表解密加密文本"""
    result = []
    for ch in content:
        mapped = FONT_DICT.get(str(ord(ch)))
        result.append(mapped if mapped else ch)
    return "".join(result)


def sanitize_filename(filename: str) -> str:
    """清理文件名中的非法字符"""
    illegal = ["<", ">", ":", '"', "/", "\\", "|", "?", "*"]
    replace = ["＜", "＞", "：", "＂", "／", "＼", "｜", "？", "＊"]
    for i, c in enumerate(illegal):
        filename = filename.replace(c, replace[i])
    return filename.strip()


# ===================== 核心功能 =====================


def search_book(keyword: str) -> list:
    """
    搜索书籍，返回搜索结果列表。
    每个结果包含 book_id, book_name, author, word_count 等。
    """
    url = (
        f"{BASE_URL}/api/author/search/search_book/v1?"
        f"filter=127,127,127,127&page_count=100&page_index=0"
        f"&query_type=0&query_word={keyword}"
    )
    try:
        resp = requests.get(url, headers=get_random_headers(), timeout=15)
        if resp.status_code != 200:
            print(f"  ⚠️ 搜索请求失败: HTTP {resp.status_code}")
            return []
        data = resp.json()
        books = data.get("data", {}).get("search_book_data_list", [])
        return books
    except Exception as e:
        print(f"  ⚠️ 搜索异常: {e}")
        return []


def get_book_info(book_id: str) -> dict:
    """
    获取书籍详细信息：书名、作者、章节列表等。
    返回 dict: {name, author, chapters: [{title, href}], word_count}
    """
    url = f"{BASE_URL}/page/{book_id}"
    try:
        resp = requests.get(url, headers=get_random_headers(), timeout=15)
        if resp.status_code != 200:
            print(f"  ⚠️ 获取书籍信息失败: HTTP {resp.status_code}")
            return {}
        ele = etree.HTML(resp.text)
    except Exception as e:
        print(f"  ⚠️ 获取书籍信息异常: {e}")
        return {}

    # 提取书名
    titles = ele.xpath("//h1/text()")
    if not titles:
        print(f"  ⚠️ 未找到书名，可能 book_id 无效")
        return {}

    book_name = titles[0].strip()

    # 提取作者
    authors = ele.xpath('//span[@class="author-name-text"]/text()')
    author = authors[0].strip() if authors else "未知作者"

    # 提取章节列表
    chapter_elements = ele.xpath('//div[@class="chapter"]/div/a')
    chapters = []
    for a in chapter_elements:
        title = a.text.strip() if a.text else f"第{len(chapters)+1}章"
        href = a.xpath("@href")[0] if a.xpath("@href") else ""
        if href:
            chapters.append({"title": title, "href": href})

    # 提取字数
    word_counts = ele.xpath(
        '//div[@class="info-count-word"]/span[@class="detail"]/text()'
    )
    word_count = word_counts[0] if word_counts else ""

    return {
        "name": book_name,
        "author": author,
        "chapters": chapters,
        "word_count": word_count,
    }


def download_chapter_content(chapter_href: str) -> str:
    """
    下载单章内容并解密。
    chapter_href: 例如 /reader/7404826399455855129
    返回解密后的纯文本。
    """
    url = BASE_URL + chapter_href
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=get_random_headers(), timeout=15)
            if resp.status_code != 200:
                time.sleep(1)
                continue
            selector = parsel.Selector(resp.text)
            # 尝试多种 CSS 选择器
            content_list = selector.css(".muye-reader-content-16 p::text").getall()
            if not content_list:
                content_list = selector.css(".muye-reader-content p::text").getall()
            if not content_list:
                # 尝试通过 xpath
                ele = etree.HTML(resp.text)
                content_list = ele.xpath(
                    '//div[contains(@class,"muye-reader-content")]//p/text()'
                )

            if content_list:
                return decrypt_text("\n".join(content_list))
            else:
                time.sleep(0.5)
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(1)
            else:
                print(f"    ⚠️ 章节下载失败: {chapter_href} - {e}")
    return ""


# ===================== 状态管理 =====================


def load_state() -> dict:
    """加载上次的下载状态（已下载的章节数）"""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state: dict):
    """保存下载状态"""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  ⚠️ 保存状态失败: {e}")


# ===================== 主处理逻辑 =====================


def find_book_id(name: str, author: str) -> str:
    """通过书名和作者搜索 book_id"""
    print(f"  🔍 搜索中: {name}")
    books = search_book(name)
    if not books:
        # 尝试用书名前几个字搜索
        short_name = name[: min(8, len(name))]
        if short_name != name:
            print(f"  🔍 缩短关键词重试: {short_name}")
            books = search_book(short_name)

    if not books:
        print(f"  ❌ 搜索无结果")
        return ""

    print(f"  📋 找到 {len(books)} 个结果")

    def clean(s):
        return (s or "").strip().replace(" ", "").replace("\u3000", "")

    target_name = clean(name)
    target_author = clean(author)

    # 精确匹配
    for book in books:
        bn = clean(decrypt_text(book.get("book_name", "")))
        ba = clean(decrypt_text(book.get("author", "")))
        bid = str(book.get("book_id", ""))
        if target_name in bn and target_author == ba:
            print(f"  ✅ 精确匹配: {bn} - {ba} (ID: {bid})")
            return bid

    # 模糊匹配
    for book in books:
        bn = clean(decrypt_text(book.get("book_name", "")))
        ba = clean(decrypt_text(book.get("author", "")))
        bid = str(book.get("book_id", ""))
        if len(target_name) >= 4 and target_name[:4] in bn and target_author in ba:
            print(f"  ✅ 模糊匹配: {bn} - {ba} (ID: {bid})")
            return bid

    # 打印结果帮助调试
    print(f"  ❌ 未找到匹配 (目标作者: {author})")
    for i, book in enumerate(books[:5]):
        bn = decrypt_text(book.get("book_name", "?"))
        ba = decrypt_text(book.get("author", "?"))
        bid = book.get("book_id", "?")
        print(f"    [{i+1}] {bn} - {ba} (ID: {bid})")

    return ""


def process_novel(novel: dict, state: dict) -> dict:
    """
    处理单本小说：
    1. 获取书籍信息和章节列表
    2. 与上次状态比较，找出新增章节
    3. 下载所有章节（全量生成 txt），但只下载新增的
    4. 生成 书名-作者.txt
    """
    name = novel["name"]
    author = novel["author"]
    book_id = novel.get("book_id", "")

    print(f"\n{'='*50}")
    print(f"📖 处理: 《{name}》 [作者: {author}]")
    print(f"{'='*50}")

    # 如果没有 book_id，搜索获取
    if not book_id:
        book_id = find_book_id(name, author)
        if not book_id:
            return {
                "name": name,
                "author": author,
                "success": False,
                "reason": "search_failed",
            }
        novel["book_id"] = book_id
    else:
        print(f"  📌 使用已配置的 book_id: {book_id}")

    # 获取书籍信息
    book_info = get_book_info(book_id)
    if not book_info:
        return {
            "name": name,
            "author": author,
            "book_id": book_id,
            "success": False,
            "reason": "book_info_failed",
        }

    real_name = book_info["name"]
    real_author = book_info["author"]
    chapters = book_info["chapters"]
    total_chapters = len(chapters)

    print(f"  📚 {real_name} - {real_author}")
    print(f"  📊 共 {total_chapters} 章 ({book_info.get('word_count', '?')})")

    if total_chapters == 0:
        return {
            "name": name,
            "author": author,
            "book_id": book_id,
            "success": False,
            "reason": "no_chapters",
        }

    # 检查状态：上次下载到了第几章
    state_key = book_id
    prev_count = state.get(state_key, {}).get("chapter_count", 0)
    prev_content_file = state.get(state_key, {}).get("content_file", "")

    if prev_count >= total_chapters:
        print(f"  ✅ 无新章节 (已有 {prev_count} 章)")
        # 即使没有新章节，也确保输出文件存在
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
            "book_id": book_id,
            "success": True,
            "filename": target_filename,
            "new_chapters": 0,
            "total_chapters": total_chapters,
        }

    new_count = total_chapters - prev_count
    print(f"  🆕 新增 {new_count} 章 (从第 {prev_count+1} 章开始)")

    # 初始化 cookie（用第一个新章节测试）
    first_new_chapter = (
        chapters[prev_count] if prev_count < total_chapters else chapters[-1]
    )
    print(f"  🔑 初始化 cookie...")
    if not init_cookie(first_new_chapter["href"]):
        print(f"  ⚠️ cookie 初始化失败，继续尝试...")
        init_cookie()  # 至少生成一个随机 cookie

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
            # 如果加载失败，需要从头下载
            prev_count = 0
            existing_content = ""
            print(f"  ⚠️ 加载已有内容失败，将从头下载")

    # 下载新章节（并行下载）
    chapters_to_download = chapters[prev_count:]
    # 预分配结果列表，保证章节顺序
    downloaded_content = [None] * len(chapters_to_download)
    fail_count = 0
    max_workers = min(8, len(chapters_to_download))  # 并行度，最多8线程

    def _download_one(idx_chapter):
        """下载单章的线程任务"""
        idx, chapter = idx_chapter
        chapter_num = prev_count + idx + 1
        title = chapter["title"]
        content = download_chapter_content(chapter["href"])
        success = bool(content and len(content) > 10)
        text = f"\n{title}\n\n{content}\n" if success else f"\n{title}\n\n[内容获取失败]\n"
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
                print(f"  � [{chapter_num}/{total_chapters}] {status} {title}")
                if not success:
                    fail_count += 1
            except Exception as e:
                idx = futures[future]
                chapter_num = prev_count + idx + 1
                title = chapters_to_download[idx]["title"]
                downloaded_content[idx] = f"\n{title}\n\n[内容获取失败]\n"
                fail_count += 1
                print(f"  📥 [{chapter_num}/{total_chapters}] ❌ {title} ({e})")

    # 过滤掉 None（理论上不会有）
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
        "book_id": book_id,
        "success": True,
        "filename": target_filename,
        "file_size": file_size,
        "new_chapters": new_count,
        "total_chapters": total_chapters,
        "fail_count": fail_count,
    }


def load_config() -> dict:
    """加载配置文件"""
    if not CONFIG_FILE.exists():
        print(f"❌ 配置文件不存在: {CONFIG_FILE}")
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    """主函数"""
    print("=" * 60)
    print("📚 HX-NovelSync - 番茄小说自动同步")
    print("   直接爬取网页版，自带字体解密")
    print("=" * 60)

    # 加载配置
    config = load_config()
    novels = config.get("novels", [])

    if not novels:
        print("❌ 配置中没有定义任何小说")
        sys.exit(1)

    print(f"📋 共 {len(novels)} 本小说待处理")

    # 初始化 cookie
    init_cookie()

    # 加载上次状态
    state = load_state()

    # 逐本处理
    results = []
    ids_updated = False

    for novel in novels:
        try:
            result = process_novel(novel, state)
            results.append(result)
            if result.get("book_id") and not novel.get("_had_id"):
                ids_updated = True
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

    # 如果搜索到了新的 book_id，更新配置文件
    if ids_updated:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            print("  💾 已更新 novels.json（保存了 book_id）")
        except Exception as e:
            print(f"  ⚠️ 保存配置失败: {e}")

    # 统计结果
    success_list = [r for r in results if r.get("success")]
    fail_list = [r for r in results if not r.get("success")]

    print(f"\n{'='*60}")
    print(f"📊 处理完成: {len(success_list)}/{len(novels)} 本成功")
    for r in success_list:
        size_mb = r.get("file_size", 0) / 1024 / 1024
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
