"""yatslist — Yat's List 命令行客户端。

零第三方依赖，只用 Python 标准库。从 yatslist.com 拉取四张公开清单的
JSON 数据（深圳活动 / 黑客松 / 深圳外国人活动 / X Space 纪要），在终端里
按日期浏览、按截止日排序、跨清单搜索。

数据结构（2026-11 实测）：
- events.json / szexpat events.json：顶层 {updated_at, events: [...]}，
  条目 start/end 为带时区的 ISO 时间字符串（如 2026-11-08T19:00:00+08:00，
  可缺秒、可为 null）。
- hackathons.json：顶层 {updated_at, hackathons: [...]}，
  条目 deadline/start 为纯日期字符串（YYYY-MM-DD）。
- spaces.json：顶层 {updated_at, spaces: [...]}，存档型清单，
  条目 date 为纯日期字符串（YYYY-MM-DD），按日期倒序展示。
输出时间一律取数据源原文，不做时区换算。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta, timezone

__version__ = "0.1.2"

# 数据源地址（模块级常量，改版时只改这里）
EVENTS_URL = "https://yatslist.com/events.json"
HACKATHONS_URL = "https://yatslist.com/hackathons.json"
EXPAT_URL = "https://yatslist.com/szexpat/events.json"
SPACES_URL = "https://yatslist.com/spaces.json"

TIMEOUT = 10  # 秒
USER_AGENT = f"yatslist-cli/{__version__}"

# 三份数据均为 +08:00（Asia/Shanghai，无夏令时），用固定偏移做日期判断
DATA_TZ = timezone(timedelta(hours=8))

WEEKDAYS_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

SOURCE_EVENTS = "深圳活动"
SOURCE_HACKATHONS = "黑客松"
SOURCE_EXPAT = "外国人活动"
SOURCE_SPACES = "Space 纪要"


class FetchError(Exception):
    """拉取或解析远程 JSON 失败。"""


# ---------------------------------------------------------------- 拉取与解析

def fetch_json(url: str):
    """拉取并解析 JSON；失败抛 FetchError（带中文友好信息）。"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise FetchError(f"服务器返回 {e.code}（{url}）") from e
    except urllib.error.URLError as e:
        raise FetchError(f"网络连接失败：{e.reason}（{url}）") from e
    except TimeoutError as e:
        raise FetchError(f"请求超时（{TIMEOUT} 秒，{url}）") from e
    except OSError as e:
        raise FetchError(f"网络错误：{e}（{url}）") from e
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise FetchError(f"数据格式异常，无法解析（{url}）") from e


