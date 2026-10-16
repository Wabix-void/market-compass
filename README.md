# 商情罗盘 MarketCompass

> 面向中小电商的多源公开商情洞察与 AI 选品参谋

采集电商平台**公开**的商品销量代理信号、价格、榜单与评价信息，构建结构化商情指标，并通过「指标层 + 规则/大模型 + 证据链校验」输出可解释的选品、定价与行情分析建议。

**真实数据已跑通**：内置苏宁易购公开搜索结果页采集适配器，87 → 73 条真实商品入库，全链路无需任何第三方依赖。

## 快速开始

无需安装任何第三方依赖（仅用 Python 标准库）：

```bash
# 方式 A：用演示数据（模拟，56 天时间序列，指标最完整）
python scripts/bootstrap.py
python scripts/run_server.py            # → http://127.0.0.1:8787

# 方式 B：用真实公开数据（苏宁易购搜索页，限速 3 秒/请求）
python scripts/collect_suning.py                       # 采集，约 15 秒
python scripts/bootstrap.py --sources suning           # 入库 + 算指标
python scripts/run_server.py

# 方式 C：模拟 + 真实混合
python scripts/bootstrap.py --sources seed,suning

# 端到端冒烟测试（需服务已启动）
python tests/smoke_test.py
```

端口可用环境变量 `MARKETCOMPASS_PORT` 覆盖；`MARKETCOMPASS_VERBOSE=1` 可打开服务请求日志。

## 核心能力

### 1. 商品行情分析（自由输入）

用户在「商品行情分析」页直接输入想投资的商品，系统自动完成：

```
自由输入（保温杯 / 露营装备 / 猫爬架 / 慕思家）
  → 解析为细分类目 / 一级类目 / 品牌（词典 + 字符 bigram 相似度，带匹配依据与匹配度）
  → 指标层取数，罗列行情数据（规模、趋势、价格带、品牌份额、竞争格局、评价痛点、增长榜）
  → 生成行情判断与建议动作，每条动作绑定可复现的指标
  → 证据链重算校验，无法复现即拒绝输出
```

未覆盖的商品会明确返回"数据未覆盖"，并给出最接近的候选标的，**不会编造行情**。

### 2. 真实公开数据采集

| 数据源 | 接入方式 | 实测可抓字段 |
|---|---|---|
| `seed`（演示） | 本地合成 | 已售件数、评价数、榜单排名、价格、促销价 |
| `suning`（真实） | 公开搜索结果页 | SKU、标题、卖点、**评价数**、店铺类型、榜单排名 |

采集合规设计：
- 采集前读取 `robots.txt`，**识别"robots.txt 被返回成首页 HTML"的陷阱**（`robotparser` 遇到这种会默认放行，直接采信会误判成合规）；
- 默认限速 **3 秒/请求**，不并发、不重试轰炸；
- 只取公开展示字段，**不采集任何个人信息**（无用户 ID、无评论正文）；
- 每次采集写入 `audit_collect_log` 审计台账（来源、URL、时间、robots 判定、字段范围、批次）；
- **相关性过滤**：搜索结果页常混入"相关推荐"（实测搜"猫爬架"时 27 条里有 26 条是消毒液等无关商品），
  按"完整关键词 / 关键词尾部 2-gram"两级判定过滤，并把过滤条数写进采集报告。

### 3. 证据链机制

AI 输出的每条结论都绑定 `指标名 + 数值 + 周期 + 来源 + 置信度`；生成后校验器按指标名**回指标层重算**，
逐条比对（相对容差 0.5%）。任一条无法复现，整体降级为"数据不足"。

## 当前状态

| 能力 | 状态 |
|---|---|
| F1 数据接入中心 | ✅ 苏宁公开页已跑通；官方 API 适配器（淘宝/京东/拼多多）+ 配置向导已完成，待真实凭据验证 |
| F2 数据治理与跨平台同款对齐 | ✅ 模拟数据 183 簇 / 115 跨平台 |
| F3 商情分析引擎 | ✅ 趋势、价格带、CR5/HHI、供需缺口、评价痛点 |
| F4 AI 决策参谋（选品 + 自由输入行情分析） | ✅ 离线模板模式；配置环境变量即切换真模型 |
| F5 可视化看板 | ✅ 大盘 / 行情分析 / 排行 / 单品档案 / AI 参谋 / 审计 |
| F6 权限与配额 | ⏳ 规划中 |

