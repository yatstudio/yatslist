"""离线单元测试：用 tests/fixtures 下的样本 JSON 测筛选/分组/搜索逻辑。

固定 now = 2026-11-08（周日）12:00 +08:00，保证结果确定。
运行：python -m unittest discover -s tests -v（在项目根目录）
"""

import json
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from yatslist import cli  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=cli.DATA_TZ)
TODAY = NOW.date()


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


class TestParsing(unittest.TestCase):
    def test_parse_datetime_with_seconds(self):
        dt = cli.parse_datetime("2026-11-08T14:00:00+08:00")
        self.assertEqual((dt.hour, dt.minute), (14, 0))

    def test_parse_datetime_without_seconds(self):
        dt = cli.parse_datetime("2026-11-14T09:30+08:00")
        self.assertEqual((dt.hour, dt.minute), (9, 30))

    def test_parse_datetime_date_only(self):
        dt = cli.parse_datetime("2026-11-10")
        self.assertEqual(dt.date().isoformat(), "2026-11-10")

    def test_parse_none_and_garbage(self):
        self.assertIsNone(cli.parse_datetime(None))
        self.assertIsNone(cli.parse_datetime(""))
        self.assertIsNone(cli.parse_datetime("not-a-date"))

    def test_raw_time_takes_source_text(self):
        self.assertEqual(cli.raw_time("2026-11-08T19:00:00+08:00"), "19:00")
        self.assertEqual(cli.raw_time("2026-11-08T09:30+08:00"), "09:30")
        self.assertIsNone(cli.raw_time("2026-11-08"))
        self.assertIsNone(cli.raw_time(None))


class TestFilterEvents(unittest.TestCase):
    def setUp(self):
        self.items = load("events.json")["events"]

    def test_window_7_days(self):
        picked = cli.filter_upcoming_events(self.items, 7, TODAY)
        titles = [it["title"] for _, it in picked]
        self.assertIn("今天下午的分享会", titles)
        self.assertIn("进行中的展览", titles)
        self.assertIn("第七天的活动（窗口内）", titles)  # 11-14 在 [11-08, 11-15) 内
        self.assertNotIn("第八天的活动（窗口外）", titles)  # 11-15 起，窗口外
        self.assertNotIn("已经结束的活动", titles)
        self.assertNotIn("没有开始时间的活动", titles)
        self.assertEqual(len(picked), 3)

    def test_ongoing_displayed_under_today(self):
        picked = cli.filter_upcoming_events(self.items, 7, TODAY)
        by_title = {it["title"]: d for d, it in picked}
        self.assertEqual(by_title["进行中的展览"], TODAY)  # 11-01 开始、未结束 → 归到今天

    def test_grouping(self):
        picked = cli.filter_upcoming_events(self.items, 7, TODAY)
        groups = cli.group_by_date(picked)
        self.assertEqual([g[0].isoformat() for g in groups], ["2026-11-08", "2026-11-14"])
        self.assertEqual(len(groups[0][1]), 2)

    def test_days_override(self):
        picked = cli.filter_upcoming_events(self.items, 1, TODAY)
        titles = [it["title"] for _, it in picked]
        self.assertEqual(sorted(titles), ["今天下午的分享会", "进行中的展览"])


class TestFilterHackathons(unittest.TestCase):
    def setUp(self):
        self.items = load("hackathons.json")["hackathons"]

    def test_unexpired_sorted_by_deadline(self):
        picked = cli.filter_hackathons(self.items, NOW)
        titles = [it["title"] for _, it in picked]
        self.assertEqual(
            titles,
            ["今天截止的黑客松", "两天后截止的黑客松", "下个月截止的黑客松"],
        )

    def test_soon_72h(self):
        picked = cli.filter_hackathons(self.items, NOW, soon=True)
        titles = [it["title"] for _, it in picked]
        self.assertEqual(titles, ["今天截止的黑客松", "两天后截止的黑客松"])

    def test_days_window(self):
        picked = cli.filter_hackathons(self.items, NOW, days=3)
        self.assertEqual(len(picked), 2)


class TestExpatWindow(unittest.TestCase):
    def test_default_14_days(self):
        items = load("expat.json")["events"]
        picked = cli.filter_upcoming_events(items, 14, TODAY)
        titles = [it["title"] for _, it in picked]
        self.assertEqual(sorted(titles), ["English Comedy Night", "Long-running Art Exhibition"])


class TestSpaces(unittest.TestCase):
    def setUp(self):
        self.items = load("spaces.json")["spaces"]

    def test_sort_desc_by_date(self):
        ordered = cli.sort_spaces(self.items)
        self.assertEqual([it["id"] for it in ordered], ["series-ep16", "mid-single", "older-single"])

    def test_line_with_series_and_episode(self):
        item = [it for it in self.items if it["id"] == "series-ep16"][0]
        line = cli.fmt_space_line(item)
        self.assertEqual(line, "  2026-11-07  《测试系列》第 16 期：如何社交？  [测试系列 第16期]")

    def test_line_without_series(self):
        item = [it for it in self.items if it["id"] == "older-single"][0]
        line = cli.fmt_space_line(item)
        self.assertEqual(line, "  2026-10-27  单期节目：一个话题")

    def test_expat_url_points_to_szexpat(self):
        self.assertEqual(cli.EXPAT_URL, "https://yatslist.com/szexpat/events.json")
        self.assertEqual(cli.SPACES_URL, "https://yatslist.com/spaces.json")


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.ev = load("events.json")["events"]
        self.hk = load("hackathons.json")["hackathons"]
        self.ex = load("expat.json")["events"]

    def test_search_events_by_venue(self):
        results = cli.search_all(self.ev, self.hk, self.ex, "美术馆", TODAY, NOW)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], cli.SOURCE_EVENTS)
        self.assertEqual(results[0][2]["title"], "进行中的展览")

    def test_search_hackathons_by_topic(self):
        results = cli.search_all(self.ev, self.hk, self.ex, "web3", TODAY, NOW)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], cli.SOURCE_HACKATHONS)

    def test_search_expat_case_insensitive(self):
        results = cli.search_all(self.ev, self.hk, self.ex, "COMEDY", TODAY, NOW)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], cli.SOURCE_EXPAT)

    def test_search_skips_expired(self):
        results = cli.search_all(self.ev, self.hk, self.ex, "咖啡馆", TODAY, NOW)
        self.assertEqual(results, [])  # 唯一匹配是已结束活动

    def test_search_no_match(self):
        results = cli.search_all(self.ev, self.hk, self.ex, "不存在的词xyz", TODAY, NOW)
        self.assertEqual(results, [])


class TestFormatting(unittest.TestCase):
    def test_event_line(self):
        item = load("events.json")["events"][0]
        line = cli.fmt_event_line(item, TODAY)
        self.assertEqual(line, "  14:00  今天下午的分享会 @ 南山智园")

    def test_ongoing_marker(self):
        item = load("events.json")["events"][1]
        line = cli.fmt_event_line(item, TODAY)
        self.assertTrue(line.endswith("（进行中）"))

    def test_hackathon_line(self):
        item = load("hackathons.json")["hackathons"][0]
        line = cli.fmt_hackathon_line(item)
        self.assertEqual(line, "  截止 2026-11-08  今天截止的黑客松（深圳 · 线下）")

    def test_date_header_weekday(self):
        # 2026-11-08 是周日
        self.assertEqual(cli.fmt_date_header(TODAY), "2026-11-08 周日")


if __name__ == "__main__":
    unittest.main()
