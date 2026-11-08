# yatslist

**Yat's List 的命令行客户端** — 深圳活动、黑客松、深圳外国人活动，三张清单，一条命令。

**The Yat's List command-line client** — Shenzhen events, hackathons, and expat events in Shenzhen, right in your terminal. Zero third-party dependencies (Python standard library only).

> Shenzhen events, served to your Agent — and now to your terminal, too.

## 安装 / Install

```bash
pip install yatslist
```

需要 Python ≥ 3.9。Requires Python ≥ 3.9. No third-party dependencies.

## 用法 / Usage

```bash
# 深圳活动：今天起未来 7 天，按日期分组
yatslist

# 只看未来 3 天 / 输出 JSON
yatslist --days 3
yatslist --json

# 黑客松：报名未截止，按截止日升序
yatslist hackathons

# 黑客松：只看 72 小时内截止的（赶 deadline 用）
yatslist hackathons --soon

# 深圳外国人活动：未来 14 天（英文活动为主）
yatslist expat
yatslist expat --days 7

# 三张清单一起搜（标题 / 地点 / 简介），结果标注来源清单
yatslist search Agent
yatslist search 咖啡
```

### 示例输出 / Example output

```
$ yatslist
Yat's List · 深圳活动（未来 7 天，共 69 场）  数据更新于 2026-11-08T11:14:12+08:00
2026-11-08 周日
  13:00  xxx Meetup @ 南山智园
  19:00  xxx 公开课 @ 福田区某空间（进行中）
2026-11-09 周一
  ...

$ yatslist hackathons --soon
Yat's List · 黑客松（72 小时内截止，共 12 场，按截止日排序）  数据更新于 ...
  截止 2026-11-08  BoHack 2026 天津青年黑客松（天津 · 线下）
  ...

$ yatslist search AI
Yat's List · 搜索「AI」（共 5 条）
  [深圳活动] 2026-11-09 19:00 xxx AI 分享会
    https://...
  [黑客松] 截止 2026-11-13 xxx Hackathon
    https://...
```

## 数据来源 / Data sources

数据来自 [yatslist.com](https://yatslist.com) 公开 JSON，每日更新、逐条核实自官方页面：

| 清单 | 地址 |
| --- | --- |
| 深圳活动 | https://yatslist.com/events.json |
| 黑客松 | https://yatslist.com/hackathons.json |
| 深圳外国人活动 | https://yatslist.com/expat/events.json |

说明 / Notes:

- 时间按数据源原文呈现，不做时区换算；日期筛选按数据时区（UTC+8）计算。
- Times are shown exactly as published in the data (UTC+8); no timezone conversion is applied.
- 网络失败或超时（10 秒）时会给出中文错误提示并以非零状态码退出。
- `search` 只搜未结束 / 未截止的条目。

## 开发 / Development

```bash
python -m unittest discover -s tests -v   # 离线单元测试（fixtures 样本，不联网）
python -m build                            # 构建 sdist + wheel
```

## License

MIT © Yat Tse
