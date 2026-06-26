# 选基可信闭环执行计划

更新时间：2026-06-26

本计划用于把当前选基能力从“可展示公开基金数据”推进到“数据可解释、回测可校准、建议可追踪”的可信投资分析工具。执行顺序按依赖关系排列：先证明数据，再验证策略，再生成建议，最后完善账户和交互。

## P0-1 数据质量体系硬化

Subagent：基金数据可靠性工程师

目标：
- 给每次基金分析生成稳定的数据质量结构，明确字段是真实抓取、平台直出、本地估算、缺失还是过期。
- 不再只用 `ok/partial` 粗标签表达可信度。

范围：
- 后端质量结构与测试优先。
- 主要文件：`src/services/fund_service.py`、`api/v1/schemas/funds.py`、`tests/test_fund_service.py`。

验收：
- 每只基金输出 `overall_status`、`quality_score`、`dimensions`、`warnings`、`blocking_issues`。
- 覆盖基础信息、最新净值、历史净值、收益榜单/同类分位、风险指标、交易规则/费率、持仓/行业/报告/资讯佐证。
- 缺失、估算、过期不能显示为完整可用。

状态：已实现并通过规格审查、代码质量审查。

## P0-2 回测校准中心

Subagent：量化回测工程师

目标：
- 把单基金 NAV 回测升级为可批量校准的策略验证层。
- 用历史信号结果反向标注当前规则是否可信，而不是只展示一次回测收益。

范围：
- 优先新增独立回测校准模块，减少和信号主逻辑耦合。
- 重点支持按基金、账本、基金类型聚合。

验收：
- 输出按 action 的命中率、平均远期收益、回撤暴露、交易频率、费用拖累。
- 给出 `calibration_status`：insufficient / experimental / usable / strong。
- 不使用未来数据；说明训练/评估窗口。

状态：已实现第一版，并通过规格审查、代码质量审查和运行时接口回归。当前提供 `fund_backtest_calibration_v1`，支持按基金池、账本和基金类型聚合 action 命中率、远期收益、回撤暴露、交易频率和费用拖累；校准结果只作为可信度上下文，不自动改写信号阈值。

## P0-3 基金信号闭环 v3

Subagent：决策引擎工程师

目标：
- 让买入/定投/观望/减仓/赎回建议引用数据质量、回测校准、基金类型、市场状态和费用影响。
- 将规则版本、证据、限制条件结构化，后续可追踪和调参。

范围：
- 信号生成和解释结构。
- 不做 LLM 自由生成买卖建议，LLM 仅可做解释和风险审阅。

验收：
- `signal_context` 包含规则版本、参数版本、数据质量摘要、回测校准摘要、费用影响、适用边界。
- 建议必须能解释“为什么不是另一个动作”。

状态：第一版已落地，并通过规格审查、代码质量审查。当前 `fund_signal_rule_v3_contextual` 仍由规则引擎决定动作，`signal_context` 补充 data_quality、calibration/backtest_calibration、execution_constraints、decision_checks、alternative_actions、confidence_level 和 boundaries；P0-2 校准只作为上下文引用，`applied_to_thresholds=false`，不自动改阈值。

## P1-1 交易规则与费用精细化

Subagent：基金交易规则工程师

目标：
- 把公开申购、赎回、持有期费率、确认日、状态限制接到分析和回测里。
- 让建议从“收益好不好”升级到“执行成本和交易约束是否值得”。

范围：
- 交易规则结构、费率解析、费用模型、回测接入。

验收：
- 支持申购费、赎回费分段、管理/托管/销售服务费展示。
- 回测费用假设能说明来源和保守/估算边界。

状态：第一版已落地，并通过规格审查、代码质量审查。`trading_rules.fee_model` 保留公开申购金额分档、赎回持有期分档，并为回测给出申购 `selected_rate_pct` 与赎回 `conservative_rate_pct`；`execution_constraints.fee_model_summary` 标明 tiers 可用性、`fees_estimated`、回测采用档位和 policy。若 provider 返回可解析的运作费率，管理费、托管费、销售服务费进入 `annual_expense`；未返回时不伪造。当前仍不接真实账户、真实销售渠道优惠或历史逐日费率。

## P1-2 基金类型专属指标

Subagent：基金分类画像工程师

目标：
- 不同基金类型使用不同核心指标，不再用同一套股票型指标评价所有基金。

范围：
- 股票/混合、债券、货币、指数、QDII、FOF、ETF/联接的差异化指标。

验收：
- 每类基金有 `metric_profile` 和适用/不适用说明。
- 货币基金关注七日年化/万份收益，债基关注久期/信用/回撤，指数基金关注跟踪误差和指数估值，QDII 标注汇率/海外市场延迟。

