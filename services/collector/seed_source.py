"""种子数据源（演示用）：生成模拟的多平台公开商情信号。

定位说明
--------
本模块是 `CollectorAdapter` 的一种实现，产出与真实公开数据源**完全相同的原始层格式**
（data/raw/*.jsonl）。真实站点接入时只需新增一个适配器（如 `public_page.py`），
下游 ETL、指标、AI 全链路无需改动 —— 用户侧不需要任何手动配置。

覆盖品类：家居收纳 / 厨房餐饮 / 户外露营 / 宠物用品，共 15 个细分类目，
每个子类目在 1~3 个平台有在售条目，便于验证跨平台同款对齐与自由输入解析。

合规说明
--------
本适配器不发起任何网络请求，纯本地合成数据，页面会显著标注"演示数据"。
真实适配器必须遵守 robots.txt、限速、不采集个人信息、不绕过登录与风控。
"""

from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# 输出路径
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = PROJECT_ROOT / "data" / "raw" / "seed"

DAYS = 56
# 结束日期跟随当天，保证演示数据与真实采集数据处于同一时间轴（可混合分析）
END_DATE = date.today()
START_DATE = END_DATE - timedelta(days=DAYS - 1)
RNG_SEED = 20251130
PER_SUBCATEGORY = 13  # 每个细分类目的标准品数量

PLATFORMS = [
    {"platform_id": "p_tmall", "name": "天猫", "source_type": "public_page",
     "compliance_note": "公开商品页与公开榜单，仅采集展示字段，不含用户信息",
     "price_factor": 1.00},
    {"platform_id": "p_jd", "name": "京东", "source_type": "public_page",
     "compliance_note": "公开商品页与公开榜单，仅采集展示字段，不含用户信息",
     "price_factor": 1.08},
    {"platform_id": "p_pdd", "name": "拼多多", "source_type": "public_page",
     "compliance_note": "公开商品页与公开榜单，仅采集展示字段，不含用户信息",
     "price_factor": 0.88},
]

