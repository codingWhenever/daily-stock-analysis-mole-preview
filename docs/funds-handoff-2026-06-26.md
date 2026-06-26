# 选基可信闭环交接文档

更新时间：2026-06-26

本文档用于把当前 `/funds` 公募基金模块的产品目标、已落地能力、验证证据、未完成边界和下一轮优先级交给后续接手者。它不替代完整规格和执行计划；权威规划仍以：

- `docs/funds-decision-foundation-spec.md`
- `docs/funds-execution-plan.md`

为准。

## 一句话交接

当前 `/funds` 已从“基金搜索和基金池展示”推进到“公开数据可解释、数据质量可追踪、费用/类型/回测有结构化底座、基金账本具备扩展画像、可导入用户确认后的持仓快照、可展示组合级持仓摘要、市场级榜单/荐基证据和个人动作 v2 预览”的阶段。它还不是完整投资决策系统：资讯佐证实接、账本交互增强、基金E账户校验、CSV/Excel/交易流水导入、真实平台买入/卖出笔数或金额榜、独立完整适当性问卷、组合级行业/主题暴露和账户历史回撤仍未完成。

接手时要把当前能力理解为“公开基金数据 + 本地基金池/账本 + 用户确认持仓快照 + 组合快照摘要 + 市场级公开证据 + 规则化个人动作预览”的阶段，而不是“已经能读取完整平台账户、交易流水、现金余额并自动给出最终投资指令”的阶段。`docs/funds-decision-foundation-spec.md` 中的完整独立用户画像、真实平台买入/卖出榜、市场风格轮动实接、资讯佐证、组合级行业/主题暴露和账户历史回撤仍是下一阶段蓝图，不能写入当前已完成清单。

## 当前产品目标

用户希望达到的最终形态是：

- 输入基金名称或代码，可以查到尽可能多的公开数据。
- 加入基金池后持续跟踪净值、收益、同类分位、回撤、波动、费用、交易限制、类型画像和回测校准。
- 根据基金类型、市场周期、近期行情、长期回测、费用和风险，给出可解释的买卖/定投/观望/减仓建议。
- 后续进一步支持更完整的真实持仓校验、账本/账户画像、市场热点、行业 Top 产品、真实平台买入/卖出/资金流榜单、个人持仓动作校准和闭环反馈。

当前实现不接个人平台账号，不读取完整交易流水或现金余额，不承诺收益；持仓能力仅来自用户上传截图/OCR 预览并确认后的当前快照，不能伪装成真实成本流水。

和完整规格的关系：

- 已实现主线：公开基金搜索、基金池、数据质量、类型画像、费用模型、NAV 回测、回测校准、规则信号、扩展账本画像、RapidOCR 持仓截图 OCR 预览/确认、OCR 字段级置信度、支付宝/京东金融/雪球样例解析、已确认持仓快照、组合级持仓摘要、金额闭眼模式、市场级公开榜单、行业热度/行业产品 Top10 代理榜、天天基金公开热销榜、公开买入热度榜、公开卖出压力榜、荐基证据卡、个人持仓动作 v2 和 `/funds` 工作台第一版收口。
- 仍是规划主线：独立完整用户画像问卷、组合级行业/主题暴露、用户级真实平台买入/卖出笔数或金额榜、资讯佐证实接、账本交互增强、基金E账户校验、CSV/Excel/交易流水导入、页面工作台持续打磨。
- 下一轮优先级应先继续做实回测/数据底座和真实市场上下文；资讯佐证、账本交互、基金E账户校验和独立画像问卷按后续切片推进。

## 运行状态

本地服务当前可按以下方式运行：

```bash
cd /Users/lee_oh/aiproject/CreativeProducts/daily_stock_analysis
.venv/bin/python main.py --serve-only --host 127.0.0.1 --port 8765
```

已验证入口：

- Web: `http://127.0.0.1:8765/funds`
- Health: `http://127.0.0.1:8765/api/health`
- API docs: `http://127.0.0.1:8765/docs`

注意：后端 Python 代码变更后需要重启服务；当前进程不会自动热加载 `fund_service.py` 等服务代码。

## 当前工作树状态

当前 `/funds` 相关功能已经分模块提交。最近关键提交包括：

- `275fb1c fix: improve funds page layout`
- `36e132a feat: add fund market industry rankings`
- `7e0b208 feat: expand fund ledger profile`
- `a4ee003 feat: add fund portfolio summary`
- `66a0d27 feat: add fund holding field confidence`
- `8445e63 feat: summarize fund holding import changes`

