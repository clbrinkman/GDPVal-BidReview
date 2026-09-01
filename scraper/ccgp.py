"""中国政府采购网(ccgp.gov.cn) 招标公告爬虫
三级流程: 搜索列表 -> 详情页 -> 附件下载
产物: data/raw/{tdr_id}/ 附件 + detail.txt, 元数据入 data/platform.db
"""
import argparse
import datetime as dt
import os
import re
import sqlite3
import sys
import time
from urllib.parse import urljoin

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "raw")
DB_PATH = os.path.join(ROOT, "data", "platform.db")

SEARCH_URL = "http://search.ccgp.gov.cn/bxsearch"  # 搜索接口有频控, 弃用
BASE = "http://www.ccgp.gov.cn"
CHANNELS = {
    "df-gkzb": "/cggg/dfgg/gkzb/",   # 地方公告-公开招标
    "zy-gkzb": "/cggg/zygg/gkzb/",   # 中央公告-公开招标
    "df-jzxcs": "/cggg/dfgg/jzxcs/", # 地方公告-竞争性磋商
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
}
ATTACH_EXT = (".pdf", ".doc", ".docx", ".zip", ".rar", ".ofd")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS tender (
        tdr_id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        url TEXT UNIQUE NOT NULL,
        title TEXT,
        publish_date TEXT,
        region TEXT,
        bid_type TEXT,
        status TEXT DEFAULT 'raw',
        fetched_at TEXT
    );
    CREATE TABLE IF NOT EXISTS attachment (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tdr_id TEXT NOT NULL REFERENCES tender(tdr_id),
        filename TEXT,
        url TEXT,
        path TEXT,
        size INTEGER,
        UNIQUE(tdr_id, url)
    );
    """)
    return conn


def next_tdr_id(conn):
    year = dt.date.today().year
    prefix = f"TDR-CCGP-{year}-"
    row = conn.execute(
        "SELECT tdr_id FROM tender WHERE tdr_id LIKE ? ORDER BY tdr_id DESC LIMIT 1",
        (prefix + "%",)).fetchone()
    seq = int(row[0].rsplit("-", 1)[1]) + 1 if row else 1
    return prefix + f"{seq:05d}"


def get(url, delay, binary=False, retries=2):
    for attempt in range(retries + 1):
        try:
            time.sleep(delay)
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            if binary:
                return resp.content
            try:
                return resp.content.decode("utf-8")
            except UnicodeDecodeError:
                return resp.content.decode("gb18030", "replace")
        except requests.RequestException:
            if attempt == retries:
                raise
            time.sleep(delay * 3)


def search_list(channel, page_index, delay):
    """频道列表页: index.htm / index_{n}.htm"""
    ch = CHANNELS[channel]
    page = "index.htm" if page_index == 1 else f"index_{page_index - 1}.htm"
    html = get(BASE + ch + page, delay)
    soup = BeautifulSoup(html, "lxml")
    items = []
    for li in soup.select("ul.c_list_bid li"):
        a = li.find("a", href=True)
        if not a:
            continue
        ems = li.find_all("em")
        items.append({
            "url": urljoin(BASE + ch, a["href"]),
            "title": a.get("title") or a.get_text(strip=True),
            "publish_date": (ems[0].get_text(strip=True)[:10] if len(ems) > 0 else ""),
            "region": ems[1].get_text(strip=True) if len(ems) > 1 else "",
            "purchaser": ems[2].get_text(strip=True) if len(ems) > 2 else "",
        })
    return items


def parse_detail(html):
    soup = BeautifulSoup(html, "lxml")
    content = soup.select_one("div.vF_detail_content") or soup.select_one("div.detail") or soup.body
    text = content.get_text("\n", strip=True) if content else ""
    attach = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().split("?")[0].endswith(ATTACH_EXT):
            attach.append({"url": href, "name": a.get_text(strip=True) or os.path.basename(href)})
    return text, attach


def crawl(channel, pages, max_details, delay):
    conn = init_db()
    os.makedirs(RAW_DIR, exist_ok=True)
    seen, new_items = set(), 0
    stats = {"listed": 0, "skipped_dup": 0, "detail": 0, "with_attach": 0, "files": 0}

    for page in range(1, pages + 1):
        try:
            items = search_list(channel, page, delay)
        except Exception as e:
            print(f"[warn] 列表第{page}页失败: {e}")
            continue
        print(f"[list] 第{page}页 {len(items)} 条")
        stats["listed"] += len(items)

        for it in items:
            if new_items >= max_details:
                break
            if it["url"] in seen or conn.execute(
                    "SELECT 1 FROM tender WHERE url=?", (it["url"],)).fetchone():
                stats["skipped_dup"] += 1
                continue
            seen.add(it["url"])

            try:
                html = get(it["url"], delay)
                text, attach = parse_detail(html)
            except Exception as e:
                print(f"[warn] 详情失败 {it['url']}: {e}")
                continue

            tdr_id = next_tdr_id(conn)
            tdir = os.path.join(RAW_DIR, tdr_id)
            os.makedirs(tdir, exist_ok=True)
            with open(os.path.join(tdir, "detail.txt"), "w", encoding="utf-8") as f:
                f.write(text)

            conn.execute(
                "INSERT INTO tender VALUES (?,?,?,?,?,?,?,?,?)",
                (tdr_id, f"ccgp-{channel}", it["url"], it["title"], it["publish_date"],
                 it["region"], "公开招标", "raw",
                 dt.datetime.now().isoformat(timespec="seconds")))

            for att in attach:
                try:
                    blob = get(att["url"], delay, binary=True)
                except Exception as e:
                    print(f"[warn] 附件失败 {att['url']}: {e}")
                    continue
                fname = re.sub(r'[\\/:*?"<>|]', "_", att["name"])
                if not os.path.splitext(fname)[1]:
                    fname += os.path.splitext(att["url"].split("?")[0])[1]
                fpath = os.path.join(tdir, fname)
                with open(fpath, "wb") as f:
                    f.write(blob)
                conn.execute(
                    "INSERT OR IGNORE INTO attachment(tdr_id,filename,url,path,size) VALUES (?,?,?,?,?)",
                    (tdr_id, fname, att["url"], fpath, len(blob)))
                stats["files"] += 1

            conn.commit()
            stats["detail"] += 1
            if attach:
                stats["with_attach"] += 1
            new_items += 1
            print(f"[detail] {tdr_id} 附件{len(attach)}个 | {it['title'][:40]}")

        if new_items >= max_details:
            break

    print(f"\n[done] 列表{stats['listed']} 详情{stats['detail']} "
          f"带附件{stats['with_attach']} 文件{stats['files']} 去重跳过{stats['skipped_dup']}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="df-gkzb", choices=list(CHANNELS), help="频道")
    ap.add_argument("--pages", type=int, default=2, help="列表页数(每页20条)")
    ap.add_argument("--max-details", type=int, default=20, help="最多抓多少个详情")
    ap.add_argument("--delay", type=float, default=1.5, help="请求间隔秒")
    args = ap.parse_args()
    crawl(args.channel, args.pages, args.max_details, args.delay)