# aliases 用于「用户自由输入商品名」的解析词典（同义词 / 俗称 / 口语说法）
CATEGORY_TREE = [
    {
        "category_id": "c_home", "name": "家居收纳",
        "aliases": ["家居", "收纳", "整理", "储物"],
        "brands": ["轻巢", "慕思家", "简物", "森屿", "禾作", "本味", "南野", "拾光", "木町", "一隅"],
        "children": [
            {"category_id": "c_box", "name": "收纳箱",
             "aliases": ["收纳箱", "整理箱", "储物箱", "收纳盒", "箱子", "收纳筐"],
             "price": (29, 169), "heat": 1.00, "heat_base": 4200,
             "specs": ["45L", "66L", "88L", "110L"],
             "materials": ["牛津布", "PP塑料", "棉麻"],
             "points": ["可折叠", "带轮", "加厚", "透明可视", "可叠加"],
             "reviews": ["容量大", "结实", "无异味", "折叠方便", "盖子偏薄", "颜色偏深"]},
            {"category_id": "c_shelf", "name": "置物架",
             "aliases": ["置物架", "货架", "层架", "收纳架", "架子"],
             "price": (49, 259), "heat": 0.82, "heat_base": 3600,
             "specs": ["3层", "4层", "5层"],
             "materials": ["碳钢", "实木", "不锈钢"],
             "points": ["免安装", "可移动", "承重强", "窄缝适用", "防锈"],
             "reviews": ["稳固", "安装简单", "承重好", "有磕碰", "层距合适", "螺丝偏少"]},
            {"category_id": "c_closet", "name": "衣柜收纳",
             "aliases": ["衣柜收纳", "衣物收纳", "挂袋", "隔板", "衣橱整理"],
             "price": (19, 129), "heat": 0.68, "heat_base": 2900,
             "specs": ["分层隔板", "悬挂式", "抽屉式"],
             "materials": ["无纺布", "竹木", "ABS"],
             "points": ["省空间", "免打孔", "可水洗", "加厚", "多格分区"],
             "reviews": ["省空间", "取用方便", "布料略薄", "分层合理", "尺寸合适", "拉链卡顿"]},
            {"category_id": "c_desk", "name": "桌面收纳",
             "aliases": ["桌面收纳", "笔筒", "文件架", "桌面整理", "首饰盒"],
             "price": (15, 99), "heat": 0.55, "heat_base": 2100,
             "specs": ["笔筒款", "文件架", "首饰盒"],
             "materials": ["亚克力", "皮革", "金属"],
             "points": ["小巧", "多格", "防滑", "透明", "可旋转"],
             "reviews": ["小巧", "做工精细", "放笔刚好", "有色差", "材质一般", "收纳整洁"]},
        ],
    },
    {
        "category_id": "c_kitchen", "name": "厨房餐饮",
        "aliases": ["厨房", "餐饮", "厨具", "餐具", "喝水"],
        "brands": ["瓷谷", "日尝", "一勺", "暖山", "食光", "器物集", "小满", "知行"],
        "children": [
            {"category_id": "c_cup", "name": "保温杯",
             "aliases": ["保温杯", "水杯", "杯子", "焖烧杯", "保温壶", "随行杯", "咖啡杯"],
             "price": (39, 299), "heat": 1.15, "heat_base": 8800,
             "specs": ["350ml", "500ml", "750ml", "1L"],
             "materials": ["316不锈钢", "304不锈钢", "陶瓷内胆", "钛合金"],
             "points": ["长效保温", "轻量", "一键开盖", "防漏", "车载适用"],
             "reviews": ["保温效果好", "不漏水", "手感好", "有异味", "杯盖偏松", "清洗方便"]},
            {"category_id": "c_freshbox", "name": "保鲜盒",
             "aliases": ["保鲜盒", "饭盒", "密封盒", "便当盒", "餐盒", "储物罐"],
             "price": (19, 159), "heat": 0.88, "heat_base": 5200,
             "specs": ["单格", "三格", "五格", "套装"],
             "materials": ["玻璃", "PP", "不锈钢"],
             "points": ["微波可用", "密封防漏", "可冷冻", "分格设计", "可叠放"],
             "reviews": ["密封性好", "好清洗", "偏重", "盖子卡扣偏紧", "容量合适", "有划痕"]},
            {"category_id": "c_kshelf", "name": "厨房置物架",
             "aliases": ["厨房置物架", "调料架", "刀架", "锅盖架", "沥水架"],
             "price": (39, 239), "heat": 0.72, "heat_base": 3900,
             "specs": ["单层", "双层", "落地式"],
             "materials": ["不锈钢", "碳钢烤漆", "竹木"],
             "points": ["免打孔", "防锈", "可调节", "带沥水", "壁挂"],
             "reviews": ["安装方便", "防锈不错", "焊接处粗糙", "承重一般", "尺寸合适", "生锈"]},
            {"category_id": "c_tableware", "name": "餐具套装",
             "aliases": ["餐具", "碗碟", "盘子", "筷子", "碗筷套装"],
             "price": (29, 259), "heat": 0.61, "heat_base": 2600,
             "specs": ["单人份", "双人份", "四人份"],
             "materials": ["骨瓷", "陶瓷", "小麦秸秆"],
             "points": ["可入微波炉", "易清洗", "釉面光滑", "礼盒装", "防烫"],
             "reviews": ["颜值高", "釉面细腻", "有磕碰", "偏薄", "包装好", "色差"]},
        ],
    },
    {
        "category_id": "c_outdoor", "name": "户外露营",
        "aliases": ["户外", "露营", "野营", "徒步", "营地"],
        "brands": ["野行", "山野", "露营家", "途野", "风迹", "营地", "远山", "峰行"],
        "children": [
            {"category_id": "c_chair", "name": "折叠椅",
             "aliases": ["折叠椅", "露营椅", "月亮椅", "克米特椅", "户外椅", "马扎"],
             "price": (59, 399), "heat": 1.05, "heat_base": 7300,
             "specs": ["低背", "高背", "加宽"],
             "materials": ["铝合金", "碳钢", "牛津布"],
             "points": ["轻量便携", "承重120kg", "带收纳袋", "可躺", "加固脚垫"],
             "reviews": ["坐着舒服", "很轻", "收纳方便", "支架偏细", "布料有气味", "稳固"]},
            {"category_id": "c_tent", "name": "露营帐篷",
             "aliases": ["帐篷", "天幕", "帐篷天幕", "遮阳棚", "自动帐篷"],
             "price": (199, 1599), "heat": 0.92, "heat_base": 6400,
             "specs": ["2人", "3-4人", "5-8人"],
             "materials": ["涤纶涂银", "牛津布", "尼龙"],
             "points": ["免搭建", "防雨", "防晒UPF50+", "双层", "透气窗"],
             "reviews": ["搭建简单", "防雨可以", "偏重", "骨架偏软", "空间足够", "有味"]},
            {"category_id": "c_light", "name": "户外照明",
             "aliases": ["露营灯", "氛围灯", "手电筒", "头灯", "营地灯", "灯串"],
             "price": (29, 349), "heat": 0.78, "heat_base": 4100,
             "specs": ["单灯", "双灯", "灯串3米"],
             "materials": ["ABS", "铝合金", "硅胶"],
             "points": ["三档调光", "可充电", "防水IPX4", "磁吸", "暖光氛围"],
             "reviews": ["亮度足", "续航久", "充电口偏紧", "塑料感强", "便携", "发热"]},
            {"category_id": "c_cooler", "name": "保温箱",
             "aliases": ["保温箱", "冷藏箱", "冰包", "冰袋", "车载冰箱"],
             "price": (89, 699), "heat": 0.58, "heat_base": 2300,
             "specs": ["13L", "26L", "45L"],
             "materials": ["EPP", "PU发泡", "牛津布"],
             "points": ["长效保冷", "可坐人", "带提手", "排水口", "食品级内胆"],
             "reviews": ["保冷效果好", "容量合适", "偏重", "盖子密封一般", "做工扎实", "有异味"]},
        ],
    },
    {
        "category_id": "c_pet", "name": "宠物用品",
        "aliases": ["宠物", "猫", "狗", "养宠", "猫咪"],
        "brands": ["毛球", "喵居", "汪小院", "宠爱", "爪印", "小鱼干", "软喵", "毛豆"],
        "children": [
            {"category_id": "c_cat_tree", "name": "猫爬架",
             "aliases": ["猫爬架", "猫树", "猫抓板", "猫跳台", "猫爬柱"],
             "price": (79, 599), "heat": 1.00, "heat_base": 5600,
             "specs": ["三层", "四层", "顶天立地"],
             "materials": ["剑麻", "实木", "绒布"],
             "points": ["稳固不晃", "可拆洗", "多猫适用", "加厚底座", "含猫窝"],
             "reviews": ["猫很喜欢", "稳固", "安装费时", "绒布掉毛", "做工不错", "有毛刺"]},
            {"category_id": "c_pet_bed", "name": "宠物窝",
             "aliases": ["宠物窝", "猫窝", "狗窝", "垫子", "睡垫"],
             "price": (29, 299), "heat": 0.84, "heat_base": 3800,
             "specs": ["S", "M", "L"],
             "materials": ["短绒", "棉麻", "冰丝"],
             "points": ["可拆洗", "四季通用", "加厚保暖", "防滑底", "可折叠"],
             "reviews": ["软和", "好清洗", "掉毛", "偏小", "猫很爱睡", "填充偏薄"]},
            {"category_id": "c_pet_bowl", "name": "宠物食具",
             "aliases": ["宠物碗", "食盆", "饮水机", "自动喂食器", "猫碗", "狗碗"],
             "price": (19, 399), "heat": 0.76, "heat_base": 4400,
             "specs": ["单碗", "双碗", "自动款"],
             "materials": ["陶瓷", "不锈钢", "PP"],
             "points": ["防打翻", "可拆洗", "大容量", "静音", "定时定量"],
             "reviews": ["好用", "易清洗", "出水声偏大", "容量够", "底座不稳", "做工一般"]},
        ],
    },
]