截至本次文档更新，功能代码已按模块提交；本地仍可能保留未跟踪验证产物：`apps/dsa-web/output/` 和 `docs/funds-uiux-review-2026-06-26.md`。它们是截图/评审证据，不应混入功能提交，除非后续明确要归档验收截图或 UI 评审稿。

## 已完成能力

### 1. 公募基金池 MVP

已支持：

- 搜索公募基金。
- 加入基金池。
- 刷新基金池。
- 移出基金池。
- 查询基金净值历史。
- 获取最近一次基金分析快照。
- 对单只基金运行 NAV walk-forward 回测。

主要 API：

```text
GET    /api/v1/funds/search
GET    /api/v1/funds/pool
POST   /api/v1/funds/pool
DELETE /api/v1/funds/pool/{code}
POST   /api/v1/funds/pool/refresh
POST   /api/v1/funds/{code}/refresh
GET    /api/v1/funds/{code}/analysis
GET    /api/v1/funds/{code}/nav
GET    /api/v1/funds/{code}/backtest
```

边界：

- 不接入支付宝、京东金融、雪球等个人账号。
- 不抓 Cookie，不模拟私有 App 接口。
- 公开数据源不可用或字段缺失时必须显示 partial/limited/estimated，不得显示为完整可用。

### 2. 数据质量体系 P0-1

已落地 `fund_data_quality_v1`，每次基金分析会输出：

- `overall_status`
- `quality_score`
- `dimensions`
- `warnings`
- `blocking_issues`

覆盖维度包括基础信息、最新净值、历史净值、收益榜单/同类分位、风险指标、交易规则/费率、持仓/报告/资讯佐证结构等。

重要边界：

- 缺失、估算、过期和未来日期会被降级。
- 未知报告日期不能当作有效 evidence。
- 数据质量不只是 `ok/partial`，新版细节在 `metrics.profile.data_quality_detail` 和 `metrics.data_quality_detail`。

### 3. 回测校准中心 P0-2

已新增 `fund_backtest_calibration_v1`，支持按基金池、账本、基金类型聚合单基金 NAV walk-forward 回测结果。

主要 API：

```text
GET /api/v1/funds/calibration/backtests
```

支持参数：

- `ledger_id`
- `fund_type`
- `codes`
- `lookback_days`
- `eval_window_days`
- `rebalance_interval_days`
- `initial_cash`

当前输出重点：

- 按 action 的命中率。
- 平均远期收益。
- 回撤暴露。
- 交易频率。
- 费用拖累。
- `calibration_status`: `insufficient` / `experimental` / `usable` / `strong`。

重要边界：

- 校准结果当前只作为上下文，不自动改信号阈值。
- `signal_context.backtest_calibration.applied_to_thresholds=false`。
- 样本不足、失败基金、筛选出范围基金不会污染聚合指标。

### 4. 基金信号闭环 v3 P0-3

当前信号模型版本：

```text
fund_signal_rule_v3_contextual
```

已将以下内容结构化进入 `signal_context`：

- 数据质量摘要。
- 基金类型指标摘要。
- 回测/校准摘要。
- 费用和交易约束。
- 决策检查项。
- 替代动作。
- 置信等级。
- 适用边界。

重要边界：

- 当前仍是规则引擎，不是 LLM 自由生成买卖建议。
- LLM 后续只能做解释和风险审阅，不能绕过规则和证据链直接下动作。
- 当前规则仍是初始参数，尚未进入按类型、市场周期和长期回测自动调参阶段。

### 5. 交易规则与费用 P1-1

已新增 `fund_fee_model_v1`，并进入分析、信号上下文和回测费用假设。

已支持：

- 申购费分档。
- 赎回费持有期分档。
- 管理费、托管费、销售服务费等运作费率的可解析项。
- 回测费用假设来源和边界。

当前策略：

- 申购回测费率优先用前端/最新 quote 的 front fee，否则用公开申购首档。
- 赎回回测费率使用公开赎回分档中的保守高值。
- 缺失费率时不伪造，标记 `fees_estimated`。

边界：

- 不接真实销售渠道优惠。
- 不接个人账户实际费率。
- 不接历史逐日费率。

### 6. 基金类型专属指标 P1-2

已新增：

```text
fund_metric_profile_v1
```

覆盖类型：

- 主动权益 / 混合。
- 货币基金。
- 债券基金。
- 指数 / ETF / ETF 联接。
- QDII。
- FOF。