**数据规模**：演示源 4 一级 / 15 二级类目 / 195 标准品 / 356 条目 / 19,936 条日指标；
真实源（苏宁）3 个关键词 / 73 条真实商品 / 单日快照。

## ⚠️ 数据口径（重要，答辩必看）

公开数据**拿不到平台真实销量**——京东搜索页返回空壳、价格由 JS 异步加载、`p.3.cn` 价格接口超时。
因此系统输出的是**销量代理指标 SPS**，并有三种口径：

| 口径 mode | 触发条件 | 计算方式 | 置信度上限 |
|---|---|---|---|
| `full_signal` | 有"已售件数"增量（演示源、逐日累积数据） | `0.58·Δ已售 + 0.24·评价反推 + 0.18·榜单分位` | 0.96 |
| `api_volume_direct` | 官方开放平台返回滚动窗口销量 | 直接作为规模值，不做增量推算 | 0.85 |
| `single_snapshot_stock_basis` | 仅 1 天快照且无已售信号（**公开页接入初期**） | `评价存量 ÷ 类目评价转化率 ÷ 假设窗口 90 天` | 0.46 |
| `review_increment_basis` | ≥2 天且评价增量 > 0 | `评价增量 ÷ 类目评价转化率` | 0.46 |
| `review_increment_stale_stock_fallback` | ≥2 天但评价增量观测为 0（公开页评价数是缓存展示值） | 退化为存量估计：`评价存量 ÷ 转化率 ÷ 假设窗口 90 天` | 0.40 |

单日快照模式下，**环比与趋势不可用**（报告里显示"环比暂不可用"，不会给出 0% 这种误导值）；
累积 ≥2 天采集后自动升级为增量口径。价格缺失时报告显示"价格未采集"，销售额估计标记为不可用。

> **两轮真实采集的实测结论（2026-10-15 / 10-16）**：66 个商品两日的评价数**一个都没变**——
> 苏宁公开页展示的是缓存值（如"9000+"），一天间隔观测不到增量。系统因此退化为存量估计，
> 并把置信度从 0.46 进一步降到 0.40，而不是输出一堆 0。
> 要观测真实增量，需要更长的采集间隔（建议 ≥1 周），或改用官方开放平台 API。

## 目录结构