def _log_normal(rng: random.Random, median: float, sigma: float) -> float:
    """对数正态抽样，用于制造销量长尾（头部集中）。"""
    return median * math.exp(rng.gauss(0.0, sigma))


def _platform_factor(platform_id: str) -> float:
    for platform in PLATFORMS:
        if platform["platform_id"] == platform_id:
            return platform["price_factor"]
    return 1.0


def build_catalog(rng: random.Random) -> tuple[list[dict], list[dict]]:
    """构建标准品与各平台上架记录（listing）。"""
    clusters: list[dict] = []
    listings: list[dict] = []
    index = 0

    for parent in CATEGORY_TREE:
        for sub in parent["children"]:
            for _ in range(PER_SUBCATEGORY):
                brand = rng.choice(parent["brands"])
                spec = rng.choice(sub["specs"])
                material = rng.choice(sub["materials"])
                point = rng.choice(sub["points"])

                base_velocity = _log_normal(rng, median=38.0, sigma=0.88) * sub["heat"]
                trend = rng.gauss(0.0018, 0.0072)
                comment_rate = rng.uniform(0.018, 0.055)
                weekend_boost = rng.uniform(1.0, 1.28)
                base_price = rng.uniform(*sub["price"])

                cluster_id = f"cl_{index:04d}"
                canonical_title = f"{brand} {material}{sub['name']} {spec} {point}"
                clusters.append({
                    "cluster_id": cluster_id,
                    "canonical_title": canonical_title,
                    "category_id": sub["category_id"],
                    "parent_id": parent["category_id"],
                })

                platform_count = rng.choices([1, 2, 3], weights=[0.45, 0.38, 0.17], k=1)[0]
                chosen = rng.sample(PLATFORMS, k=platform_count)

                for p_index, platform in enumerate(chosen):
                    suffix = ["官方旗舰店", "自营店", "工厂直营", "优选店"][p_index % 4]
                    title = f"{brand}{sub['name']}{spec}{material}{point} {suffix}"
                    listing_id = f"{platform['platform_id']}_{index:04d}"
                    price = round(base_price * platform["price_factor"] * rng.uniform(0.96, 1.05), 2)
                    listings.append({
                        "product_id": listing_id,
                        "cluster_id": cluster_id,
                        "parent_id": parent["category_id"],
                        "platform_id": platform["platform_id"],
                        "title": title,
                        "brand": brand,
                        "category_id": sub["category_id"],
                        "attrs": {"规格": spec, "材质": material, "卖点": point, "店铺类型": suffix},
                        "url": f"https://example-public-data.invalid/{platform['platform_id']}/{listing_id}",
                        "first_seen": (START_DATE - timedelta(days=rng.randint(30, 400))).isoformat(),
                        "_sim": {
                            "base_velocity": base_velocity * rng.uniform(0.7, 1.3),
                            "trend": trend,
                            "comment_rate": comment_rate,
                            "weekend_boost": weekend_boost,
                            "price": price,
                        },
                    })
                index += 1

    return clusters, listings