已输出：

- `metric_profile`
- `type_specific_metrics`
- `primary_metrics`
- `missing_specialized_metrics`
- `not_applicable_metrics`
- `limitations`

重要边界：

- 不再用同一套股票型指标评价所有基金。
- 货币基金在七日年化、万份收益、规模/流动性未接入前保持 `watch`。
- 类型指标缺口进入 `strategy_readiness.missing_specialized_metrics` 和 `signal_context.metric_profile`，但当前不改写评分阈值。

### 7. 基金账本与扩展账户画像 P2-1

已完成后端和 `/funds` 表单第一版。

账本字段：

- `account_type`
- `purpose`
- `risk_target`
- `investment_horizon`
- `rebalance_frequency`
- `drawdown_tolerance`
- `liquidity_need`
- `investment_experience`
- `monthly_budget`
- `cash_reserve_months`
- `preferred_fund_types`
- `notes`

主要 API：

```text
POST  /api/v1/funds/ledgers
PATCH /api/v1/funds/ledgers/{ledger_id}
PATCH /api/v1/funds/pool/{code}/ledger
```

已支持：

- 创建账本时写入轻量账户画像。
- 更新账本画像，可选更新 `name` / `color`。
- `list_pool` 返回 `ledgers`，每个 ledger 带画像字段和 `fund_count`。
- 基金池条目可手动归属到账本。
- 个人动作 v2 会读取回撤承受、流动性、投资经验、月度预算、现金安全垫和偏好类型，用于目标仓位和建议金额区间约束。
- 旧 SQLite 缺 `fund_pool_items.ledger_id` 或 `fund_ledgers` 画像列时会幂等补列。
- 迁移检查或 `ALTER TABLE` 失败时 fail-fast，不静默带病启动。
- active/inactive 同名账本都拒绝重复创建或重命名为同名，避免误覆盖旧账本画像。

未做：

- 个人平台账号。
- 独立完整适当性问卷和问卷评分。
- 手工加减持、买入日期、交易流水和现金余额。
- 账户历史收益率、历史回撤、行业/主题暴露和重仓穿透。
- 账本删除/归档、排序、批量移动、主题色预设和完整前端交互增强。

### 8. 持仓导入、字段置信度和组合摘要

已完成第一版：

- `/api/v1/funds/holding-imports/preview` 支持截图上传后直接触发 RapidOCR，也保留粘贴 OCR 文本降级路径。
- `/api/v1/funds/holding-imports/confirm` 只写入用户确认或编辑后的 canonical 当前快照，不长期保存原图和原始 OCR 文本。
- `FundHoldingCandidate.field_confidence` 已覆盖 `code`、`name`、`market_value`、`units`、`cost_amount`、`pnl_amount`、`pnl_pct`、`latest_nav` 等核心字段。
- 支持支付宝、京东金融和雪球列表截图专项解析；无基金代码的列表会按基金名称反查代码，并给出中低置信度提示。
- 持仓收益率校验通过时，可由市值与持仓收益反推成本；截图未展示份额时，可用公开单位净值反推份额和净值字段。
- 再次确认导入时返回 `change_summary`，包含新增、更新、移除和关键字段变化摘要。
- `/api/v1/funds/holdings` 返回 `portfolio_summary`，包括总市值、总成本、总盈亏、集中度、前几大持仓、平台/账本分布、字段覆盖率、风险分、风险等级和风险原因。
- `/funds` 已确认持仓区默认闭眼展示金额/仓位，可手动打开。

重要边界：

- 当前快照不是完整交易流水，不代表真实历史成本或历史收益率。
- 成本、份额和净值的反推字段会降低字段级置信度，用户确认或编辑后的值才进入 canonical 快照。
- 组合摘要是当前持仓快照口径，风险分只使用当前确认市值、集中度、产品数量、平台集中和字段覆盖率，不包含账户历史回撤、现金余额、历史申赎和行业/主题穿透。

### 9. 市场级榜单、行业代理榜和荐基证据

已完成第一版：

- `/api/v1/funds/market-rankings` 返回 `market_fund_ranking_v1`。
- 已有市场级公开组：ETF 主力净流入、ETF 主力净流出、ETF 成交热度、开放式基金收益实证。
- 已接入 `platform_public_buy_rank`，来源为天天基金移动端公开热销排行 `eastmoney.fundmobapi.FundMNRank`，用于展示平台公开购买热度。
- 已派生 `industry_heat_top10`、`industry_product_top10`、`public_buy_proxy_rank`、`public_sell_proxy_rank`。
- `recommendation_candidates` 会引用行业产品 Top10 和公开买入代理榜，进入 `/api/v1/funds/recommendations/today` 的市场级荐基证据卡。
- `/funds` 页面明确区分市场级榜单/荐基证据和个人持仓动作。

