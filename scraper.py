# Created by 青云 on 2026/10/21.
"""新车上市 & 降价 数据抓取。只用标准库。

- 降价榜：懂车帝排行榜接口 rank_data_type=52（本地经销商报价，按城市）
- 月销量榜：懂车帝排行榜接口 rank_data_type=11（支持 month=YYYYMM）
- 新车上市 / 即将上市：Google News RSS 标题解析
- 最新上市车型（补充）：爱卡汽车新车频道
懂车帝接口没有公开文档，类型编号为实测结果。
"""
import gzip, html, json, re, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta, date
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).parent
DATA_FILE = ROOT / "data.json"
CST = timezone(timedelta(hours=8))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
CITIES = ["杭州", "上海", "北京", "广州", "深圳", "成都", "武汉", "南京"]
RANK_API = "https://www.dongchedi.com/motor/pc/car/rank_data"
SALES_MONTHS = 6


def fetch(url, timeout=20, raw=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
    if b[:2] == b"\x1f\x8b":
        b = gzip.decompress(b)
    return b if raw else b.decode("utf-8", "ignore")


def rank(rank_type, city="杭州", count=50, offset=0, month=""):
    q = urllib.parse.urlencode({"aid": 1839, "app_name": "auto_web_pc", "city_name": city, "count": count,
                                "offset": offset, "rank_data_type": rank_type, "month": month, "nation": 0})
    d = json.loads(fetch(f"{RANK_API}?{q}"))
    return (d.get("data") or {}).get("list") or [], (d.get("data") or {}).get("paging") or {}


def slim(x):
    return {"id": x["series_id"], "name": x["series_name"], "brand": x.get("brand_name", ""),
            "img": x.get("image", "").replace("tplv-resize:640:0", "tplv-resize:240:0"),
            "price": x.get("price", ""), "min": x.get("min_price"), "max": x.get("max_price")}


# ── 降价榜（按城市）──────────────────────────────────────
def cuts():
    out = {}
    for city in CITIES:
        items, total = [], 0
        for off in (0, 50):
            lst, paging = rank(52, city=city, offset=off)
            total = paging.get("total", total)
            items += [{**slim(x), "cut": x.get("descender_price"), "pct": x.get("count")} for x in lst if x.get("descender_price")]
            time.sleep(0.2)
        if items:
            out[city] = {"total": total, "items": items}
    if not out:
        raise ValueError("no cut data")
    return out


# ── 月销量榜（近 6 个月）──────────────────────────────────
def sales(old):
    known = old.get("sales", {})
    out = {}
    m = datetime.now(CST).date().replace(day=1)
    checked = 0
    while len(out) < SALES_MONTHS and checked < SALES_MONTHS + 3:
        m = (m - timedelta(days=1)).replace(day=1)
        key = m.strftime("%Y%m")
        checked += 1
        # 已结束且已抓过的月份不再请求（最近一个月每天刷新，数据可能补录）
        if key in known and len(out) > 0:
            out[key] = known[key]
            continue
        items = []
        for off in (0, 50):
            lst, _ = rank(11, month=key, offset=off)
            items += [{**slim(x), "sales": x.get("count"), "rank": x.get("rank")} for x in lst]
            time.sleep(0.2)
        if items:
            out[key] = items
    if not out:
        raise ValueError("no sales")
    return dict(sorted(out.items(), reverse=True))


# ── 新车上市（新闻标题解析）────────────────────────────────
PRICE_RE = re.compile(r"(\d{1,3}(?:\.\d{1,2})?)(?:\s*万元?)?(?:\s*[-–—~～至]\s*(\d{1,3}(?:\.\d{1,2})?))?\s*万")
DATE_RE = re.compile(r"(?:将于|定档|官宣|于)?\s*(\d{1,2})月(\d{1,2})日(?:晚)?\s*(?:正式)?(?:全球|焕新|全新)?(?:上市|发布|开启交付)")
# 剥掉价格、日期、营销用语后，取「上市 / 预售」前面的最后一段作为车型名
STRIP_RE = re.compile(r"【[^】]*】|[“”\"'《》！!]|(?:限时|超级)?(?:置换价|置换|权益价|起售价|预售价|售价|售|指导价|官方指导价|一口价|补贴后)?\s*\d+(?:\.\d+)?\s*万元?"
                      r"(?:\s*[-–—~～至]\s*\d+(?:\.\d+)?\s*万元?)?起?|将于\s*\d+月\d+日(?:晚)?|于?\s*\d+月\d+日|正式|官宣|定档|即将|全球|焕新")
GENERIC = ("全新", "新款", "第二代", "第三代", "二代", "三代", "大", "新")
BRANDS = ("比亚迪", "吉利", "长安", "奇瑞", "大众", "丰田", "本田", "日产", "别克", "宝马", "奔驰", "奥迪", "小鹏", "蔚来", "理想",
          "小米", "零跑", "问界", "极氪", "领克", "哈弗", "坦克", "深蓝", "阿维塔", "智己", "岚图", "腾势", "方程豹", "捷达", "红旗")
NOISE = ("销量", "降价", "召回", "财报", "股价", "营收", "国补", "补贴", "以旧换新", "车展", "预计", "或将", "曝光", "谍照", "申报",
         "FAQ", "值不值", "什么时候", "明年", "多少钱", "怎么样", "？", "?")   # 问答式 SEO 文和推测性内容不算新车上市


def launches():
    out = []
    queries = [("正式上市 售价 万元 when:21d", "launched"), ("将于 月 日 上市 预售 when:30d", "upcoming"),
               ("新车 上市 指导价 万 when:21d", "launched")]
    for q, kind in queries:
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"})
        root = ET.fromstring(fetch(url))
        for it in root.iter("item"):
            title, src = it.findtext("title") or "", it.find("source")
            source = (src.text or "") if src is not None else ""
            if source and title.endswith(" - " + source):
                title = title[: -len(source) - 3]
            title = html.unescape(title).strip()
            if "上市" not in title and "预售" not in title or any(w in title for w in NOISE):
                continue
            try:
                pub = parsedate_to_datetime(it.findtext("pubDate")).astimezone(CST)
            except Exception:
                continue
            seg = next((s for s in re.split(r"[，,|｜：:；;!！?？]", title) if re.search(r"上市|预售|发布", s)), title)
            head = re.split(r"上市|开启预售|开启预订|预售|发布", STRIP_RE.sub(" ", seg))[0]
            parts = [x for x in re.split(r"[\s/、]+", head) if x]
            name = parts[-1] if parts else ""
            if len(parts) >= 2 and re.fullmatch(r"[A-Za-z0-9\-\.]+", name):   # 「小鹏 MONA L05」这类英文型号带上前一段
                name = parts[-2] + " " + name
            # 泛指多款车的盘点、数码产品等不是具体车型
            if len(name) < 2 or re.search(r"新车|多款|几款|\d款新|^\d款|这两款|最近|一大波|公布|重磅|^级|vivo|香港|手机", name):
                name = ""
            pr = PRICE_RE.search(title)
            dm = DATE_RE.search(title)
            launch_date = None
            if dm:
                y = pub.year + (1 if int(dm.group(1)) < pub.month - 6 else 0)
                try:
                    launch_date = date(y, int(dm.group(1)), int(dm.group(2))).isoformat()
                except ValueError:
                    pass
            upcoming = bool(launch_date and launch_date > pub.date().isoformat()) or ("预售" in title and "上市" not in seg.replace("预售", ""))
            out.append({"title": title, "url": it.findtext("link"), "source": source, "time": pub.isoformat(),
                        "name": name[:24], "price": [float(pr.group(1)), float(pr.group(2) or pr.group(1))] if pr else None,
                        "presale": "预售" in title, "date": launch_date or (None if upcoming else pub.date().isoformat()),
                        "status": "upcoming" if upcoming else "launched"})
    # 同一车型多家报道：去掉年款 / 代际 / 品牌等修饰后，按包含关系去重，保留最新一条
    def norm(nm):
        k = re.sub(r"\d{4}款|款|纯电续航\d+公里|续航\d+公里|闪充豪华旗舰轿车", "", nm)
        for w in BRANDS + GENERIC:
            k = k.replace(w, "")
        return re.sub(r"\W", "", k).lower()
    res = []
    for n in sorted(out, key=lambda x: x["time"], reverse=True):
        k = norm(n["name"])
        if not k:                                    # 没识别出车型名的标题丢弃，避免把行业新闻当新车
            continue
        dup = next((r for r in res if k in r["_k"] or r["_k"] in k), None)
        if dup:
            dup["also"] = dup.get("also", 0) + 1
            if not dup["price"] and n["price"]:
                dup["price"] = n["price"]
            continue
        n["_k"] = k
        res.append(n)
    for r in res:
        r.pop("_k", None)
    if not res:
        raise ValueError("no launches")
    return res[:60]


# ── 爱卡：最新上市车型（无日期，补充）───────────────────────
def xcar():
    h = fetch("https://newcar.xcar.com.cn/", raw=True).decode("gb18030", "ignore")
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", h, flags=re.S)))
    seg = t[t.find("最新上市") + 4: t.find("车型热度排行榜")] if "最新上市" in t else ""
    items, buf = [], []
    for tok in seg.split():                          # 「车型名（可能多个词）价格」交替出现
        if re.fullmatch(r"\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?万", tok):
            if buf:
                items.append({"name": " ".join(buf), "price": tok})
            buf = []
        else:
            buf.append(tok)
    if not items:
        raise ValueError("no xcar list")
    return items[:20]


def main():
    old = {}
    if DATA_FILE.exists():
        try:
            old = json.loads(DATA_FILE.read_text("utf-8"))
        except Exception:
            old = {}
    now = datetime.now(CST).isoformat(timespec="seconds")
    sources = []

    def run(name, fn, key, *args):
        try:
            res = fn(*args)
            sources.append({"name": name, "ok": True, "count": len(res), "updated": now})
            return res
        except Exception as e:
            prev = next((s for s in old.get("sources", []) if s["name"] == name), {})
            sources.append({"name": name, "ok": False, "error": str(e)[:120], "updated": prev.get("updated")})
            return old.get(key) or ({} if key in ("cuts", "sales") else [])

    data = {
        "updated": now,                          # 每次都变 = 心跳，保证每次运行都有提交
        "cities": CITIES,
        "cuts": run("懂车帝 降价榜", cuts, "cuts"),
        "sales": run("懂车帝 月销量", sales, "sales", old),
        "launches": run("新车上市新闻", launches, "launches"),
        "xcar": run("爱卡 最新上市", xcar, "xcar"),
        "sources": sources,
    }
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), "utf-8")
    c = data["cuts"].get("杭州", {})
    print("cuts", {k: (v["total"], len(v["items"])) for k, v in data["cuts"].items()})
    print("hz top", [(x["name"], x["price"], x["cut"], x["pct"]) for x in c.get("items", [])[:3]])
    print("sales", {k: (len(v), v[0]["name"], v[0]["sales"]) for k, v in data["sales"].items()})
    print("launches", len(data["launches"]))
    for x in data["launches"][:12]:
        print("  ", x["status"], x["date"], x["name"], x["price"], "|", x["title"][:46])
    print("xcar", data["xcar"][:4])
    print("failed", [s["name"] for s in sources if not s["ok"]])


if __name__ == "__main__":
    main()