def build_signals(rng: random.Random, listings: list[dict]) -> list[dict]:
    """按日推进，生成累计已售、累计评价、榜单排名等公开可见信号。"""
    daily: dict[str, list[float]] = {}
    for item in listings:
        sim = item["_sim"]
        velocity = sim["base_velocity"]
        trend = sim["trend"]
        promo_days = {rng.randint(0, DAYS - 1) for _ in range(rng.randint(1, 4))}
        series: list[float] = []
        for day_index in range(DAYS):
            current = velocity * (1.0 + trend * day_index)
            current *= rng.uniform(0.82, 1.18)
            if day_index in promo_days:
                current *= rng.uniform(1.6, 2.6)
            weekday = (START_DATE + timedelta(days=day_index)).weekday()
            if weekday >= 5:
                current *= sim["weekend_boost"]
            series.append(max(current, 0.4))
        daily[item["product_id"]] = series

    sold_cum: dict[str, float] = {item["product_id"]: 0.0 for item in listings}
    review_cum: dict[str, float] = {item["product_id"]: 0.0 for item in listings}
    rows: list[dict] = []

    for day_index in range(DAYS):
        stat_date = (START_DATE + timedelta(days=day_index)).isoformat()
        rank_map: dict[str, tuple[int, int]] = {}
        groups: dict[tuple[str, str], list[tuple[str, float]]] = {}
        for item in listings:
            key = (item["platform_id"], item["category_id"])
            groups.setdefault(key, []).append((item["product_id"], daily[item["product_id"]][day_index]))
        for group_items in groups.values():
            group_items.sort(key=lambda pair: pair[1], reverse=True)
            list_size = len(group_items)
            for position, (product_id, _value) in enumerate(group_items, start=1):
                rank_map[product_id] = (position, list_size)

        for item in listings:
            product_id = item["product_id"]
            sim = item["_sim"]
            day_sales = daily[product_id][day_index]
            sold_cum[product_id] += day_sales
            review_cum[product_id] += day_sales * sim["comment_rate"] * rng.uniform(0.75, 1.25)

            rank, list_size = rank_map[product_id]
            weekday = (START_DATE + timedelta(days=day_index)).weekday()
            is_promo = rng.random() < 0.06 or weekday in (5, 6)
            promo_price = round(sim["price"] * rng.uniform(0.72, 0.92), 2) if is_promo else None

            rows.append({
                "product_id": product_id,
                "stat_date": stat_date,
                "sold_cumulative": int(round(sold_cum[product_id])),
                "review_cumulative": int(round(review_cum[product_id])),
                "rank": rank,
                "list_size": list_size,
                "price": round(sim["price"] * rng.uniform(0.99, 1.01), 2),
                "promo_price": promo_price,
                "platform_id": item["platform_id"],
            })

    return rows