重要边界：

- `platform_public_buy_rank` 和 `public_buy_proxy_rank` 的买入侧已优先使用天天基金公开热销排行，但它仍是平台公开销售热度，不是用户级真实买入流水或申购金额。
- `public_sell_proxy_rank` 仍是 ETF 净流出压力代理；当前没有公开可验证的用户级真实卖出笔数或赎回金额榜。
- 市场级榜单前期完全脱离用户画像和个人持仓，只能作为具体产品推荐的公开证据，不是个人买卖指令。
- 行业和主题识别当前基于基金名称/类型/公开榜单字段推断，尚未完成基金定期报告持仓穿透和行业暴露精算。

## 已明确暂缓

### 资讯佐证实接 P1-3

本轮按用户要求暂缓。代码里存在 `research_evidence`、`market_context`、基金报告/持仓/资讯相关结构和收集逻辑，但不能宣称已完成“资讯佐证实接”。

后续完成条件应至少包括：

- evidence 按 `fund_report` / `holding_news` / `industry_news` / `market_event` 分类。
- 每条 evidence 有来源、时间、关联标的/行业、正负面或风险标签。
- 可追溯链接或报告 ID。
- 无法抓取时明确 fail-open。
- UI 上不能把空结构展示成已接入。

### 账本交互增强 P2-2

本轮按用户要求暂缓。当前已有基础账本分类切换和后端画像接口，但不是完整账户交互。

后续完成条件应至少包括：

- 重命名。
- 删除/归档。
- 批量移动基金。
- 账本排序。
- 主题色预设。
- 空态。
- 移动端不横向溢出。
- 按账本展示账户画像和后续持仓摘要。

## 完整规格中的未实现蓝图

`docs/funds-decision-foundation-spec.md` 规划了更完整的基金决策系统。以下内容需要按“已落地第一版”和“仍未落地”区分，不能把 v1 能力说成完整能力，也不能把仍未完成项写成已完成。

已落地第一版但仍需增强：

- RapidOCR 本地图片 OCR 预览。
- 支付宝、京东金融、雪球真实截图样例解析。
- 雪球无代码列表截图解析和基金名称反查。
- OCR 字段级置信度。
- 用户确认/编辑 OCR 候选后写入当前持仓快照。
- 再次导入时返回字段差异和新增/更新/移除摘要。
- 各平台默认账本；全部视图按基金代码聚合，各账本/平台保留独立明细。
- 组合级当前持仓摘要，包括集中度、平台/账本分布和字段覆盖率。
- `/funds` 持仓和个人动作金额默认闭眼，可手动打开。
- 市场级公开榜单、行业热度 Top10、行业产品 Top10、天天基金公开热销榜、公开买入热度榜、卖出压力代理榜和荐基证据卡。
- 账本画像扩展字段。
- 个人持仓动作 v2 预览。
- `/funds` 工作台第一版和个人动作摘要收口。

仍未落地或未完整验证：

- 基金E账户校验源。
- CSV / Excel / 账单 / 交易流水导入。
- 平台账号直连、真实交易流水、现金余额和真实平台费率。
- 组合层行业/主题暴露、重仓穿透和历史回撤。
- 账本排序、重命名、删除/归档、批量移动等完整交互。

画像和个人持仓动作：

- 独立完整用户画像/适当性问卷和评分。
- 当前扩展账本画像已进入个人动作，但仍需更完整的风险承受能力、财务状况、投资经验和产品适配问卷。
- 将真实现金余额、真实可用申购预算和平台持仓分布作为买入/减仓硬约束。
- 接入用户现金余额或可用申购预算。
- 对个人动作金额区间做回测校准和后验评估。

荐基和市场榜单：

- 今日荐基已具备市场级证据卡 v1，行业热度 Top10 和行业产品 Top10 已有代理版，但尚未形成基于真实行业配置、估值和风格轮动的完整荐基工作流。
- 用户级真实平台买入笔数、卖出笔数、申购金额、赎回金额榜。
- 市场级榜单只汇总公开客观交易、资金流和平台热度数据，不依赖用户画像或个人持仓。
- 市场级榜单是推荐具体产品的前期数据实证，不等同于个人买入/卖出建议。