状态：第一版已落地，并通过规格审查、代码质量审查。`profile.metric_profile` / `profile.type_specific_metrics` 按 `strategy_family` 输出核心指标、适用性、不适用的主动权益指标、专项缺口和解释边界；已覆盖 `money_market`、`bond_income`、`index_beta`/ETF 联接、`qdii_global`、`fof_allocation`、`active_equity`/mixed。`strategy_readiness.missing_specialized_metrics` 和 `signal_context.metric_profile` 会引用专项缺口，但当前不改写信号评分阈值；货币基金在七日年化、万份收益、规模/流动性未接入前保持 `watch`。本轮不接资讯佐证实接，不做账本交互完善。

## P1-3 资讯佐证实接

状态：本轮按用户要求暂缓，不作为当前落地队列；已有结构保留，不宣称实接完成。

Subagent：投研证据工程师

目标：
- 把行业新闻、基金报告、重仓股财报/公告和市场事件作为建议佐证，而不是只留空结构。

范围：
- 优先复用现有 intelligence sources 和基金报告/持仓数据。
- 资讯仅作 evidence，不替代净值和回测。

验收：
- evidence 按 fund_report / holding_news / industry_news / market_event 分类。
- 每条 evidence 有来源、时间、关联标的/行业、正负面或风险标签。
- 无法抓取时明确 fail-open。

## P2-1 账本账户化

Subagent：组合账户工程师

目标：
- 当前账本是分类；下一步支持可选账户语义：目标、风险偏好、资金用途、持仓/成本手录。

范围：
- 本轮只做轻量本地账户画像与兼容迁移，不接个人账号、不做持仓手录明细。

验收：
- 账本支持 `account_type`、`purpose`、`risk_target`、`investment_horizon`、`rebalance_frequency`、`notes` 本地画像字段。
- `POST /api/v1/funds/ledgers`、`PATCH /api/v1/funds/ledgers/{ledger_id}`、`list_pool` 能稳定读写/返回上述字段。
- 旧 SQLite 库缺列时可幂等补列；补列检查或 `ALTER TABLE` 失败时直接 fail-fast，不静默带病启动。
- 同名账本无论 active/inactive 都拒绝重复创建或重命名为同名。

状态：第一版后端轻量账户画像已落地，并通过规格复审、代码质量复审和接口级临时库验证。当前验收口径只覆盖后端轻量账户画像、PATCH/API/list_pool 返回、同名账本防覆盖和旧 SQLite 幂等迁移；份额/成本/买入日期录入、账户级收益/回撤/集中度计算仍留在后续阶段，不算本轮 P2-1 done。

## P2-2 账本交互完善

状态：本轮按用户要求暂缓，不作为当前落地队列；现有账本分类切换继续保留。

Subagent：产品交互设计工程师

目标：
- 让账本切换、批量归类、主题色、空态和移动端体验更像一个长期使用的基金工作台。

范围：
- 主要前端，少量 API 可配合。

验收：
- 支持重命名、删除/归档、批量移动、账本排序、主题色预设。
- 移动端不横向溢出，按钮不挤压基金名。

## 执行节奏

1. P0-1 完成后，先做 spec compliance review，再做 code quality review。
2. P0-1 通过后派发 P0-2；P0-2 不通过时不推进 P0-3。
3. 本轮跳过资讯佐证实接和账本交互完善，避免把“结构存在”误说成“实接完成”。
4. P1 任务在 P0 数据结构稳定后并行拆小块，但实现代理仍按文件边界逐个合入。
5. 每轮都跑后端 py_compile、相关 pytest、前端 lint/build，以及 `/funds` 桌面和移动端截图检查。

## 下一轮路线修订

本计划上方的 P0-1 到 P2-2 记录的是当前已实施和已评审过的工程切片。下一轮执行需与 `docs/funds-product-review-2026-06-26.md` 和 `docs/funds-decision-foundation-spec.md` 的最新评审口径对齐：

1. 先收口当前已实现边界，确保公开基金数据、基金池/账本、数据质量、回测、费用和类型画像不被写成真实个人持仓能力。
2. P1 数据底座/回测、P2 市场上下文和 `/funds` 工作台 UI/UX 设计并行推进。
3. 市场级买入榜、卖出榜、资金流向榜前期完全脱离用户画像和持仓，只汇总公开客观交易、资金流、成交热度和平台热度数据。
4. 市场级榜单是推荐具体产品的前期数据实证，不是个人买入/卖出动作。
5. 个人持仓动作建议只有在用户画像和已确认持仓同时存在后才输出；无持仓时 UI 只展示市场级榜单、推荐候选和未启用原因。
6. 持仓导入走 OCR 图片导入主路径，RapidOCR + 用户确认/编辑为入库前置条件。
7. UI/UX 改版是重要关注点，应先设计工作台信息架构和关键交互，再按功能契约分步落地。