def parse_datetime(value):
    """解析 ISO 时间字符串 → aware datetime；纯日期按当天 00:00 处理。

    无法解析或为空返回 None。
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    try:
        if "T" not in text and " " not in text:
            d = date.fromisoformat(text)
            return datetime.combine(d, time.min, tzinfo=DATA_TZ)
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=DATA_TZ)
    return dt


def parse_date(value):
    """解析日期：优先取 ISO 时间的日期部分，也接受纯日期字符串。"""
    dt = parse_datetime(value)
    return dt.date() if dt else None


def raw_time(value):
    """从 ISO 字符串原文截取 HH:MM（不做任何时区换算）；无时间部分返回 None。"""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    for sep in ("T", " "):
        if sep in text:
            tail = text.split(sep, 1)[1]
            if len(tail) >= 5 and tail[2] == ":":
                return tail[:5]
            return None
    return None


def now_in_data_tz() -> datetime:
    return datetime.now(DATA_TZ)


# ---------------------------------------------------------------- 通用筛选

def filter_upcoming_events(items, days: int, today: date):
    """筛出窗口 [today, today+days) 内仍未结束的活动。

    规则：开始日期 < 窗口末日，且结束日期（无 end 时用开始日期）>= today。
    返回 [(展示日期, 条目)]，展示日期 = 开始日期；已开始未结束的（进行中）
    展示日期记为 today。无 start 的条目跳过。
    """
    window_end = today + timedelta(days=days)
    picked = []
    for item in items:
        start_d = parse_date(item.get("start"))
        if start_d is None:
            continue
        end_d = parse_date(item.get("end")) or start_d
        if end_d < today or start_d >= window_end:
            continue
        display_d = start_d if start_d >= today else today
        picked.append((display_d, item))
    picked.sort(key=lambda pair: (pair[0], raw_time(pair[1].get("start")) or "", pair[1].get("title") or ""))
    return picked


def group_by_date(picked):
    """[(日期, 条目)] → [(日期, [条目, ...])]，保持已有顺序。"""
    groups = []
    for d, item in picked:
        if groups and groups[-1][0] == d:
            groups[-1][1].append(item)
        else:
            groups.append((d, [item]))
    return groups


def filter_hackathons(items, now: datetime, soon: bool = False, days=None):
    """筛出报名未截止的黑客松，按截止日升序。

    deadline 为纯日期，按当天 23:59:59（数据时区）仍可报名计。
    soon=True 时只保留 72 小时内截止的；days 不为 None 时只保留
    days 天内截止的。无 deadline 的条目跳过。
    """
    picked = []
    for item in items:
        dl = parse_date(item.get("deadline"))
        if dl is None:
            continue
        dl_end = datetime.combine(dl, time(23, 59, 59), tzinfo=DATA_TZ)
        if dl_end < now:
            continue
        if soon and dl_end > now + timedelta(hours=72):
            continue
        if days is not None and dl_end > now + timedelta(days=days):
            continue
        picked.append((dl, item))
    picked.sort(key=lambda pair: (pair[0], pair[1].get("title") or ""))
    return picked


# ---------------------------------------------------------------- 搜索

def _match(item, keyword, fields):
    kw = keyword.lower()
    for f in fields:
        v = item.get(f)
        if isinstance(v, str) and kw in v.lower():
            return True
        if isinstance(v, list) and any(isinstance(x, str) and kw in x.lower() for x in v):
            return True
    return False


EVENT_SEARCH_FIELDS = ["title", "title_en", "title_zh", "venue", "district", "summary", "summary_zh", "organizer"]
HACKATHON_SEARCH_FIELDS = ["title", "title_en", "city", "summary", "prize", "topics"]


def search_all(events, hackathons, expat_events, keyword, today: date, now: datetime):
    """三张清单一起搜（仅未结束/未截止条目），返回 [(来源, 排序日期, 条目)]。"""
    results = []
    live_events = {id(it) for _, it in filter_upcoming_events(events, 3660, today)}
    for item in events:
        if id(item) in live_events and _match(item, keyword, EVENT_SEARCH_FIELDS):
            results.append((SOURCE_EVENTS, parse_date(item.get("start")), item))
    live_expat = {id(it) for _, it in filter_upcoming_events(expat_events, 3660, today)}
    for item in expat_events:
        if id(item) in live_expat and _match(item, keyword, EVENT_SEARCH_FIELDS):
            results.append((SOURCE_EXPAT, parse_date(item.get("start")), item))
    for dl, item in filter_hackathons(hackathons, now):
        if _match(item, keyword, HACKATHON_SEARCH_FIELDS):
            results.append((SOURCE_HACKATHONS, dl, item))
    results.sort(key=lambda r: (r[1] or date.max, r[0], r[2].get("title") or ""))
    return results


# ---------------------------------------------------------------- 输出格式

def fmt_date_header(d: date) -> str:
    return f"{d.isoformat()} {WEEKDAYS_ZH[d.weekday()]}"


def fmt_event_line(item, today: date) -> str:
    t = raw_time(item.get("start")) or "全天"
    title = item.get("title") or "(无标题)"
    line = f"  {t}  {title}"
    venue = item.get("venue")
    if venue:
        line += f" @ {venue}"
    start_d = parse_date(item.get("start"))
    if start_d is not None and start_d < today:
        line += "（进行中）"
    return line


def fmt_expat_line(item, today: date) -> str:
    t = raw_time(item.get("start")) or "全天"
    title = item.get("title") or item.get("title_zh") or "(无标题)"
    line = f"  {t}  {title}"
    venue = item.get("venue") or item.get("area") or item.get("address")
    if venue:
        line += f" @ {venue}"
    start_d = parse_date(item.get("start"))
    if start_d is not None and start_d < today:
        line += "（进行中）"
    return line


def fmt_hackathon_line(item) -> str:
    title = item.get("title") or "(无标题)"
    line = f"  截止 {item.get('deadline')}  {title}"
    place = item.get("city")
    fmt = item.get("format")
    if place and fmt:
        line += f"（{place} · {fmt}）"
    elif place or fmt:
        line += f"（{place or fmt}）"
    return line


def sort_spaces(items):
    """Space 纪要按日期倒序（无日期的垫底），同日期保持原顺序。"""
    return sorted(items, key=lambda it: parse_date(it.get("date")) or date.min, reverse=True)


def fmt_space_line(item) -> str:
    title = item.get("title") or "(无标题)"
    line = f"  {item.get('date') or '----'}  {title}"
    series = item.get("series")
    if series:
        line += f"  [{series}"
        if item.get("episode"):
            line += f" 第{item['episode']}期"
        line += "]"
    return line


def print_event_groups(picked, today: date, line_fmt):
    for d, group in group_by_date(picked):
        print(fmt_date_header(d))
        for item in group:
            print(line_fmt(item, today))


# ---------------------------------------------------------------- 子命令

def _items(data, key):
    if isinstance(data, dict) and isinstance(data.get(key), list):
        return data[key]
    if isinstance(data, list):
        return data
    return []


def cmd_events(args, expat: bool = False) -> int:
    url = EXPAT_URL if expat else EVENTS_URL
    days = args.days if args.days is not None else (14 if expat else 7)
    data = fetch_json(url)
    items = _items(data, "events")
    today = now_in_data_tz().date()
    picked = filter_upcoming_events(items, days, today)
    if args.json:
        print(json.dumps([it for _, it in picked], ensure_ascii=False, indent=2))
        return 0
    name = SOURCE_EXPAT if expat else SOURCE_EVENTS
    updated = data.get("updated_at", "") if isinstance(data, dict) else ""
    print(f"Yat's List · {name}（未来 {days} 天，共 {len(picked)} 场）" + (f"  数据更新于 {updated}" if updated else ""))
    if not picked:
        print("（这个时间段暂时没有活动）")
        return 0
    print_event_groups(picked, today, fmt_expat_line if expat else fmt_event_line)
    return 0


def cmd_hackathons(args) -> int:
    data = fetch_json(HACKATHONS_URL)
    items = _items(data, "hackathons")
    now = now_in_data_tz()
    picked = filter_hackathons(items, now, soon=args.soon, days=args.days)
    if args.json:
        print(json.dumps([it for _, it in picked], ensure_ascii=False, indent=2))
        return 0
    scope = "72 小时内截止" if args.soon else "报名未截止"
    updated = data.get("updated_at", "") if isinstance(data, dict) else ""
    print(f"Yat's List · {SOURCE_HACKATHONS}（{scope}，共 {len(picked)} 场，按截止日排序）" + (f"  数据更新于 {updated}" if updated else ""))
    if not picked:
        print("（暂时没有符合条件的黑客松）")
        return 0
    for _, item in picked:
        print(fmt_hackathon_line(item))
    return 0


def cmd_spaces(args) -> int:
    data = fetch_json(SPACES_URL)
    items = sort_spaces(_items(data, "spaces"))
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0
    updated = data.get("updated_at", "") if isinstance(data, dict) else ""
    print(f"Yat's List · {SOURCE_SPACES}（共 {len(items)} 场，按日期倒序）" + (f"  数据更新于 {updated}" if updated else ""))
    if not items:
        print("（暂时还没有收录的纪要）")
        return 0
    for item in items:
        print(fmt_space_line(item))
        if item.get("url"):
            print(f"    {item['url']}")
    return 0


def cmd_search(args) -> int:
    ev = _items(fetch_json(EVENTS_URL), "events")
    hk = _items(fetch_json(HACKATHONS_URL), "hackathons")
    ex = _items(fetch_json(EXPAT_URL), "events")
    now = now_in_data_tz()
    results = search_all(ev, hk, ex, args.keyword, now.date(), now)
    if args.json:
        out = []
        for source, _, item in results:
            obj = dict(item)
            obj["source_list"] = source
            out.append(obj)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    print(f"Yat's List · 搜索「{args.keyword}」（共 {len(results)} 条）")
    if not results:
        print("（没有找到匹配的活动，换个关键词试试）")
        return 0
    for source, d, item in results:
        if source == SOURCE_HACKATHONS:
            head = f"  [{source}] 截止 {item.get('deadline')}"
        else:
            t = raw_time(item.get("start")) or ""
            head = f"  [{source}] {(d.isoformat() if d else '')} {t}".rstrip()
        print(f"{head}  {item.get('title') or '(无标题)'}")
        if item.get("url"):
            print(f"    {item['url']}")
    return 0


# ---------------------------------------------------------------- 入口

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yatslist",
        description="Yat's List 命令行客户端：深圳活动 / 黑客松 / 深圳外国人活动 / Space 纪要（数据来源 https://yatslist.com）",
    )
    parser.add_argument("--version", action="version", version=f"yatslist {__version__}")
    parser.add_argument("--days", type=int, default=None, help="只看未来 N 天（默认 7）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 数组")
    sub = parser.add_subparsers(dest="command")

    p_hk = sub.add_parser("hackathons", help="黑客松清单（报名未截止，按截止日排序）")
    p_hk.add_argument("--soon", action="store_true", help="只看 72 小时内截止的")
    p_hk.add_argument("--days", type=int, default=None, help="只看 N 天内截止的")
    p_hk.add_argument("--json", action="store_true", help="输出 JSON 数组")

    p_ex = sub.add_parser("expat", help="深圳外国人活动（默认未来 14 天）")
    p_ex.add_argument("--days", type=int, default=None, help="只看未来 N 天（默认 14）")
    p_ex.add_argument("--json", action="store_true", help="输出 JSON 数组")

    p_sp = sub.add_parser("spaces", help="X Space 纪要清单（按日期倒序）")
    p_sp.add_argument("--json", action="store_true", help="输出 JSON 数组")

    p_se = sub.add_parser("search", help="三张清单一起搜")
    p_se.add_argument("keyword", help="关键词（匹配标题/地点/简介）")
    p_se.add_argument("--json", action="store_true", help="输出 JSON 数组")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except BrokenPipeError:
        # 管道被关闭（如 | head）：把 stdout 转到 /dev/null 后安静退出，不打堆栈
        import os

        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except OSError:
            pass
        return 0


def _dispatch(args) -> int:
    try:
        if args.command == "hackathons":
            return cmd_hackathons(args)
        if args.command == "expat":
            return cmd_events(args, expat=True)
        if args.command == "spaces":
            return cmd_spaces(args)
        if args.command == "search":
            return cmd_search(args)
        return cmd_events(args, expat=False)
    except FetchError as e:
        print(f"错误：{e}", file=sys.stderr)
        print("请检查网络连接后重试。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
