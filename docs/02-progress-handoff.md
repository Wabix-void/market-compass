# 商情罗盘 MarketCompass — 进度存档（Handoff）

| 项目 | 内容 |
|---|---|
| 存档时间 | 2026-10-15（当天续做后已更新） |
| 当前状态 | **三个数据源全通**：演示源（模拟 56 天）/ 苏宁公开页（73 条真实）/ 官方开放平台（淘宝·京东·拼多多，待凭据验证） |
| 后台任务 | 服务运行中（端口 8787） |
| 下一步 | 拿到 AppKey 后跑 `--live` 验证；然后是答辩材料（Word 提案 + PPT） |

---

## 0. 一句话现状

全链路可用：演示数据（模拟，56 天时间序列）与真实数据（苏宁公开搜索页，单日快照）两条路径都跑通，
AI 行情分析在真实数据下能给出**真实商品、真实评价数**支撑的建议，且所有引用指标都能回指标层重算复现。

尚未开始：官方开放平台 API 适配器骨架与 appkey 配置向导（用户明确说"我不会填 appkey"，要做成粘贴式）。

---

## 1. 恢复步骤（三条命令）

```bash
cd E:\dsh-workspace\market-compass

# 1) 重建数据与指标（约 1.5 秒，只读本地原始层，不发网络请求）
python scripts/bootstrap.py

# 2) 启动服务与看板
python scripts/run_server.py          # → http://127.0.0.1:8787

# 3) 端到端冒烟测试（需服务已启动，35 项断言）
python tests/smoke_test.py
```

推荐解释器（本机已验证）：

```
C:\Users\wbx\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe
```

项目**零第三方依赖**，系统 Python `C:\Python\Python313\python.exe` 同样能跑。

---

## 2. 已完成并验证

| 模块 | 文件 | 验证方式 | 结果 |
|---|---|---|---|
| 数据模型与建表 | `infra/sql/schema.sql` | bootstrap 建库 | ✅ |
| 演示数据源（模拟公开信号） | `services/collector/seed_source.py` | bootstrap 采集 | ✅ 19 类目 / 195 标准品 / 356 条目 / 19,936 信号 |
| ETL：清洗 + 跨平台同款对齐 + SPS 指标 | `services/etl/pipeline.py` | bootstrap + 冒烟测试 | ✅ 183 簇 / 115 跨平台 / 19,936 指标 |
| 分析层查询 | `services/analytics/queries.py` | 冒烟测试 | ✅ |
| 自由输入行情分析 | `services/analytics/market_analysis.py` | 冒烟测试 | ✅ 保温杯/露营装备/猫爬架/保鲜盒 全部命中 |
| AI 报告 + 证据链重算校验 | `services/ai/advisor.py` | 冒烟测试 | ✅ 35/35 断言通过 |
| REST API（标准库 HTTP） | `apps/api/server.py` | 冒烟测试 | ✅ 13 个接口 |
| 前端看板（原生 HTML/Canvas） | `apps/web/` | node --check 语法 + 6 页签对应 | ✅ |
| 端到端冒烟测试 | `tests/smoke_test.py` | 实际运行 | ✅ 35/35 |

---

## 3. 进行中（未完成，注意）

### 3.1 苏宁真实采集适配器 —— ✅ 已跑通（本节保留踩坑记录）

- 文件：`services/collector/suning_search.py`，入口 `scripts/collect_suning.py`
- 实测结果：保温杯 29 条 / 收纳箱 15 条 / 置物架 29 条 = **73 条真实商品**，含真实标题、评价数、店铺类型、排名
- **踩过的三个坑（重要）**：
  1. **User-Agent 写了中文** → HTTP 头只能用 latin-1，请求根本没发出去（`UnicodeEncodeError`）。
     现已改为纯 ASCII，并让 `_http_get` 把异常原因带出来（否则只看到 `HTTP -1` 无法定位）；
  2. **搜索结果页混入"相关推荐"** → 实测搜"猫爬架"，27 条里 26 条是消毒液等无关商品，
     导致行情分析推荐出消毒液。现按"完整关键词 / 关键词尾部 2-gram"两级过滤，
     并把过滤条数写入采集报告（`filtered_out`）；
  3. **同款不同 SKU 标题前缀相同** → 候选品出现 3 条重复建议。
     现按标题前 18 字归组，同系列只保留量级最高者。