市场与闭环：

- 市场热点、ETF 资金流、风格轮动和估值分位实接。
- 按市场阶段和基金类型自动校准策略阈值。
- 用户反馈与后验评估闭环。
- `/funds` 工作台仍需继续打磨“今日决策 / 我的持仓 / 荐基 / 基金池 / 导入与数据 / 用户画像”的信息架构和关键交互。

## 数据真实性与产品文案边界

接手者必须保持以下原则：

- 真实抓取、公开平台直出、本地估算、缺失和过期必须分开标注。
- 回撤、波动、夏普等指标若来自本地净值估算，要明确是 `nav_calculation`，不能说成平台直出。
- 阶段收益和同类分位如果来自公开榜单字段，可以展示为公开直出，但要保留来源和日期。
- 资讯结构存在不等于资讯已接通。
- 市场上下文代理存在不等于指数估值/资金流/风格轮动已完整接入。
- 买卖建议必须说明它是规则引擎输出，并带数据质量、回测校准、费用和适用边界。
- 不要把用户确认后的截图持仓快照说成完整平台账户或真实交易流水。
- 不要把市场级荐基证据卡说成因人而异的买入/卖出指令。
- 不要把行业/卖出压力代理榜说成真实行业配置穿透或用户级真实平台卖出笔数；平台公开热销榜只能说成公开购买热度，不能说成用户级买入流水或申购金额；也不要把独立完整用户画像和资讯佐证说成已完成。

## 当前已实现 API 与规划 API 边界

当前代码中已实现的 `/api/v1/funds` 路径是：

```text
GET    /api/v1/funds/search
GET    /api/v1/funds/pool
POST   /api/v1/funds/ledgers
PATCH  /api/v1/funds/ledgers/{ledger_id}
POST   /api/v1/funds/pool
DELETE /api/v1/funds/pool/{code}
PATCH  /api/v1/funds/pool/{code}/ledger
POST   /api/v1/funds/pool/refresh
GET    /api/v1/funds/calibration/backtests
GET    /api/v1/funds/market-rankings
POST   /api/v1/funds/holding-imports/preview
POST   /api/v1/funds/holding-imports/confirm
GET    /api/v1/funds/holdings
GET    /api/v1/funds/recommendations/today
GET    /api/v1/funds/personal-actions
POST   /api/v1/funds/{code}/refresh
GET    /api/v1/funds/{code}/backtest
GET    /api/v1/funds/{code}/analysis
GET    /api/v1/funds/{code}/nav
```

以下是 `docs/funds-decision-foundation-spec.md` 的规划 API，目前没有实现，接手者不要在联调或产品文案中当作可用：

```text
POST  /api/v1/funds/holding-imports/parse
POST  /api/v1/funds/holding-imports/commit
GET   /api/v1/funds/holding-imports/{batch_id}
PATCH /api/v1/funds/holdings/{holding_id}
POST  /api/v1/funds/investor-profile/evaluate
GET   /api/v1/funds/recommendations/industries
GET   /api/v1/funds/recommendations/action-rankings
GET   /api/v1/funds/privacy-preferences
PATCH /api/v1/funds/privacy-preferences
```

## 当前版本和 Schema 锚点

接手者核对字段时优先看 `src/services/fund_service.py`、`src/services/fund_backtest_calibration.py` 和 `api/v1/schemas/funds.py`，当前已落地的关键版本名是：

