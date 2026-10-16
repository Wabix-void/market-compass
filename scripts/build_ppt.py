"""生成参赛演示 PPT（商情罗盘 MarketCompass）。

用法：python scripts/build_ppt.py
输出：docs/参赛材料/02-演示PPT.pptx
"""

from __future__ import annotations

import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt


def _force_utf8_console() -> None:
    """Windows 中文控制台默认 GBK，直接输出 ✓/✗ 会抛 UnicodeEncodeError，这里统一兜底。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


_force_utf8_console()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = PROJECT_ROOT / "docs" / "参赛材料" / "02-演示PPT.pptx"

FONT = "微软雅黑"
BLUE = RGBColor(0x2F, 0x6F, 0xEB)
DEEP = RGBColor(0x16, 0x23, 0x3D)
GRAY = RGBColor(0x6B, 0x76, 0x88)
LIGHT = RGBColor(0xEA, 0xF1, 0xFF)
SOFT = RGBColor(0xF5, 0xF7, 0xFA)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
TEAL = RGBColor(0x0F, 0x8F, 0x80)
WARN = RGBColor(0xB0, 0x66, 0x08)
LINE = RGBColor(0xD8, 0xE0, 0xEE)

SW, SH = 13.333, 7.5


def set_font(run, size=16, bold=False, color=DEEP, font=FONT) -> None:
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = font
    rPr = run._r.get_or_add_rPr()
    rFonts = rPr.find(qn("a:latin"))
    if rFonts is not None:
        rFonts.set(qn("a:ea"), font)


def textbox(slide, x, y, w, h, lines, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = anchor
    first = True
    for line in lines:
        if isinstance(line, str):
            line = {"text": line}
        para = frame.paragraphs[0] if first else frame.add_paragraph()
        first = False
        para.alignment = line.get("align", align)
        para.space_after = Pt(line.get("space", 6))
        para.line_spacing = line.get("leading", 1.15)
        if line.get("text"):
            run = para.add_run()
            run.text = line["text"]
            set_font(run, line.get("size", 16), line.get("bold", False),
                     line.get("color", DEEP))
    return box


def rect(slide, x, y, w, h, fill, shape=MSO_SHAPE.RECTANGLE, line_color=None):
    item = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        item.fill.background()
    else:
        item.fill.solid()
        item.fill.fore_color.rgb = fill
    if line_color is None:
        item.line.fill.background()
    else:
        item.line.color.rgb = line_color
        item.line.width = Pt(0.75)
    item.shadow.inherit = False
    return item


def card(slide, x, y, w, h, title, body, fill=WHITE, accent=BLUE,
         title_size=16, body_size=12.5):
    rect(slide, x, y, w, h, fill, MSO_SHAPE.ROUNDED_RECTANGLE, LINE)
    rect(slide, x, y, 0.075, h, accent, MSO_SHAPE.RECTANGLE)
    lines = [{"text": title, "size": title_size, "bold": True, "color": DEEP, "space": 6}]
    for item in body:
        lines.append({"text": item, "size": body_size, "color": GRAY, "space": 4, "leading": 1.25})
    textbox(slide, x + 0.28, y + 0.18, w - 0.5, h - 0.3, lines)


def slide_title(slide, title, subtitle=None):
    rect(slide, 0.6, 0.52, 0.11, 0.5, BLUE, MSO_SHAPE.RECTANGLE)
    lines = [{"text": title, "size": 25, "bold": True, "color": DEEP, "space": 2}]
    if subtitle:
        lines.append({"text": subtitle, "size": 12.5, "color": GRAY})
    textbox(slide, 0.85, 0.44, 11.9, 0.85, lines)


def footer(slide, page: int):
    textbox(slide, 0.6, 6.95, 8, 0.35,
            [{"text": "商情罗盘 MarketCompass · AI 应用大赛（产业应用 · 数据分析）",
              "size": 9.5, "color": GRAY}])
    textbox(slide, 12.2, 6.95, 0.6, 0.35,
            [{"text": str(page), "size": 9.5, "color": GRAY, "align": PP_ALIGN.RIGHT}])


def blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def build() -> Path:
    prs = Presentation()
    prs.slide_width = Inches(SW)
    prs.slide_height = Inches(SH)
    page = 0

    # ---------------- 1 封面 ----------------
    page += 1
    slide = blank(prs)
    rect(slide, 0, 0, SW, SH, DEEP)
    rect(slide, 0, 0, SW, 0.12, BLUE)
    textbox(slide, 0.9, 1.75, 11.5, 1.3,
            [{"text": "商情罗盘  MarketCompass", "size": 46, "bold": True, "color": WHITE}])
    textbox(slide, 0.9, 3.05, 11.5, 0.7,
            [{"text": "面向中小电商的公开商情洞察与 AI 选品参谋", "size": 21, "color": RGBColor(0x9F, 0xC0, 0xFF)}])
    rect(slide, 0.95, 3.95, 3.2, 0.045, BLUE)
    textbox(slide, 0.9, 4.35, 11.5, 1.6, [
        {"text": "把散落在各平台的公开销量信号、价格、榜单与评价，变成可执行、可追溯的决策建议",
         "size": 15, "color": RGBColor(0xC8, 0xD6, 0xF0), "space": 10},
        {"text": "销量代理指标（SPS）  ·  证据链重算校验  ·  四种透明数据口径  ·  全程合规采集",
         "size": 14, "color": RGBColor(0x8F, 0xB4, 0xF8)},
    ])
    textbox(slide, 0.9, 6.35, 11.5, 0.5,
            [{"text": "AI 应用大赛 · 产业应用 · 数据分析   |   已跑通真实公开数据采集与端到端验证",
              "size": 12, "color": RGBColor(0x7E, 0x8F, 0xAD)}])

    # ---------------- 2 痛点 ----------------
    page += 1
    slide = blank(prs)
    slide_title(slide, "中小卖家选品，卡在三个断层",
                "我们访谈与调研的共同结论：不是没有数据，而是数据到决策之间断了三截")
    items = [
        ("① 数据散落", ["销量、价格、榜单、评价分散在不同平台",
                    "人工比价一次要数小时，且无法横向对比",
                    "抓下来的数据没有统一口径，越算越乱"], BLUE),
        ("② 有数无结论", ["现有工具只给表格和图表",
                     "不告诉你「这个类目还值不值得进」",
                     "更不会给出定价区间与切入时机"], TEAL),
        ("③ 有模型无依据", ["直接问大模型「卖什么好」",
                      "答案空泛、无法验证，甚至凭空编造数字",
                      "没有数据背书，卖家不敢照着做"], WARN),
    ]
    for index, (title, body, color) in enumerate(items):
        card(slide, 0.75 + index * 4.05, 1.85, 3.8, 3.1, title, body, accent=color)
    rect(slide, 0.75, 5.35, 11.9, 0.9, LIGHT, MSO_SHAPE.ROUNDED_RECTANGLE)
    textbox(slide, 1.1, 5.5, 11.2, 0.6,
            [{"text": "断层所在，就是产品价值所在：我们补的正是「数据 → 结论 → 可执行动作」这一段。",
              "size": 15, "bold": True, "color": BLUE}], anchor=MSO_ANCHOR.MIDDLE)
    footer(slide, page)

    # ---------------- 3 解决方案 ----------------
    page += 1
    slide = blank(prs)
    slide_title(slide, "商情罗盘：公开商情数据 → 可执行决策",
                "用户只需输入一个商品名，30 秒内得到行情罗列 + 带证据的判断与建议")
    stages = [
        ("数据接入", ["公开页面采集", "官方开放平台 API", "授权导入 / 演示数据"]),
        ("指标层", ["清洗与同款对齐", "销量代理指标 SPS", "竞争集中度 CR5/HHI"]),
        ("AI 决策", ["检索行业知识", "生成建议动作", "证据链重算校验"]),
        ("交付", ["行情看板", "单品档案", "报告导出"]),
    ]
    for index, (title, body) in enumerate(stages):
        x = 0.75 + index * 3.05
        rect(slide, x, 1.95, 2.75, 2.0, WHITE, MSO_SHAPE.ROUNDED_RECTANGLE, LINE)
        rect(slide, x, 1.95, 2.75, 0.42, BLUE if index % 2 == 0 else TEAL, MSO_SHAPE.RECTANGLE)
        textbox(slide, x, 2.0, 2.75, 0.35,
                [{"text": title, "size": 14, "bold": True, "color": WHITE,
                  "align": PP_ALIGN.CENTER}], anchor=MSO_ANCHOR.MIDDLE)
        textbox(slide, x + 0.2, 2.55, 2.35, 1.3,
                [{"text": f"· {line}", "size": 11.5, "color": GRAY, "space": 5} for line in body])
        if index < len(stages) - 1:
            textbox(slide, x + 2.76, 2.65, 0.3, 0.5,
                    [{"text": "▶", "size": 13, "color": LINE, "align": PP_ALIGN.CENTER}])
    card(slide, 0.75, 4.25, 5.85, 2.1, "典型使用场景",
         ["卖家输入「保温杯」",
          "系统解析标的 → 罗列 12 项行情指标 + 价格带 + 品牌份额 + 评价痛点",
          "输出带证据链的定价锚点、差异化切入点与测款候选"], accent=BLUE)
    card(slide, 6.8, 4.25, 5.85, 2.1, "与现有工具的本质差异",
         ["现有工具：给数据，结论靠人",
          "通用大模型：直接生成结论，因此会编",
          "商情罗盘：结论必须能回指标层重算复现，编不出来就整体降级"], accent=TEAL)
    footer(slide, page)

    # ---------------- 4 架构 ----------------
    page += 1
    slide = blank(prs)
    slide_title(slide, "系统架构", "五层分层设计；每种数据源一个适配器，下游 ETL / 指标 / AI / 看板零改动")
    layers = [
        ("应用层", "品类大盘 · 商品行情分析 · 商品排行 · 单品档案 · AI 选品参谋 · 合规审计", BLUE),
        ("AI 层", "检索编排（RAG） · 指标查询工具 · LLM 生成 · 证据链重算校验器", TEAL),
        ("计算层", "清洗标准化 · 跨平台同款对齐 · SPS 指标引擎（四种口径） · 评价挖掘", BLUE),
        ("存储层", "原始层归档（不可变快照） · SQLite 业务库 · 指标表 · 审计台账", TEAL),
        ("接入层", "苏宁公开页适配器 · 官方 API 适配器（淘宝/京东/拼多多） · 演示数据源 · 限速与 robots 判定", BLUE),
    ]
    for index, (name, detail, color) in enumerate(layers):
        y = 1.85 + index * 0.92
        rect(slide, 0.75, y, 2.0, 0.75, color, MSO_SHAPE.ROUNDED_RECTANGLE)
        textbox(slide, 0.75, y, 2.0, 0.75,
                [{"text": name, "size": 14.5, "bold": True, "color": WHITE,
                  "align": PP_ALIGN.CENTER}], anchor=MSO_ANCHOR.MIDDLE)
        rect(slide, 2.95, y, 9.65, 0.75, WHITE, MSO_SHAPE.ROUNDED_RECTANGLE, LINE)
        textbox(slide, 3.25, y, 9.1, 0.75,
                [{"text": detail, "size": 12, "color": GRAY}], anchor=MSO_ANCHOR.MIDDLE)
    footer(slide, page)

    # ---------------- 5 功能一：自由输入 ----------------
    page += 1
    slide = blank(prs)
    slide_title(slide, "核心功能一：输入任意商品，得到行情分析",
                "用户不需要懂类目体系，直接输入想投资的商品名即可")
    card(slide, 0.75, 1.8, 3.8, 3.0, "① 解析标的",
         ["词典（类目名 + 别名 + 品牌）+ 字符 bigram 相似度",
          "输出匹配标的、匹配依据、匹配度",
          "阈值 0.5；品牌输入自动落到主销类目",
          "实测：「保温杯」「露营装备」「慕思家」全部命中"], accent=BLUE)
    card(slide, 4.75, 1.8, 3.8, 3.0, "② 罗列行情数据",
         ["12 张 KPI：规模 / 环比 / CR5 / HHI / 品牌 CR3 / 供需缺口",
          "价格带分布、品牌份额、细分结构",
          "销量代理 Top12、增长最快 / 下滑最明显",
          "评价关键词分痛点与卖点两组"], accent=TEAL)
    card(slide, 8.75, 1.8, 3.9, 3.0, "③ 生成判断与建议",
         ["结论：走势、竞争结构、机会点",
          "建议动作：定价锚点、差异化切入点、测款候选",
          "每条动作绑定一个可复现指标",
          "风险提示 + 局限性声明"], accent=WARN)
    rect(slide, 0.75, 5.05, 11.9, 1.15, SOFT, MSO_SHAPE.ROUNDED_RECTANGLE, LINE)
    textbox(slide, 1.1, 5.18, 11.2, 0.9, [
        {"text": "未覆盖不编造：匹配度低于阈值时明确返回「数据未覆盖」，并给出最接近的候选标的。",
         "size": 13.5, "bold": True, "color": DEEP, "space": 4},
        {"text": "实测：「猫爬架」在苏宁仅 1 条相关供给（页面其余 26 条是推荐位的无关商品），系统如实呈现而非凑数。",
         "size": 11.5, "color": GRAY},
    ])
    footer(slide, page)

    # ---------------- 6 功能二：证据链 ----------------
    page += 1
    slide = blank(prs)
    slide_title(slide, "核心功能二：AI 建议必须带证据链",
                "每条结论都绑定指标名 + 数值 + 周期 + 来源 + 置信度")
    fill = {"title": "AI 输出结构（节选）",
            "body": ['"summary": "一句话结论"',
                     '"evidence": [{"metric": "market.cr5:保温杯", "value": 0.98,',
                     '              "period": "2026-10-15", "confidence": 0.46,',
                     '"actions":  [{"step": "定价锚定 …", "evidence_metric": "…"}]',
                     '"risks" / "limitations" / "verification"']}
    rect(slide, 0.75, 1.9, 6.0, 4.3, RGBColor(0x0F, 0x17, 0x2A), MSO_SHAPE.ROUNDED_RECTANGLE)
    textbox(slide, 1.0, 2.05, 5.5, 0.4,
            [{"text": fill["title"], "size": 13, "bold": True, "color": RGBColor(0x9F, 0xC0, 0xFF)}])
    textbox(slide, 1.0, 2.55, 5.6, 3.5,
            [{"text": line, "size": 11, "color": RGBColor(0xCF, 0xE0, 0xFF), "space": 5}
             for line in fill["body"]])
    steps = [("生成建议", "模型只组织语言，不产生数字"),
             ("提取引用", "解析出全部 evidence 指标名"),
             ("回指标层重算", "按指标名重新执行查询"),
             ("逐条比对", "相对容差 0.5%"),
             ("判定", "任一条不通过 → 整体降级为「数据不足」")]
    for index, (name, detail) in enumerate(steps):
        y = 1.9 + index * 0.88
        rect(slide, 7.1, y, 5.55, 0.76, WHITE, MSO_SHAPE.ROUNDED_RECTANGLE, LINE)
        textbox(slide, 7.35, y + 0.06, 5.1, 0.64, [
            {"text": f"{index + 1}. {name}", "size": 12.5, "bold": True, "color": BLUE, "space": 1},
            {"text": detail, "size": 10.5, "color": GRAY},
        ])
    textbox(slide, 7.1, 6.32, 5.55, 0.5,
            [{"text": "★ 这是用架构抑制幻觉，而不是靠提示词祈祷模型别乱说。",
              "size": 12, "bold": True, "color": TEAL}])
    footer(slide, page)

    # ---------------- 7 AI 追问 + 数字溯源 ----------------
    page += 1
    slide = blank(prs)
    slide_title(slide, "AI 追问：模型作答，数字必须能溯源",
                "追问是模板原理上做不到的事 —— 让模型答，但每个数字事后都要回指标层核对")
    ask_steps = [
        ("用户追问", "「5 万预算适合做这个类目吗？」"),
        ("取指标快照", "复用行情分析已算好的指标，模型只见数字"),
        ("模型作答", "只组织语言，禁止引入新数字、禁止预测"),
        ("逐数字回查", "抽出回答中所有数字，回指标层比对（容差 2%）"),
    ]
    for index, (name, detail) in enumerate(ask_steps):
        x = 0.75 + index * 3.05
        rect(slide, x, 1.75, 2.78, 1.35, WHITE, MSO_SHAPE.ROUNDED_RECTANGLE, LINE)
        rect(slide, x, 1.75, 2.78, 0.36, BLUE if index % 2 == 0 else TEAL, MSO_SHAPE.RECTANGLE)
        textbox(slide, x, 1.78, 2.78, 0.3,
                [{"text": f"{index + 1}. {name}", "size": 12.5, "bold": True,
                  "color": WHITE, "align": PP_ALIGN.CENTER}], anchor=MSO_ANCHOR.MIDDLE)
        textbox(slide, x + 0.15, 2.2, 2.48, 0.85,
                [{"text": detail, "size": 10.5, "color": GRAY}])

    rect(slide, 0.75, 3.35, 5.85, 2.9, WHITE, MSO_SHAPE.ROUNDED_RECTANGLE, LINE)
    rect(slide, 0.75, 3.35, 0.075, 2.9, TEAL, MSO_SHAPE.RECTANGLE)
    textbox(slide, 1.05, 3.5, 5.3, 2.6, [
        {"text": "实测 · 正常路径", "size": 14, "bold": True, "color": TEAL, "space": 6},
        {"text": "问：我只有 5 万预算，适合做这个类目吗？", "size": 11.5, "color": DEEP, "space": 5},
        {"text": "答：该指标显示 CR5 为 0.8979、brand_cr3 为 1.0，集中度很高，"
                 "但 avg_confidence 仅 0.433……", "size": 11, "color": GRAY, "space": 5},
        {"text": "✅ 校验：回答中 8 个数字全部可溯源（citations）",
         "size": 11.5, "bold": True, "color": TEAL},
    ])

    rect(slide, 6.8, 3.35, 5.85, 2.9, WHITE, MSO_SHAPE.ROUNDED_RECTANGLE, LINE)
    rect(slide, 6.8, 3.35, 0.075, 2.9, WARN, MSO_SHAPE.RECTANGLE)
    textbox(slide, 7.1, 3.5, 5.3, 2.6, [
        {"text": "实测 · 故意让模型自由估算", "size": 14, "bold": True, "color": WARN, "space": 6},
        {"text": "把提示词换成「可以基于常识推断」后，模型回答：",
         "size": 11.5, "color": DEEP, "space": 5},
        {"text": "「CR5 达 89.8%、品牌 CR3 为 100%，月销约 2.5 万件，"
                 "建议首期备货预算 15-25 万元。」", "size": 11, "color": GRAY, "space": 5},
        {"text": "❌ 校验：2.5 / 15 / 25 在指标层找不到出处，当场标红",
         "size": 11.5, "bold": True, "color": WARN},
    ])

    rect(slide, 0.75, 6.32, 11.9, 0.5, LIGHT, MSO_SHAPE.ROUNDED_RECTANGLE)
    textbox(slide, 1.0, 6.32, 11.4, 0.5,
            [{"text": "★ 我们不要求模型不撒谎，我们要求它撒的谎能被抓住 —— 这一题现场可以演示。",
              "size": 12, "bold": True, "color": BLUE}], anchor=MSO_ANCHOR.MIDDLE)
    footer(slide, page)

    # ---------------- 8 关键技术 1：SPS ----------------
    page += 1
    slide = blank(prs)
    slide_title(slide, "关键技术一：销量代理指标 SPS",
                "公开数据拿不到平台真实销量——这是我们实测的硬结论，也是设计的前提")
    rect(slide, 0.75, 1.8, 11.9, 1.5, SOFT, MSO_SHAPE.ROUNDED_RECTANGLE, LINE)
    textbox(slide, 1.05, 1.92, 11.3, 1.3, [
        {"text": "实测证据（2026-10-15）", "size": 12.5, "bold": True, "color": WARN, "space": 3},
        {"text": "京东搜索页只返回 2.7KB 空壳；商品页价格由 JS 异步加载（36KB HTML 里没有价格）；"
                 "p.3.cn 价格接口超时；淘宝与唯品会的 robots.txt 明确 Disallow 搜索页；京东 / 当当的 "
                 "robots.txt 被替换成首页 HTML。", "size": 11.5, "color": GRAY},
    ])
    rows = [
        ("口径 mode", "触发条件", "计算方式", "置信度上限"),
        ("full_signal", "有公开已售件数增量", "0.58·Δ已售 + 0.24·评价反推 + 0.18·榜单分位", "0.96"),
        ("api_volume_direct", "官方 API 滚动销量", "直接作为规模值，不做增量推算", "0.85"),
        ("single_snapshot_stock_basis", "公开页仅 1 天快照", "评价存量 ÷ 转化率 ÷ 假设窗口 90 天", "0.46"),
        ("review_increment_basis", "公开页 ≥2 天", "评价增量 ÷ 类目评价转化率", "0.46"),
    ]
    table_shape = slide.shapes.add_table(len(rows), 4, Inches(0.75), Inches(3.5),
                                         Inches(11.9), Inches(2.3))
    table = table_shape.table
    for col, width in zip(range(4), (3.1, 2.6, 4.7, 1.5)):
        table.columns[col].width = Inches(width)
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            cell = table.cell(r, c)
            cell.text = value
            cell.margin_left = Inches(0.08)
            cell.margin_top = Inches(0.03)
            para = cell.text_frame.paragraphs[0]
            set_font(para.runs[0], 10.5 if r else 11.5, r == 0,
                     WHITE if r == 0 else (DEEP if c == 0 else GRAY))
            cell.fill.solid()
            cell.fill.fore_color.rgb = BLUE if r == 0 else (WHITE if r % 2 else SOFT)
    textbox(slide, 0.75, 6.0, 11.9, 0.6,
            [{"text": "★ 我们不把估算包装成真值：置信度低的自动压低，环比不可用时明确写「暂不可用」而不是给 0%。",
              "size": 12.5, "bold": True, "color": TEAL}])
    footer(slide, page)

    # ---------------- 8 数据源可信度分级 ----------------
    page += 1
    slide = blank(prs)
    slide_title(slide, "数据源决定口径，口径决定可信度",
                "越权威的来源指标越硬；换源后机制不变，只是口径升级")
    rows = [
        ("数据源", "可获取字段", "指标口径 mode", "置信度上限"),
        ("官方开放平台 API", "真实销量、价格、类目、库存", "api_volume_direct", "0.85"),
        ("公开页面（≥2 天）", "评价数、榜单排名、店铺类型", "review_increment_basis", "0.46"),
        ("公开页面（仅 1 天）", "同上", "single_snapshot_stock_basis", "0.46"),
        ("公开页面（增量不可观测）", "同上（评价数为缓存展示值）",
         "review_increment_stale_stock_fallback", "0.40"),
    ]
    shape = slide.shapes.add_table(len(rows), 4, Inches(0.75), Inches(1.78),
                                   Inches(11.9), Inches(2.45))
    table = shape.table
    for col, width in zip(range(4), (2.7, 3.4, 4.3, 1.5)):
        table.columns[col].width = Inches(width)
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            cell = table.cell(r, c)
            cell.text = value
            cell.margin_left = Inches(0.08)
            cell.margin_top = Inches(0.02)
            para = cell.text_frame.paragraphs[0]
            set_font(para.runs[0], 10 if r else 11.5, r == 0,
                     WHITE if r == 0 else (DEEP if c == 0 else GRAY))
            cell.fill.solid()
            cell.fill.fore_color.rgb = BLUE if r == 0 else (WHITE if r % 2 else SOFT)

    notes = [
        ("滚动销量 ≠ 累计销量",
         "官方接口给的是「近 30 天销量」这类滚动值，当累计值相减会得到无意义的数。"
         "系统用 sales_semantics 标记隔离，只作规模值，不参与增量推算。", WARN),
        ("平台之间的精度差异",
         "淘宝 volume 返回具体数字；拼多多 sales_tip 返回「1万+」区间提示。"
         "申请凭据时优先选择返回精确值的接口。", TEAL),
        ("换源不改机制",
         "无论数据来自公开页还是官方 API，口径、置信度、证据链全部透明可追溯"
         "—— 这才是可信度的真正保障。", BLUE),
    ]
    for index, (title, body, color) in enumerate(notes):
        card(slide, 0.75 + index * 4.05, 4.55, 3.8, 2.0, title, [body],
             accent=color, title_size=14, body_size=11)
    footer(slide, page)

    # ---------------- 9 数据与合规 ----------------
    page += 1
    slide = blank(prs)
    slide_title(slide, "数据源与合规：能抓什么，不抓什么",
                "合规不是答辩时的补丁，而是写进采集器的硬约束")
    src_rows = [
        ("数据源", "接入方式", "实测结果"),
        ("苏宁易购", "公开搜索结果页", "✅ 稳定解析 SKU/标题/卖点/评价数/店铺/排名"),
        ("官方开放平台", "淘宝 / 京东 / 拼多多授权接口", "✅ 适配器与配置向导完成，待凭据启用"),
        ("演示数据集", "本地合成", "✅ 4 大类 15 子类 / 356 条目 / 19,936 条日指标"),
    ]
    shape = slide.shapes.add_table(len(src_rows), 3, Inches(0.75), Inches(1.8),
                                   Inches(6.4), Inches(1.9))
    table = shape.table
    for col, width in zip(range(3), (1.7, 2.3, 2.4)):
        table.columns[col].width = Inches(width)
    for r, row in enumerate(src_rows):
        for c, value in enumerate(row):
            cell = table.cell(r, c)
            cell.text = value
            cell.margin_left = Inches(0.07)
            para = cell.text_frame.paragraphs[0]
            set_font(para.runs[0], 10 if r else 10.5, r == 0, WHITE if r == 0 else GRAY)
            cell.fill.solid()
            cell.fill.fore_color.rgb = BLUE if r == 0 else (WHITE if r % 2 else SOFT)
    card(slide, 0.75, 3.95, 6.4, 2.5, "合规红线（已写入代码）",
         ["遵守 robots.txt，且识别「robots.txt 被返回成首页 HTML」的陷阱",
          "默认限速 3 秒/请求，不并发、不重试轰炸",
          "不采集任何个人信息（无用户 ID、无评论正文）",
          "不绕过登录与风控；被禁止的平台直接不抓",
          "每次采集写审计台账：来源 / URL / 时间 / robots 判定 / 字段 / 批次"], accent=TEAL)
    card(slide, 7.5, 1.8, 5.15, 4.65, "为什么坚持合规路线",
         ["灰产式抓包（逆向 App 接口、绕过签名与验证码）违反平台协议，",
          "可能触及《反不正当竞争法》《数据安全法》，",
          "在产业应用赛道属于一票否决风险。",
          "",
          "我们选择：公开数据 + 官方授权接口 + 用户授权导入，",
          "并把每次采集的合规判定写进审计台账，",
          "答辩时可以直接回答「这条数据哪来的」。",
          "",
          "代价是数据完整度不如灰产，收益是产品可以真的落地。"], accent=WARN)
    footer(slide, page)

    # ---------------- 9 实测结果 ----------------
    page += 1
    slide = blank(prs)
    slide_title(slide, "实测结果：真实数据已跑通",
                "不是概念演示——真实公开数据已入库并跑完全链路")
    metrics = [
        ("80", "个真实商品", "苏宁公开搜索页两轮采集去重入库"),
        ("20,082", "条日指标", "演示数据集 + 两轮真实数据合计"),
        ("62", "项测试", "35 端到端 + 18 适配器 + 9 AI 溯源"),
        ("0", "第三方依赖", "纯 Python 标准库 · MIT 开源"),
    ]
    for index, (value, unit, detail) in enumerate(metrics):
        x = 0.75 + index * 3.05
        rect(slide, x, 1.85, 2.78, 1.85, WHITE, MSO_SHAPE.ROUNDED_RECTANGLE, LINE)
        textbox(slide, x, 2.0, 2.78, 1.6, [
            {"text": value, "size": 32, "bold": True, "color": BLUE, "align": PP_ALIGN.CENTER, "space": 0},
            {"text": unit, "size": 13, "bold": True, "color": DEEP, "align": PP_ALIGN.CENTER, "space": 4},
            {"text": detail, "size": 10.5, "color": GRAY, "align": PP_ALIGN.CENTER},
        ])
    card(slide, 0.75, 3.95, 5.85, 2.85, "真实数据下的分析输出（节选）",
         ["「保温杯」：30 个真实商品，CR5=0.90、HHI=0.170（高度集中）",
          "建议动作 3 条，均为真实商品（JEKO / 希乐 / 炊大皇）",
          "每条建议附证据指标，证据链校验通过",
          "报告自动标注：环比不可用、价格未采集"], accent=BLUE)
    card(slide, 6.8, 3.95, 5.85, 2.85, "两轮采集中发现并修复的真实问题",
         ["评价数是缓存展示值，日级增量观测不到 → 新增降级口径（0.40）",
          "同名类目在演示/真实数据中歧义 → 解析优先真实源并支持切换",
          "搜「猫爬架」27 条里 26 条是无关推荐位商品 → 加相关性过滤",
          "官方 API 返回滚动销量 → 不能当累计值相减 → 新增独立口径"], accent=WARN)
    footer(slide, page)

    # ---------------- 10 产业价值 ----------------
    page += 1
    slide = blank(prs)
    slide_title(slide, "产业价值与落地路径", "从「靠经验试错」到「靠证据决策」")
    card(slide, 0.75, 1.85, 3.8, 2.5, "目标用户",
         ["中小电商卖家 / 个体创业者",
          "品牌市场部与选品团队",
          "投研与咨询分析师",
          "代运营与电商服务商"], accent=BLUE)
    card(slide, 4.75, 1.85, 3.8, 2.5, "直接价值",
         ["把数小时人工比价压缩到 30 秒",
          "降低选品试错与压货风险",
          "定价有锚点、切入有理由、风险有提示",
          "每条结论可追溯到数据来源"], accent=TEAL)
    card(slide, 8.75, 1.85, 3.9, 2.5, "商业模式",
         ["SaaS 订阅（按类目 / 席位）",
          "单份市场机会报告按次付费",
          "为服务商提供批量选品 API",
          "数据合规，可对接企业采购流程"], accent=WARN)
    steps = [("已完成", "真实公开数据采集 + 指标 + AI 建议 + 看板全链路跑通"),
             ("下一步（短期）", "启用官方 API 补真实销量与价格；支持用户粘贴页面 / 浏览器书签采集长尾站点"),
             ("下一步（中期）", "Agent 自动生成《某品类市场机会研究报告》；对接商家后台做授权导入"),
             ("下一步（长期）", "沉淀行业级商情数据库，输出类目指数与趋势预测")]
    for index, (name, detail) in enumerate(steps):
        y = 4.6 + index * 0.6
        rect(slide, 0.75, y, 2.2, 0.5, LIGHT, MSO_SHAPE.ROUNDED_RECTANGLE)
        textbox(slide, 0.85, y, 2.0, 0.5,
                [{"text": name, "size": 11, "bold": True, "color": BLUE,
                  "align": PP_ALIGN.CENTER}], anchor=MSO_ANCHOR.MIDDLE)
        textbox(slide, 3.15, y, 9.5, 0.5,
                [{"text": detail, "size": 11.5, "color": GRAY}], anchor=MSO_ANCHOR.MIDDLE)
    footer(slide, page)

    # ---------------- 11 结尾 ----------------
    page += 1
    slide = blank(prs)
    rect(slide, 0, 0, SW, SH, DEEP)
    rect(slide, 0, 0, SW, 0.12, BLUE)
    textbox(slide, 1.0, 2.3, 11.3, 1.2,
            [{"text": "让每一个选品决策，都有数据可依", "size": 34, "bold": True, "color": WHITE}])
    rect(slide, 1.05, 3.55, 3.0, 0.045, BLUE)
    textbox(slide, 1.0, 3.9, 11.3, 2.0, [
        {"text": "商情罗盘 MarketCompass", "size": 17, "bold": True,
         "color": RGBColor(0x9F, 0xC0, 0xFF), "space": 10},
        {"text": "80 个真实商品已入库   ·   20,082 条日指标   ·   62 项测试通过   ·   0 第三方依赖",
         "size": 13.5, "color": RGBColor(0xC8, 0xD6, 0xF0), "space": 8},
        {"text": "感谢观看，欢迎提问与指正", "size": 13, "color": RGBColor(0x7E, 0x8F, 0xAD)},
    ])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(OUT_PATH))
    return OUT_PATH


if __name__ == "__main__":
    path = build()
    print(f"已生成：{path}")
    print(f"页数：{len(Presentation(str(path)).slides)}")
    sys.exit(0)