```
market-compass/
├── apps/
│   ├── api/server.py                      # 标准库 HTTP 服务 + REST API
│   └── web/                               # 原生 HTML/CSS/JS 看板（无 CDN 依赖）
├── services/
│   ├── collector/
│   │   ├── seed_source.py                 # 演示数据源（本地合成）
│   │   ├── suning_search.py               # ✅ 真实数据源（苏宁公开搜索页）
│   │   ├── openapi_source.py              # ✅ 官方开放平台（淘宝/京东/拼多多）
│   │   └── raw_store.py                   # 原始层落盘（各适配器共用）
│   ├── etl/pipeline.py                    # 多源 ETL、同款对齐、SPS 指标（四种口径）
│   ├── analytics/
│   │   ├── queries.py                     # 看板查询、价格带、CR5/HHI、供需缺口
│   │   └── market_analysis.py             # 自由输入解析 + 行情数据罗列
│   └── ai/
│       ├── advisor.py                     # 检索 + 建议生成 + 证据链校验
│       └── llm_provider.py                # LLM 接口（默认离线模板）
├── config/openapi.env.example             # 凭据模板（真实凭据不入库）
├── infra/sql/schema.sql                   # 建表 + 轻量迁移
├── scripts/
│   ├── collect_suning.py                  # 苏宁采集入口
│   ├── setup_openapi.py                   # 官方 API 凭据配置向导
│   ├── check_openapi.py                   # 官方 API 配置自检（--live 真实调用）
│   ├── collect_openapi.py                 # 官方 API 采集入口
│   ├── bootstrap.py                       # 一键初始化（支持 --sources）
│   └── run_server.py                      # 启动服务
├── tests/
│   ├── smoke_test.py                      # 端到端冒烟测试（随数据源动态适配）
│   └── test_openapi.py                    # 开放平台适配器单元测试（18 项）
└── data/raw/{seed,suning,openapi_*}/      # 原始层（含 snapshots 归档）
```

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/meta` | 类目、平台、数据窗口、AI 模式 |
| GET | `/api/overview` | 大盘 KPI |
| GET | `/api/trend` | 日粒度销量代理趋势（含区间上下界） |
| GET | `/api/price-bands` | 价格带分布与占比 |
| GET | `/api/subcategories` | 细分市场排行（含供需缺口指数） |
| GET | `/api/products` | 商品排行（类目 / 关键词 / 排序） |
| GET | `/api/products/{id}` | 单品档案（指标序列、同款对比、评价、证据链） |
| GET | `/api/resolve?q=` | 自由输入解析：匹配标的、依据、匹配度、候选 |
| POST | `/api/market-analysis` | 商品行情分析：解析 + 数据罗列 + 报告 + 校验结果 |
| POST | `/api/advice` | 类目级 AI 选品建议 |
| GET | `/api/clusters` | 跨平台同款簇 |
| GET | `/api/audit` | 合规审计台账 |

`POST /api/market-analysis` 请求体：`{"query": "保温杯", "budget": 150, "risk": "medium", "goal": "行情分析"}`

## 接入更多真实数据源

只需在 `services/collector/` 下新增一个适配器，产出与 `data/raw/seed/*.jsonl` 相同格式的原始层文件，
下游 ETL、指标、AI 与看板**无需任何改动**。ETL 会自动发现 `data/raw/` 下所有含 `listings.jsonl` 的目录。

各平台实测可抓性（2026-10-15）：

| 平台 | robots.txt | 搜索页静态抓取 | 结论 |
|---|---|---|---|
| **苏宁** | 404（无规则） | ✅ 可解析 | **已接入** |
| 淘宝 / 唯品会 | ✅ 真实规则 `Disallow: /*?*` | — | **被 robots 明确禁止，不抓** |
| 京东 / 当当 | ⚠️ 被替换成首页 HTML | ❌ 空壳 / 重定向验证域 | 反爬有效，不抓 |
| 国美 | 404 | ❌ 连接失败 | 不可用 |

### 接入官方开放平台（拿到真实销量与价格）

公开页面拿不到真实销量与价格，官方开放平台可以，且完全合规。**不需要改代码**，三步：

```bash
python scripts/setup_openapi.py                 # 按提示粘贴 AppKey / AppSecret（输入不回显）
python scripts/check_openapi.py                 # 配置自检（不发请求）
python scripts/check_openapi.py --live          # 真实调用一次，验证凭据有效

python scripts/collect_openapi.py --provider taobao    # 采集
python scripts/bootstrap.py --sources openapi_taobao   # 入库 + 算指标
```

| 平台 | 申请入口 | 门槛 |
|---|---|---|
| 淘宝天猫 | https://open.taobao.com/ | 开发者认证，部分接口需应用审核 |
| 京东 | https://jos.jd.com/ | 企业资质，部分接口需签约 |
| 拼多多 | https://open.pinduoduo.com/ | 开发者认证，多多客类接口门槛较低 |

关键设计：
- 凭据只写在 `config/openapi.env`（已加入 `.gitignore`），向导与自检脚本都不会打印完整密钥；
- **没有凭据时不会崩溃**，而是返回缺失字段清单 + 申请入口 + 修复命令；
- 签名、公共参数、时间戳格式按平台差异封装（`sign_params` / `build_request` 是纯函数，有 18 项单元测试覆盖）；
- 响应解析用"候选字段名 + 自动定位列表"容错，字段对不上时只需改 `openapi_source.py` 顶部的 `*_FIELDS` 常量；
- 官方接口返回的是**滚动窗口销量**（如近 30 天），不是累计值，因此走 `api_volume_direct` 口径：
  直接作为规模值，不参与增量推算（避免把滚动值当累计值相减）。

安全提示：`--live` 会真实消耗接口配额；`--dry-run` 只打印请求（签名脱敏）。

配置真实模型（可选，仅用于把结论润色为自然语言，不参与数值生成）：

```bash
MARKETCOMPASS_LLM_BASE_URL=https://api.example.com/v1
MARKETCOMPASS_LLM_API_KEY=sk-xxx
MARKETCOMPASS_LLM_MODEL=deepseek-chat
```

## 文档

| 文档 | 内容 |
|---|---|
| [项目设计说明](docs/01-project-design.md) | 功能、架构、数据模型、AI 设计、合规、里程碑 |
| [进度存档](docs/02-progress-handoff.md) | 环境事实、数据源实测结论、关键口径、待办 |

## 合规声明

本项目只使用**公开可访问数据**与**平台官方授权接口**：遵守 robots.txt、限速采集、不采集个人信息、
不绕过任何风控与登录机制。演示源使用本地合成数据，页面已显著标注；真实源为苏宁公开搜索结果页，
采集行为全部登记在审计台账中。