| 名称 | 当前值 | 用途 |
| --- | --- | --- |
| `FUND_PROFILE_SCHEMA_VERSION` | `fund_profile_v2` | 基金画像结构 |
| `FUND_METRIC_PROFILE_SCHEMA_VERSION` | `fund_metric_profile_v1` | 分类型指标画像 |
| `FUND_DATA_QUALITY_SCHEMA_VERSION` | `fund_data_quality_v1` | 数据质量明细 |
| `FUND_SIGNAL_MODEL_VERSION` | `fund_signal_rule_v3_contextual` | 规则化信号模型 |
| `MARKET_CONTEXT_SCHEMA_VERSION` | `fund_market_context_v1` | 市场上下文结构 |
| `FUND_BACKTEST_ENGINE_VERSION` | `fund_nav_walk_forward_v1` | 单基金 NAV walk-forward 回测 |
| `FundBacktestCalibrationResponse.schema_version` | `fund_backtest_calibration_v1` | 回测校准中心响应 |
| `FundMarketRankingsResponse.schema_version` | `market_fund_ranking_v1` | 市场级公开榜单响应 |
| `FUND_HOLDING_PREVIEW_SCHEMA_VERSION` | `fund_holding_import_preview_v1` | 持仓导入预览 |
| `FUND_HOLDING_CONFIRM_SCHEMA_VERSION` | `fund_holding_confirm_v1` | 持仓导入确认 |
| `FUND_HOLDING_SNAPSHOT_SCHEMA_VERSION` | `fund_holding_snapshot_v1` | 已确认持仓快照 |
| `FUND_RECOMMENDATION_TODAY_SCHEMA_VERSION` | `fund_recommendation_today_v1` | 今日市场级荐基证据卡 |
| `FUND_PERSONAL_ACTIONS_SCHEMA_VERSION` | `fund_personal_actions_v2` | 个人持仓动作建议 |
| `FUND_PERSONAL_ACTION_MODEL_VERSION` | `fund_personal_action_model_v2` | 个人动作评分/金额区间模型 |
| `signal_context.schema_version` | `fund_signal_context_v3` | 信号上下文结构 |
| `trading_rules.fee_model.schema_version` | `fund_fee_model_v1` | 交易规则与费用模型 |

不要把 `docs/funds-decision-foundation-spec.md` 中的未来 API 和未来 schema 草案加入当前实现说明，除非对应代码、schema、测试和 UI 已经落地。

## 验证证据

以下是 2026-06-26 最近一轮验证证据；后续如果继续改代码或 UI，需要重新跑对应验证。

最近一轮后端编译验证：

```bash
.venv/bin/python -m py_compile \
  src/storage.py \
  src/repositories/fund_repo.py \
  src/services/fund_service.py \
  api/v1/schemas/funds.py \
  api/v1/endpoints/funds.py \
  tests/test_fund_service.py
```

结果：通过。

本轮持仓导入、个人动作和前端回归还验证了：

```bash
PYTHONPATH=. .venv/bin/python tests/test_fund_holding_import_service.py
PYTHONPATH=. .venv/bin/python tests/test_fund_personal_action_service.py
PYTHONPATH=. .venv/bin/python tests/test_fund_market_ranking_service.py
PYTHONPATH=. .venv/bin/python tests/test_fund_recommendation_service.py
PYTHONPATH=. .venv/bin/python -m py_compile \
  src/services/fund_holding_import_service.py \
  src/services/fund_market_ranking_service.py \
  src/services/fund_personal_action_service.py \
  api/v1/schemas/funds.py \
  tests/test_fund_holding_import_service.py \
  tests/test_fund_market_ranking_service.py \
  tests/test_fund_recommendation_service.py \
  tests/test_fund_personal_action_service.py
cd apps/dsa-web && npm run lint
cd apps/dsa-web && npm run build
git diff --check
```

结果：通过。`npm run lint` 仍有既有 warning：`apps/dsa-web/src/pages/SettingsPage.tsx:348` 的 `react-hooks/exhaustive-deps`，本轮未改。

真实截图 OCR 验证：

- 支付宝真实截图 1 张：识别出 `014320`、`002112`、`007872`、`007474`，用于验证支付宝列表专项布局解析。
- 京东金融真实截图 1 张：识别出 `501018`、`270042`，可补市值、收益、收益率，并通过公开净值反推份额/最新净值。
- 雪球真实截图 5 张：识别出 29 条候选，`empty_code_count=0`；已验证关键名称反查如 `006327`、`000934`、`519191`、`166019`、`163407`。

真实公开榜单验证：

- `platform_public_buy_rank` 真实 provider 可返回天天基金公开热销榜，样例包括 `000067`、`000042`、`000057`，`evidence_metrics.availability=platform_public_rank_only`。
- `public_buy_proxy_rank` 当前优先复用天天基金公开热销榜；`public_sell_proxy_rank` 仍来自 ETF 净流出压力代理。

当前 `.venv` 没有安装 `pytest`，因此最近一轮不是通过 `pytest` runner，而是使用直接 import 并执行 `tests/test_fund_service.py` 全部 `test_*` 函数的小脚本验证：

```text
TOTAL 32 PASS
```

说明：其中 fail-fast 迁移测试会故意打印 `failed to inspect fund pool columns` 和 `failed to add fund_ledgers.account_type` 的异常日志，这是预期行为，测试断言的是异常被抛出而不是静默吞掉。

最近一轮前端验证：

```bash
cd apps/dsa-web
npm run lint
npm run build
```