- 关键词选择依据：实测"猫爬架"在苏宁仅 1 条相关供给（长尾品类），
  故默认关键词定为 `["保温杯", "收纳箱", "置物架"]`（供给充足、相关性好）

### 3.2 ETL 多源改造 —— ✅ 已完成并验证

- `pipeline.py`：`RAW_ROOT` + `discover_sources()` 自动发现源；`_read_jsonl(name, sources)`；
  `run_all(sources=...)`；各 `load_*` 带 sources；按源写审计台账；新增 `metric_modes` 统计
- 已验证：`sources: ["suning"]`、`metric_modes: {"single_snapshot_stock_basis": 73}`、证据链通过
- `scripts/bootstrap.py` 支持 `--sources suning` / `--sources seed,suning`

### 3.3 单日快照口径 —— ✅ 已用真实数据验证

三种 mode（见 README"数据口径"章节）。真实源实测全部落在 `single_snapshot_stock_basis`，
置信度 0.46，报告中明确输出"环比暂不可用（仅 1 天快照）"，不产生 0% 这种误导值。

---

## 4. 待办清单（按优先级）

**P0（已全部完成）**

1. ✅ 运行苏宁采集，确认解析条数正常并可入库（73 条）
2. ✅ 补采集入口脚本 `scripts/collect_suning.py`（支持 `--keywords`、`--interval`）
3. ✅ 用 `sources=["suning"]` 跑 bootstrap，验证单日快照口径
4. ✅ README 标注真实源口径：**"真实源为存量口径，趋势指标需累积 ≥2 天"**

**P1（✅ 已全部完成）**

5. ✅ 官方开放平台 API 适配器骨架（淘宝 / 京东 / 拼多多），含签名、公共参数、时间戳格式差异封装、
   响应容错映射、限速配额
6. ✅ **appkey 配置向导**：`scripts/setup_openapi.py` 交互式粘贴（输入不回显），
   写入 `config/openapi.env`（已 gitignore）；配 `scripts/check_openapi.py` 自检（支持 `--live` / `--dry-run`）
7. ✅ 补上 `sales_semantics` 列与 `api_volume_direct` 口径（官方 API 的滚动窗口销量不能当累计值相减）
8. ✅ 新增 `tests/test_openapi.py`（18 项单元测试，无需凭据全通过）

**P2（待做）**

9. ⏳ 拿到真实 AppKey 后跑 `check_openapi.py --live`，按实际响应校准 `openapi_source.py` 顶部字段常量
10. ⏳ 前端「商品行情分析」页顶部加真实源口径横幅（目前提示只在报告文本里）
11. ⏳ 隔天重跑 `collect_suning.py`，验证自动升级为 `review_increment_basis` 口径
12. ⏳ 答辩材料：项目提案 Word + 路演 PPT

---

## 5. 环境事实（重要，别重复踩坑）

