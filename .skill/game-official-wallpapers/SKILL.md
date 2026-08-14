---
name: game-official-wallpapers
description: "获取游戏官方背景图/壁纸（鸣潮、异环、明日方舟终末地、明日方舟等）。当用户要某游戏的官方壁纸、背景图、主视觉、启动器背景、角色立绘大图时使用。提供各游戏的官方图床直链提取方法和下载命令。"
---

# 游戏官方背景图/壁纸获取

用户要某游戏的官方壁纸/背景图时，按此流程执行：官网/官方渠道 → 提取官方图床直链 → curl 下载 → 按版本新旧筛选 → 本地整理。

## 通用方法

1. **抓官网 HTML 提取图片直链**（最优先，官网通常直接内嵌官方图床 URL）：
   ```bash
   curl -s -L --max-time 30 "官网URL" -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0" | grep -oiE 'https?://[^"'\'' ]+\.(jpg|jpeg|png|webp)' | sort -u
   ```
2. **识别官方图床**：`web.hycdn.cn`（鹰角）、`wxN.sinaimg.cn`（微博）、`i.17173cdn.com`（17173 转载 CDN）。
3. **下载**：`curl -sL --max-time 40 -o 文件名 "直链"`。
4. **按新旧筛选**：直链 URL 常含日期（如 `upload/image/20260808/`）或文章发布时间；优先取最新版本的图。
5. **下载后确认内容**：用 Read 工具看图；超大 webp/png 会提示 "Image too large" 无法 inline 预览，但文件本身有效，无需重下。

## 各游戏专项

### 鸣潮 Wuthering Waves（库洛）
- **官网** `mc.kurogames.com`：SPA 预约页，**无**独立壁纸栏目。
- **官方壁纸源**：微博 @鸣潮、微信公众号、B站（每月日历壁纸、版本 4K 壁纸、角色立绘）。
- **可抓取渠道**：17173 转载文章（`news.17173.com/content/日期/xxx.shtml`）内含 `i.17173cdn.com` 直链，**必须带浏览器 UA**，否则 403。
- 版本节奏：2026-08-20 上线 3.6「蜃云灯影，凡尘剑心」（清宵、景燃）。

### 异环 Anomaly（完美世界 HottaStudio）
- **官网** `yh.wanmei.com`：传统页面，**无**独立壁纸栏目，壁纸随新闻/活动文章发布。
- **官方壁纸源**：官方微博 @异环 发布角色壁纸。
- **可抓取渠道**：新浪新闻转载官方微博文章（`sina.cn/news/detail/xxx.html`）内含 `wxN.sinaimg.cn/middle/xxx` 直链；**把 `/middle/` 换成 `/large/` 即高清原图**，无需 UA。
- 版本节奏：2026-08-13 上线 1.3「雾中朔望星回」（残虹、灵可）。

### 明日方舟：终末地 Arknights: Endfield（鹰角）
- **官网** `endfield.hypergryph.com`：Next.js SPA，但**页面 HTML 直接内嵌官方图床直链**。
- **抓取方法**：
  ```bash
  curl -s -L "https://endfield.hypergryph.com/?source_from=official" -H "User-Agent: ..." | grep -oiE 'https?://web\.hycdn\.cn/upload/[^"'\'' ]+\.(png|jpg|jpeg)'
  ```
- **官方图床** `web.hycdn.cn/upload/image/YYYYMMDD/hash.png`，URL 含日期可排序筛选，无需 UA，即官网原图。
- 官网另有新闻页 `endfield.hypergryph.com/news/<id>` 含高清大图（如 6000×3375 嘉年华图）。
- 版本节奏：2026-07-10「向渊行」核心章节；最新角色壁纸如梨诺（2026-08-08）。

### 明日方舟 Arknights（鹰角）
- **鹰角启动器背景图**：PRTS Wiki「鹰角启动器背景图片一览」：
  `https://prts.wiki/w/鹰角启动器背景图片一览`（URL 需编码：`%E9%B9%B0%E8%A7%92%E5%90%AF%E5%8A%A8%E5%99%A8%E8%83%8C%E6%99%AF%E5%9B%BE%E7%89%87%E4%B8%80%E8%A7%88`）
- 页面按年份/活动分类（如"2026-7-20 集成战略「沉沦者的黑流树海」"），展开即可看大图/拿链接。
- **注意**：PRTS 对 curl 返回 403（Tengine 反爬），需用 WebFetch 工具或浏览器访问；图链通常在折叠的 `<details>` 里。

## 常见坑
- 17173 CDN（`i.17173cdn.com`）裸请求 403，必须带浏览器 UA。
- 微博图床 `wxN.sinaimg.cn`：`/middle/` 是中等尺寸，`/large/` 是高清原图；改路径即可，不用换参数。
- Windows Git Bash 下 `curl -o` 写某些路径（如 `/tmp`、AppData）会失败；改用管道输出或写工作区路径。
- 第三方转载站（17173、新浪）的图多为官方原图，但需注意是转载；要第一手原图去官方微博/官网。