结果：

- `npm run build` 通过。
- `npm run lint` 无 error，仅有既有 warning：`apps/dsa-web/src/pages/SettingsPage.tsx` 的 `status` hook dependency。

接口验证：

```text
GET /api/health -> {"status":"ok", ...}
GET /api/v1/funds/pool -> 正常返回 items / ledgers
```

`ledgers` 返回字段已包含：

- `account_type`
- `purpose`
- `risk_target`
- `investment_horizon`
- `rebalance_frequency`
- `drawdown_tolerance`
- `liquidity_need`
- `investment_experience`
- `monthly_budget`
- `cash_reserve_months`
- `preferred_fund_types`
- `notes`
- `fund_count`

额外用 FastAPI `TestClient` + 临时 SQLite 文件验证：

- `POST /api/v1/funds/ledgers` 创建账本画像。
- 同名账本返回 400。
- `PATCH` 只传一个字段不会清空未传字段。
- `PATCH` 传 `null` 或空字符串可清空对应画像字段。
- `GET /pool` 可回读画像字段。

结果：

```text
PASS: ledger API contract
```

未覆盖或需要补充：

- 没有运行标准 `pytest` 命令；当前环境按历史边界使用直接执行 `test_*` 文件验证。
- 基金E账户校验源、CSV/Excel/交易流水导入、独立完整用户画像问卷、用户级真实平台买入/卖出笔数或金额、资讯佐证、组合级行业/主题暴露和历史回撤仍未验证。
- 行业热度 Top10、行业产品 Top10、公开买入热度榜和卖出压力榜当前是公开市场/平台代理口径，已测结构和排序，不等于用户级真实平台交易榜。
- 如果下一轮继续改页面、金额闭眼、荐基或导入助手 UI，需要补最新 `/funds` 桌面和移动端截图验收。

## 测试覆盖重点

当前 `tests/test_fund_service.py` 覆盖了：

- 基金分析快照结构。
- 数据质量维度、过期、未来日期、未知报告日期降级。
- 基金类型指标画像。
- 交易规则和费用模型。
- 信号上下文 v3。
- 账本创建、归属、画像更新、默认账本画像。
- 旧 SQLite `fund_ledgers` 画像列迁移。
- 旧 SQLite `fund_pool_items.ledger_id` 迁移。
- 迁移 inspect/ALTER fail-fast。
- 重名账本 active/inactive 创建拒绝。
- 重命名撞 active/inactive 同名拒绝。
- 单基金 backtest。
- 回测校准中心聚合、过滤、失败样本、样本不足。
- 扩展账本画像字段的创建、更新、迁移和个人动作约束读取。

当前 `tests/test_fund_holding_import_service.py` 覆盖了：

- OCR 文本/图片预览候选。
- 支付宝、京东金融、雪球样例解析。
- 字段级置信度。
- 成本、份额和净值补全/反推。
- 用户确认写入快照和再次导入差异摘要。
- `portfolio_summary` 的市值、盈亏、集中度、平台/账本分布、字段覆盖率、风险分和风险等级。

当前 `tests/test_fund_market_ranking_service.py` 和 `tests/test_fund_recommendation_service.py` 覆盖了：

- 市场级公开榜单基础分组。
- `platform_public_buy_rank`、`industry_heat_top10`、`industry_product_top10`、`public_buy_proxy_rank`、`public_sell_proxy_rank`。
- 榜单代理口径的 status / limitations / proxy fields。
- 今日荐基候选引用行业产品和公开买入代理证据。

当前验证不要写成标准 `pytest` 全量结果；本轮采用直接执行相关 `test_*` 文件和前端 lint/build 的边界。

## 下一轮建议优先级

### 优先级 1：回测做实做牢靠

目标：让当前规则引擎从“初始参数”走向“可被历史样本校准”。

建议任务：

- 增加更多基金池样本和不同类型样本。
- 将校准结果持久化为快照，避免每次临时重算。
- 补充同类中位、参考指数、定投基准。
- 扩展费用、确认日、限购、交易日假设。
- 输出参数版本和校准版本。
- 仍然禁止未来数据。
- 在样本达到门槛前保持 `applied_to_thresholds=false`。

验收：

- 可解释为什么某类基金动作阈值没有被应用或已经被应用。
- 可以比较规则策略 vs 买入持有 vs 定投 vs 同类中位。
- 每个 action 有样本数、命中率、收益/回撤统计和费用拖累。