| 事项 | 结论 |
|---|---|
| 网络 | **可用**。Python urllib 实测 baidu / jd / pypi / github 全部 200 |
| ❗历史误判 | 我曾判断"环境无法联网"并据此选了零依赖方案。**该判断是错的** —— 当时是 PowerShell `Invoke-WebRequest` 失败，不代表 Python 不通 |
| pip | 能访问 PyPI（能解析到 `fastapi 0.143.1`），但**安装被沙箱文件权限拒绝**（临时目录 Permission denied）。要装 FastAPI / Playwright 需提升沙箱权限 |
| 解释器 | 推荐 `C:\Users\wbx\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe`（3.12）；系统 `C:\Python\Python313\python.exe` 也能跑（项目零依赖） |
| Node | `C:\Users\wbx\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe`（用于 `node --check`） |
| 端口 | 默认 8787，可用环境变量 `MARKETCOMPASS_PORT` 覆盖 |
| 沙箱 | workspace-write；`Get-CimInstance` 被拒绝（不影响功能） |
| 日志 | 设 `MARKETCOMPASS_VERBOSE=1` 可让服务打印每次 HTTP 请求 |
| PowerShell 中文 POST | `Invoke-WebRequest` 发中文 JSON 会乱码，**验证请用 `tests/smoke_test.py`**（Python urllib，UTF-8 正确） |

---

## 6. 数据源实测结论（2026-10-15 实测）

| 平台 | robots.txt | 搜索页静态抓取 | 结论 |
|---|---|---|---|
| **苏宁** | 404（无规则） | ✅ 200 / 242KB，可解析 SKU、标题、卖点、**评价数**、店铺、排名 | **可抓**（价格异步加载拿不到） |
| 国美 | 404 | ❌ 连接失败 | 不可用 |
| 淘宝 | ✅ 真实规则 `Disallow: /*?*` | — | **被 robots 明确禁止** |
| 唯品会 | ✅ 真实规则 `Disallow: /*?*` | ❌ 16KB 空内容 | **被 robots 明确禁止** |
| 京东 | ⚠️ 被替换成首页 HTML | ❌ 搜索页仅 2.7KB 空壳；web_fetch 被重定向到 `cfe.m.jd.com` | 反爬有效，不抓 |
| 当当 | ⚠️ 被替换成 HTML | ❌ 编码 + 反爬 | 不抓 |
| 什么值得买 | ✅ 真实规则 | ❌ 202 / 209B 空内容 | 反爬有效 |

**关键坑（务必记住）**：京东、当当的 `/robots.txt` 返回的是**首页 HTML**，而
`urllib.robotparser` 解析失败时会**默认返回"允许"** —— 不核对响应内容就会把违规抓取误判成合规。
`suning_search.check_robots()` 已针对这一点做了 HTML 检测并保守放弃。

**另一条重要结论**：任何非官方渠道都拿不到平台真实销量。京东搜索页返回空壳、价格由 JS 异步加载、
`p.3.cn` 价格接口超时。所以项目里"SPS 代理指标 + 置信区间"的设计不是退让，而是唯一诚实的做法。

**合规红线**：robots 明确禁止的平台不抓；即使 robots 缺失也限速 3 秒/请求、只取公开展示字段、
不采集任何个人信息、逐次写审计台账。

---

## 7. 关键设计口径（改动前先看这里）

| 项 | 值 / 规则 |
|---|---|
| SPS 权重 | `W_SOLD / W_REVIEW / W_RANK = 0.58 / 0.24 / 0.18` |
| SPS 区间 | `margin = clamp(0.55 - 0.42 × confidence, 0.10, 0.45)` |
| 单日快照假设窗口 | `STOCK_WINDOW_DAYS = 90`，置信度上限 0.46 |
| 证据链校验 | 每条 claim 按指标名回指标层**重算**，相对容差 0.5%，任一条不通过则整体降级 |
| 自由输入解析 | 阈值 0.5；类型权重 细分类目 1.0 / 一级类目 0.95 / 品牌 0.9 |
| 类目体系 | seed：4 个一级 + 15 个二级；苏宁接入后新增 `c_sn_root` + 每关键词一个二级类目 |
| 商品簇对齐 | 品牌 + 规格 + 材质 + 标题字符相似度 |
| AI 模式 | 默认离线模板（`offline-template`），配 `MARKETCOMPASS_LLM_*` 环境变量后自动切真模型，模型只润色不算数 |