def build_search_heat(rng: random.Random) -> list[dict]:
    """公开搜索指数（需求侧信号）。"""
    rows: list[dict] = []
    for parent in CATEGORY_TREE:
        for sub in parent["children"]:
            keyword_id = f"kw_{sub['category_id']}"
            base = sub["heat_base"] * rng.uniform(0.8, 1.2)
            slope = rng.uniform(-2.0, 9.0)
            for day_index in range(DAYS):
                stat_date = (START_DATE + timedelta(days=day_index)).isoformat()
                heat = base + slope * day_index + rng.gauss(0, base * 0.03)
                rows.append({
                    "keyword_id": keyword_id,
                    "stat_date": stat_date,
                    "heat_index": round(max(heat, 50.0), 1),
                    "source": "public_search_index",
                })
    return rows


def build_reviews(rng: random.Random, listings: list[dict]) -> list[dict]:
    """评价聚合（仅统计情感与关键词，不留存任何用户信息）。"""
    word_map = {sub["category_id"]: sub["reviews"]
                for parent in CATEGORY_TREE for sub in parent["children"]}
    rows: list[dict] = []
    for item in listings:
        words = word_map[item["category_id"]]
        picked = rng.sample(words, k=min(4, len(words)))
        positive = round(rng.uniform(0.68, 0.95), 3)
        rows.append({
            "product_id": item["product_id"],
            "review_cnt": rng.randint(20, 9000),
            "sentiment_pos": positive,
            "sentiment_neg": round(1.0 - positive, 3),
            "top_keywords": picked,
        })
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def collect() -> dict:
    """执行采集，产出原始层文件。返回采集元信息。"""
    rng = random.Random(RNG_SEED)
    clusters, listings = build_catalog(rng)
    signals = build_signals(rng, listings)
    heat = build_search_heat(rng)
    reviews = build_reviews(rng, listings)

    public_listings = [{k: v for k, v in item.items() if k != "_sim"} for item in listings]

    categories: list[dict] = []
    for parent in CATEGORY_TREE:
        categories.append({
            "category_id": parent["category_id"], "parent_id": None,
            "name": parent["name"], "level": 1, "aliases": parent["aliases"],
        })
        for sub in parent["children"]:
            categories.append({
                "category_id": sub["category_id"], "parent_id": parent["category_id"],
                "name": sub["name"], "level": 2, "aliases": sub["aliases"],
            })

    _write_jsonl(SEED_DIR / "platforms.jsonl", PLATFORMS)
    _write_jsonl(SEED_DIR / "categories.jsonl", categories)
    _write_jsonl(SEED_DIR / "clusters.jsonl", clusters)
    _write_jsonl(SEED_DIR / "listings.jsonl", public_listings)
    _write_jsonl(SEED_DIR / "signals.jsonl", signals)
    _write_jsonl(SEED_DIR / "search_heat.jsonl", heat)
    _write_jsonl(SEED_DIR / "reviews.jsonl", reviews)

    return {
        "source": "seed_simulator",
        "url": "local://seed_simulator",
        "fields": "sold_cumulative,review_cumulative,rank,price,promo_price",
        "records": len(signals) + len(public_listings),
        "files": {
            "categories": len(categories),
            "clusters": len(clusters),
            "listings": len(public_listings),
            "signals": len(signals),
            "search_heat": len(heat),
            "reviews": len(reviews),
        },
        "date_range": [START_DATE.isoformat(), END_DATE.isoformat()],
    }


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