### 优先级 2：市场指数、估值、风格轮动实接

目标：把市场上下文从代理结构推进到真实可用 evidence。

建议任务：

- 明确可用的公开指数估值数据源。
- 接入宽基、行业、主题指数趋势和估值分位。
- 接入成长/价值、大盘/小盘、红利/科技等风格轮动指标。
- 为 QDII 增加海外市场延迟、汇率、海外指数上下文。
- 数据不可用时保持 fail-open 和明确缺口。

验收：

- `market_context` 中能清楚区分真实指数/估值/风格数据与代理指标。
- UI 不再把缺口写成已接入。

### 优先级 3：`/funds` 工作台 UI/UX 继续打磨

第一版工作台已做市场榜单、荐基证据、持仓导入、个人动作和基金池的分区收口，并限制了个人动作默认展开数量。下一轮仍应与回测和市场上下文并行推进，重点是信息架构深化、筛选分页和移动端数据表体验。

建议任务：

- 继续打磨今日决策、我的持仓、荐基、基金池、导入与数据、用户画像的信息架构。
- 明确市场级榜单、推荐候选和个人持仓动作建议的视觉分层。
- 为每块数据定义 `已实接 / 计算中 / 待接入 / 需用户确认` 状态。
- 为持仓明细和个人动作增加筛选、分页或抽屉详情，避免移动端过长。
- 每轮 UI 变更补桌面和移动端截图验收。
- 确保无持仓时不展示个人动作，只展示市场级榜单和推荐候选。

验收：

- 第一屏能说明“今天市场上值得看什么”和“我的持仓是否需要动作”两个问题，但两者不混淆。
- 市场级榜单标注数据来源、时间、口径和单位。
- 个人持仓动作区域在缺少画像或持仓时明确显示未启用原因。

### 优先级 4：资讯佐证实接

用户已明确这轮暂缓，后续可以作为单独任务推进。

建议任务：

- 复用现有 intelligence sources。
- 将基金报告、重仓股公告/财报、行业新闻、市场事件分桶。
- 给 evidence 增加来源、时间、关联关系、情绪/风险标签和链接。
- 在基金详情中以“佐证/反证”呈现，而不是堆新闻。

### 优先级 5：账本交互增强

用户已明确这轮暂缓，后续可以作为前端/少量 API 任务推进。

建议任务：

- 基于已有后端账本画像补 UI。
- 账本重命名、归档、排序、主题色预设。
- 批量移动基金。
- 移动端检查按钮挤压和文本溢出。
- 空账本和默认账本的状态设计。

### 优先级 6：持仓导入增强和用户画像

这是完整决策系统的关键。当前已完成持仓截图 OCR/确认/快照 v1、字段级置信度、支付宝/京东金融/雪球样例和组合快照摘要，下一步应围绕校验源、更多样本、差异复核体验和独立画像问卷继续增强，而不是重新设计一套导入链路。

建议任务：

- 增加基金E账户作为全量校验源。
- 增加更多支付宝、京东金融、雪球真实样本回归，覆盖不同字体、长截图和持仓为空场景。
- 将字段级置信度和再次导入差异摘要做成更明确的复核交互，关键字段冲突时提示用户确认。
- 完整用户画像/适当性问卷作为硬约束进入个人动作层。
- 增加 CSV/Excel/交易流水导入时，必须和当前快照语义分开，不写成 OCR 快照。

## 审查建议

指定审查者应重点检查：

- 本文是否和 `docs/funds-decision-foundation-spec.md`、`docs/funds-execution-plan.md` 一致。
- 是否有把暂缓项写成已完成的过度声明。
- API 路径和字段名称是否准确。
- 验证证据是否和当前代码真实状态一致。
- 下一轮优先级是否符合“先数据和回测，后资讯和交互”的用户口径。
- 是否还需要补充 UI 截图验收、运行命令或数据源边界。

## 交接风险

- 功能代码已按模块提交；后续 agent 仍不应执行 destructive git 操作，避免丢失本地截图/评审产物。
- 当前未跟踪 `apps/dsa-web/output/` 和 `docs/funds-uiux-review-2026-06-26.md` 属于本地验证/评审证据，除非明确归档，否则不要混入功能提交。
- 前端 lint/build 已通过，但如果继续改 UI，需要重新做桌面和移动端截图检查。
- 当前数据源为公开接口和本地计算混合，不要在文案中写成支付宝同等数据覆盖。
- 回测校准当前仍是研究/可信度上下文，不是自动交易策略。