---

## 8. 文件清单（2026-10-17 核对）

```
market-compass/
├── README.md / LICENSE（MIT）/ 使用说明.txt
├── 1-配置官方API凭据.bat / 2-启动看板.bat / 3-采集真实数据.bat / 4-重新初始化数据.bat
├── config/openapi.env.example               # 凭据模板（真实凭据不入库）
├── docs/
│   ├── 01-project-design.md                 # 设计说明（赛道已细化为「产业应用 · 数据分析」）
│   ├── 02-progress-handoff.md               # 本存档
│   └── 参赛材料/                            # 00 提交清单 / 01 作品简介 / 02 演示PPT
│                                            # 03 视频脚本 / 04 补充说明 / 05 GitHub 指南
├── apps/
│   ├── api/server.py                        # 13 个接口
│   └── web/{index.html,app.js,styles.css}   # 6 个页签
├── services/
│   ├── collector/
│   │   ├── seed_source.py                   # 演示数据源（已跑通）
│   │   ├── suning_search.py                 # ✅ 真实源（两轮采集共 80 商品）
│   │   ├── openapi_source.py                # 官方 API 适配器（淘宝/京东/拼多多）
│   │   └── raw_store.py                     # 原始层落盘（各适配器共用）
│   ├── etl/pipeline.py                      # 多源 ETL + 审计台账持久化
│   ├── analytics/{queries.py,market_analysis.py}
│   └── ai/{advisor.py,llm_provider.py}
├── infra/sql/schema.sql
├── scripts/                                 # bootstrap / run_server / collect_suning
│                                            # setup_openapi / check_openapi / collect_openapi
│                                            # build_ppt / check_deck_layout
├── tests/{smoke_test.py,test_openapi.py}    # 35 + 18 = 53 项断言
└── data/                                    # marketcompass.db + raw/{seed,suning}
```

## 9. 2026-10-17 按「问题清单与交接文档」完成的修复

来源：`E:\dsh-workspace\MarketCompass-问题清单与交接.md`

| 项 | 修复内容 | 验证方式 |
|---|---|---|
| **审计台账被清空**（真缺陷） | `audit_collect_log` 从 `TABLES` 重置清单移除；`write_audit` 对真实源追加、对演示源只保留最新一条 | 连跑 3 次 bootstrap：suning 记录 1→2→3→4 累积，seed 恒为 1 条 |
| 赛道细化 | 全部改为「产业应用 · 数据分析」 | `01-project-design.md`、PPT 封面与页脚 |
| 差异化表述 | 补充说明新增第三节；PPT 第 3 页卡片改写为「通用大模型直接生成结论，因此会编 / 商情罗盘要求结论必须能回指标层重算复现」 | PPT 渲染逐页目视确认 |
| 开源立场 | 补充说明第二节新增"零依赖 ≠ 不用开源"的澄清；PPT 第 10 页标注 MIT | — |
| 应用价值量化 | 补充说明新增第六节：引用公开数据（中国卖家近 55% 销量来自 1–2 年内新品、某卖家推新 ACOS 126.8%）+ 自测性能（单次完整分析 391 ms / 18 KB、大盘 76 ms、排行 96 ms） | 性能为本次实测 |
| 可复用性与生态价值 | 补充说明第九节新增"可复用性""生态与合作价值"两块 | — |
| 作品简介字数 | 三版全部压到字符口径内：A 590 汉字 / 795 字符，B 205 / 270，C 72 / 96；标题改为标注实测值 | 脚本统计三版均达标 |
| LICENSE 署名 | `MarketCompass contributors` → `Wabix-void` | — |
| 设计文档状态过时 | 「业务实现待开发」→「全链路已实现…53 项自动化测试通过」 | — |

**未做（需人决策）**：AI 是否接真实模型（路线 A / B）、录制演示视频、正式赛题公布后的定位调整。

