import type React from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowUpRight,
  BarChart3,
  AlertTriangle,
  CheckCircle2,
  Database,
  GitBranch,
  Layers3,
  LineChart,
  ListPlus,
  RefreshCw,
  Search as SearchIcon,
  ShieldAlert,
  Sparkles,
  Target,
  Trash2,
  TrendingUp,
} from 'lucide-react';
import {
  fundsApi,
  type FundAnalysisSnapshot,
  type FundBacktestResponse,
  type FundLedger,
  type FundMarketRankingItem,
  type FundMarketRankingsResponse,
  type FundPersonalActionsResponse,
  type FundPoolItem,
  type FundRecommendationCandidate,
  type FundRecommendationTodayResponse,
  type FundSearchItem,
} from '../api/funds';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import { ApiErrorAlert, AppPage, Badge, Button, Card, EmptyState, InlineAlert, Input, PageHeader, Select, StatCard } from '../components/common';
import { FundHoldingImportAssistant } from '../components/funds/FundHoldingImportAssistant';
import { formatDate, formatDateTime } from '../utils/format';

type PeriodKey = '1w' | '1m' | '3m' | '6m' | '1y' | '2y' | '3y' | 'ytd' | 'since_inception';

const FUND_RETURN_PERIODS: Array<{ key: PeriodKey; label: string; shortLabel: string }> = [
  { key: '1w', label: '近 1 周', shortLabel: '1周' },
  { key: '1m', label: '近 1 月', shortLabel: '1月' },
  { key: '3m', label: '近 3 月', shortLabel: '3月' },
  { key: '6m', label: '近 6 月', shortLabel: '6月' },
  { key: '1y', label: '近 1 年', shortLabel: '1年' },
  { key: '2y', label: '近 2 年', shortLabel: '2年' },
  { key: '3y', label: '近 3 年', shortLabel: '3年' },
  { key: 'ytd', label: '今年来', shortLabel: '今年' },
  { key: 'since_inception', label: '成立来', shortLabel: '成立' },
];

const LEDGER_THEME_COLORS = ['#06B6D4', '#22C55E', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#14B8A6'];

const ASSET_CLASS_LABELS: Record<string, string> = {
  active_equity: '主动权益',
  equity_beta: '指数权益',
  fixed_income: '固收',
  cash: '现金管理',
  global_asset: '海外资产',
  multi_asset: '多资产',
  unknown: '未识别',
};

const STRATEGY_FAMILY_LABELS: Record<string, string> = {
  active_equity: '主动权益策略',
  index_beta: '指数 beta 策略',
  bond_income: '固收收益策略',
  money_market: '货币流动性策略',
  qdii_global: '海外资产策略',
  fof_allocation: 'FOF 配置策略',
  general_fund: '通用基金策略',
};

const READINESS_LABELS: Record<string, string> = {
  ready_for_rule_signal: '规则信号可用',
  partial: '底座部分可用',
  pending: '待建立',
};

const MARKET_CONTEXT_LABELS: Record<string, string> = {
  proxy_only: '代理判断',
  missing: '待接入',
  ok: '已接入',
};

const MARKET_REGIME_LABELS: Record<string, string> = {
  neutral: '中性',
  momentum_tailwind: '动量顺风',
  risk_off: '风险退潮',
  drawdown_pressure: '回撤压力',
  high_volatility: '高波动',
};

const CALIBRATION_STATUS_LABELS: Record<string, string> = {
  not_ready: '待补数据',
  ready_for_research: '可做研究',
  calibrated: '已校准',
};

const VALIDATION_STATUS_LABELS: Record<string, string> = {
  heuristic_unvalidated: '初始规则，未回测',
  not_validated: '未验证',
  calibrated: '已校准',
};

const EVIDENCE_STATUS_LABELS: Record<string, string> = {
  ok: '已接入',
  connected: '已命中',
  no_match: '未命中',
  not_configured: '未配置',
  unavailable: '不可用',
  missing: '缺失',
  pending: '待检索',
};

const MARKET_RANK_TYPE_LABELS: Record<string, string> = {
  etf_net_inflow: 'ETF 流入',
  etf_net_outflow: 'ETF 流出',
  etf_turnover_heat: 'ETF 热度',
  open_fund_return_rank: '收益实证',
};

const MARKET_ROLE_LABELS: Record<string, string> = {
  market_buy_evidence: '买入证据',
  market_sell_risk_evidence: '卖出压力',
  market_liquidity_evidence: '流动性',
  market_return_evidence: '收益实证',
};

const MARKET_STATUS_LABELS: Record<string, string> = {
  completed: '已更新',
  partial: '部分可用',
  failed: '获取失败',
  ok: '可用',
  proxy_only: '代理口径',
  missing: '暂无数据',
};

const MARKET_ACTION_LABELS: Record<string, string> = {
  research_only: '仅研究',
  market_watchlist: '继续观察',
  add_to_pool: '加入基金池',
};

const RECOMMENDATION_RISK_LABELS: Record<string, string> = {
  market_evidence_missing: '市场证据缺失',
  uses_proxy_market_flow: '资金流为代理口径',
  not_analyzed_in_pool: '未生成单品画像',
  analysis_data_quality_not_ok: '画像数据不完整',
  backtest_sample_insufficient: '回测样本不足',
};

const BACKTEST_READINESS_LABELS: Record<string, string> = {
  ready_for_research: '回测可研究',
  insufficient_nav_history: '净值样本不足',
};

const LEDGER_ACCOUNT_TYPE_OPTIONS = [
  { value: '', label: '未设置' },
  { value: 'long_term', label: '长期定投' },
  { value: 'sector_theme', label: '行业主题' },
  { value: 'cash_management', label: '现金管理' },
  { value: 'watchlist', label: '观察仓' },
  { value: 'education_pension', label: '教育养老' },
  { value: 'other', label: '其他' },
];

const LEDGER_RISK_TARGET_OPTIONS = [
  { value: '', label: '未设置' },
  { value: 'conservative', label: '稳健' },
  { value: 'balanced', label: '均衡' },
  { value: 'growth', label: '成长' },
  { value: 'aggressive', label: '进取' },
];

const LEDGER_HORIZON_OPTIONS = [
  { value: '', label: '未设置' },
  { value: '3m', label: '3 个月内' },
  { value: '6m', label: '6 个月' },
  { value: '1y', label: '1 年' },
  { value: '3y_plus', label: '3 年以上' },
  { value: '5y_plus', label: '5 年以上' },
];

const LEDGER_REBALANCE_OPTIONS = [
  { value: '', label: '未设置' },
  { value: 'weekly', label: '每周检查' },
  { value: 'monthly', label: '每月' },
  { value: 'quarterly', label: '每季度' },
  { value: 'ad_hoc', label: '触发条件' },
];

type FundLedgerProfileDraft = {
  accountType: string;
  purpose: string;
  riskTarget: string;
  investmentHorizon: string;
  rebalanceFrequency: string;
  notes: string;
};

const EMPTY_LEDGER_PROFILE_DRAFT: FundLedgerProfileDraft = {
  accountType: '',
  purpose: '',
  riskTarget: '',
  investmentHorizon: '',
  rebalanceFrequency: '',
  notes: '',
};

function readNumber(obj: unknown, keys: string[]): number | null {
  if (!obj || typeof obj !== 'object') return null;
  const record = obj as Record<string, unknown>;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return null;
}

function readRecord(obj: unknown, keys: string[]): Record<string, unknown> {
  if (!obj || typeof obj !== 'object') return {};
  const record = obj as Record<string, unknown>;
  for (const key of keys) {
    const value = record[key];
    if (value && typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>;
  }
  return {};
}

function readString(obj: unknown, keys: string[]): string | null {
  if (!obj || typeof obj !== 'object') return null;
  const record = obj as Record<string, unknown>;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value) return value;
  }
  return null;
}

function readStringArray(obj: unknown, keys: string[]): string[] {
  if (!obj || typeof obj !== 'object') return [];
  const record = obj as Record<string, unknown>;
  for (const key of keys) {
    const value = record[key];
    if (Array.isArray(value)) return value.filter((item): item is string => typeof item === 'string' && item.length > 0);
  }
  return [];
}

function readRecordArray(obj: unknown, keys: string[]): Record<string, unknown>[] {
  if (!obj || typeof obj !== 'object') return [];
  const record = obj as Record<string, unknown>;
  for (const key of keys) {
    const value = record[key];
    if (Array.isArray(value)) {
      return value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item));
    }
  }
  return [];
}

function camelPeriodKey(key: PeriodKey): string {
  if (key === 'since_inception') return 'sinceInception';
  return key.toUpperCase();
}

function periodNumber(obj: unknown, key: PeriodKey): number | null {
  return readNumber(obj, [key, camelPeriodKey(key)]);
}

function metricNumber(metrics: Record<string, unknown>, key: string, ...aliases: string[]): number | null {
  return readNumber(metrics, [key, ...aliases]);
}

function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return `${value.toFixed(2)}%`;
}

function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return value.toFixed(digits);
}

function formatMoneyAmount(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  if (value >= 100000000) return `${(value / 100000000).toFixed(1)}亿`;
  if (value >= 10000) return `${(value / 10000).toFixed(1)}万`;
  return `${value.toFixed(0)}元`;
}

function formatCurrency(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return `¥${value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`;
}

function formatLargeAmount(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  if (abs >= 100000000) return `${sign}${(abs / 100000000).toFixed(2)}亿`;
  if (abs >= 10000) return `${sign}${(abs / 10000).toFixed(1)}万`;
  return `${value.toFixed(0)}`;
}

function hexToRgba(hex: string | null | undefined, alpha: number): string {
  const value = (hex || '#06B6D4').replace('#', '');
  const normalized = value.length === 3
    ? value.split('').map((char) => char + char).join('')
    : value.padEnd(6, '0').slice(0, 6);
  const number = Number.parseInt(normalized, 16);
  if (Number.isNaN(number)) return `rgba(6, 182, 212, ${alpha})`;
  const red = (number >> 16) & 255;
  const green = (number >> 8) & 255;
  const blue = number & 255;
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function formatSource(value: unknown): string {
  if (Array.isArray(value)) {
    const labels = value.map(formatSource).filter((item) => item && item !== '--');
    return labels.length ? labels.join(' / ') : '--';
  }
  if (typeof value !== 'string' || !value) return '--';
  if (value === 'fund_open_fund_rank_em') return '东方财富基金排行';
  if (value === 'fund_open_fund_daily_em') return '东方财富开放基金日榜';
  if (value === 'fund_open_fund_info_em') return '东方财富历史净值';
  if (value === 'fund_individual_analysis_xq') return '雪球基金风险分析';
  if (value === 'nav_calculation') return '本地净值估算';
  if (value === 'fund_name_em') return '东方财富基金名表';
  if (value === 'fund_nav_and_peer_rank_proxy') return '净值/同类分位代理';
  if (value === 'bootstrap_type_preset') return '分类型初始参数';
  if (value === 'akshare_market_context') return '公开指数/基金档案';
  if (value === 'stock_index_pe_lg') return '乐咕指数 PE';
  if (value === 'stock_index_pb_lg') return '乐咕指数 PB';
  if (value === 'fund_portfolio_industry_allocation_em') return '天天基金行业配置';
  if (value === 'fund_portfolio_hold_em') return '天天基金重仓持股';
  if (value === 'fund_announcement_report_em') return '天天基金定期报告';
  if (value === 'fund_purchase_em/fund_fee_em') return '天天基金交易规则/费率';
  if (value === 'intelligence_repository') return '本地资讯情报库';
  if (value === 'akshare.fund_etf_spot_em') return '东方财富 ETF 行情/资金流';
  if (value === 'akshare.fund_open_fund_rank_em') return '东方财富开放基金排行';
  return value;
}

function labelFromMap(map: Record<string, string>, value: string | null): string {
  if (!value) return '--';
  return map[value] || value;
}

function statusVariant(status: string | null): 'default' | 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'completed' || status === 'ok') return 'success';
  if (status === 'proxy_only' || status === 'partial') return 'info';
  if (status === 'missing') return 'warning';
  if (status === 'failed') return 'danger';
  return 'default';
}

function actionVariant(action: string): 'default' | 'success' | 'warning' | 'danger' | 'info' {
  if (action === 'buy' || action === 'dca') return 'success';
  if (action === 'reduce' || action === 'sell_watch') return 'danger';
  if (action === 'pause_buy') return 'warning';
  return 'info';
}

function riskTone(level?: string | null): 'default' | 'success' | 'warning' | 'danger' {
  if (level === '高') return 'danger';
  if (level === '中') return 'warning';
  if (level === '低') return 'success';
  return 'default';
}

function returnTone(value: number | null): 'default' | 'success' | 'danger' {
  if (value === null) return 'default';
  return value >= 0 ? 'success' : 'danger';
}

type PeerTone = 'leader' | 'strong' | 'neutral' | 'lagging' | 'weak' | 'unknown';

const PEER_TONE_META: Record<PeerTone, {
  label: string;
  badge: 'default' | 'success' | 'warning' | 'danger' | 'info';
  textClass: string;
  fillClass: string;
  railClass: string;
}> = {
  leader: {
    label: '头部领先',
    badge: 'success',
    textClass: 'text-success',
    fillClass: 'bg-success',
    railClass: 'bg-success/12',
  },
  strong: {
    label: '明显领先',
    badge: 'info',
    textClass: 'text-cyan',
    fillClass: 'bg-cyan',
    railClass: 'bg-cyan/12',
  },
  neutral: {
    label: '中位附近',
    badge: 'default',
    textClass: 'text-secondary-text',
    fillClass: 'bg-secondary-text',
    railClass: 'bg-surface-2',
  },
  lagging: {
    label: '偏弱观察',
    badge: 'warning',
    textClass: 'text-warning',
    fillClass: 'bg-warning',
    railClass: 'bg-warning/12',
  },
  weak: {
    label: '同类落后',
    badge: 'danger',
    textClass: 'text-danger',
    fillClass: 'bg-danger',
    railClass: 'bg-danger/12',
  },
  unknown: {
    label: '暂无分位',
    badge: 'default',
    textClass: 'text-muted-text',
    fillClass: 'bg-muted-text',
    railClass: 'bg-surface-2',
  },
};

function peerTone(percentile: number | null): PeerTone {
  if (percentile === null) return 'unknown';
  if (percentile >= 90) return 'leader';
  if (percentile >= 70) return 'strong';
  if (percentile >= 45) return 'neutral';
  if (percentile >= 25) return 'lagging';
  return 'weak';
}

function coverageVariant(status: string | null): 'default' | 'success' | 'warning' | 'danger' {
  if (status === 'ok') return 'success';
  if (status === 'missing') return 'danger';
  if (status === 'partial') return 'warning';
  return 'default';
}

function coverageLabel(status: string | null): string {
  if (status === 'ok') return 'ok';
  if (status === 'partial') return 'partial';
  if (status === 'missing') return 'missing';
  return '--';
}

function coverageText(status: string | null): string {
  if (status === 'ok') return '已接入';
  if (status === 'partial') return '部分可用';
  if (status === 'missing') return '待接入';
  return '未知';
}

function contextVariant(status: string | null): 'default' | 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'ok' || status === 'calibrated') return 'success';
  if (status === 'proxy_only' || status === 'ready_for_research') return 'info';
  if (status === 'missing' || status === 'not_ready') return 'warning';
  return 'default';
}

function evidenceVariant(status: string | null): 'default' | 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'ok' || status === 'connected') return 'success';
  if (status === 'no_match' || status === 'not_configured' || status === 'pending') return 'warning';
  if (status === 'unavailable' || status === 'missing') return 'danger';
  return 'default';
}

function formatPolicyWeight(value: unknown): string {
  const numeric = typeof value === 'number' && Number.isFinite(value) ? value : null;
  return numeric === null ? '--' : numeric.toFixed(2);
}

function formatPeerPercentile(value: number | null): string {
  return value === null ? '同类 --' : `同类 ${value.toFixed(1)}%`;
}

function formatPeerLead(value: number | null): string {
  return value === null ? '--' : `超过 ${value.toFixed(1)}% 同类`;
}

function rankPercentile(rank: number | null, sampleSize: number | null): number | null {
  if (rank === null || sampleSize === null || rank <= 0 || sampleSize <= 0) return null;
  return Math.max(0, Math.min(100, (sampleSize - rank + 1) / sampleSize * 100));
}

function formatRank(rank: number | null, sampleSize: number | null): string {
  if (rank === null && sampleSize === null) return '--';
  if (rank === null) return `-- / ${sampleSize}`;
  if (sampleSize === null) return `${rank}`;
  return `${rank} / ${sampleSize}`;
}

function feeRowText(row: Record<string, unknown>): string {
  const period = readString(row, ['适用期限', '持有期限', '期限', '购买金额', '金额']);
  const rate = readString(row, ['费率', '申购费率', '赎回费率', '原费率', '折扣后费率']);
  if (period && rate) return `${period} ${rate}`;
  if (rate) return rate;
  const fallback = Object.entries(row)
    .slice(0, 2)
    .map(([key, value]) => `${key} ${String(value)}`)
    .join(' · ');
  return fallback || '--';
}

type NextLayerView = {
  title: string;
  description: string;
  status: 'connected' | 'next' | 'planned';
};

function nextLayerView(value: string): NextLayerView {
  if (value.includes('基金类型')) {
    return {
      title: '分类型参数',
      description: '按主动权益、指数、固收、QDII 等拆分评分权重。',
      status: 'next',
    };
  }
  if (value.includes('市场周期') || value.includes('估值') || value.includes('风格')) {
    return {
      title: '市场上下文',
      description: '接入宽基趋势、行业景气、估值分位和风格轮动。',
      status: 'next',
    };
  }
  if (value.includes('交易规则') || value.includes('费率')) {
    return {
      title: '交易成本',
      description: '把申赎状态、起购金额和持有期费率纳入执行约束。',
      status: 'next',
    };
  }
  if (value.includes('行业新闻') || value.includes('财报') || value.includes('权威解读')) {
    return {
      title: '资讯佐证',
      description: '结合行业新闻、重仓公司公告财报和基金经理报告交叉验证。',
      status: 'next',
    };
  }
  if (value.includes('回测')) {
    return {
      title: '回测校准',
      description: '按基金类型验证阈值、回撤、胜率和换手成本。',
      status: 'planned',
    };
  }
  if (value.includes('LLM')) {
    return {
      title: 'LLM 审阅',
      description: '只负责解释、冲突检查和风险提示，不直接定买卖。',
      status: 'planned',
    };
  }
  return {
    title: value,
    description: '作为下一阶段数据或策略能力接入。',
    status: 'planned',
  };
}

function nextLayerVariant(status: NextLayerView['status']): 'default' | 'success' | 'warning' | 'info' {
  if (status === 'connected') return 'success';
  if (status === 'next') return 'info';
  return 'default';
}

function outcomeVariant(outcome: string | null): 'default' | 'success' | 'warning' | 'danger' {
  if (outcome === 'win') return 'success';
  if (outcome === 'loss') return 'danger';
  if (outcome === 'neutral') return 'warning';
  return 'default';
}

const FundReturnGrid: React.FC<{
  returns: Record<string, unknown>;
  percentiles?: Record<string, unknown>;
  compact?: boolean;
}> = ({ returns, percentiles, compact = false }) => {
  const rows = FUND_RETURN_PERIODS.map((period) => ({
    ...period,
    value: periodNumber(returns, period.key),
    percentile: periodNumber(percentiles, period.key),
  }));
  const maxAbsReturn = Math.max(1, ...rows.map((row) => Math.abs(row.value ?? 0)));
  const primary = rows.find((row) => row.key === '3m') || rows.find((row) => row.value !== null) || rows[0];
  const highlights = [
    rows.find((row) => row.key === '1m'),
    rows.find((row) => row.key === '1y'),
    rows.find((row) => row.key === 'ytd'),
  ].filter((row): row is typeof rows[number] => Boolean(row));

  if (compact) {
    return (
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
        {rows.map((period) => {
          const value = period.value;
          const percentile = period.percentile;
          return (
            <div key={period.key} className="min-w-0 rounded-xl border border-subtle bg-surface-2 px-3 py-2">
              <p className="truncate text-[11px] text-muted-text">{period.shortLabel}</p>
              <p className={`mt-1 text-sm font-semibold ${value !== null && value < 0 ? 'text-danger' : 'text-foreground'}`}>
                {formatPct(value)}
              </p>
              {percentile !== null ? <p className="mt-1 truncate text-[10px] text-secondary-text">{formatPeerPercentile(percentile)}</p> : null}
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <p className="label-uppercase">核心阶段</p>
          <div className="mt-2 flex flex-wrap items-end gap-x-4 gap-y-2">
            <div>
              <p className="text-sm text-secondary-text">{primary.label}</p>
              <p className={`mt-1 text-4xl font-semibold leading-none ${primary.value !== null && primary.value < 0 ? 'text-danger' : 'text-foreground'}`}>
                {formatPct(primary.value)}
              </p>
            </div>
            <div className="pb-1 text-sm text-secondary-text">
              <p>{formatPeerPercentile(primary.percentile)}</p>
              <p>按公开榜单阶段收益展示</p>
            </div>
          </div>
        </div>

        <div className="grid w-full gap-2 sm:grid-cols-3 lg:w-[520px]">
          {highlights.map((item) => (
            <div key={item.key} className="rounded-xl border border-subtle bg-surface-2 px-3 py-2">
              <p className="text-xs text-muted-text">{item.label}</p>
              <div className="mt-1 flex items-baseline justify-between gap-2">
                <p className={`text-base font-semibold ${item.value !== null && item.value < 0 ? 'text-danger' : 'text-foreground'}`}>
                  {formatPct(item.value)}
                </p>
                <p className="text-xs text-secondary-text">{formatPeerPercentile(item.percentile)}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        {rows.map((period) => {
          const value = period.value;
          const percentile = period.percentile;
          const toneMeta = PEER_TONE_META[peerTone(percentile)];
          const width = value === null ? 0 : Math.max(7, Math.min(100, Math.abs(value) / maxAbsReturn * 100));
          const isNegative = value !== null && value < 0;
          return (
            <div key={period.key} className="grid gap-2 rounded-xl border border-transparent px-1 py-1.5 sm:grid-cols-[72px_minmax(0,1fr)_104px_88px] sm:items-center">
              <div className="flex items-center justify-between gap-2 sm:block">
                <p className="text-sm font-medium text-foreground">{period.shortLabel}</p>
                <p className={`text-xs sm:hidden ${toneMeta.textClass}`}>{formatPeerPercentile(percentile)}</p>
              </div>
              <div className="h-2.5 overflow-hidden rounded-full bg-surface-2">
                {value !== null ? (
                  <div
                    className={`h-full rounded-full ${isNegative ? 'bg-danger/70' : 'bg-cyan/70'}`}
                    style={{ width: `${width}%` }}
                  />
                ) : null}
              </div>
              <p className={`text-sm font-semibold sm:text-right ${isNegative ? 'text-danger' : 'text-foreground'}`}>{formatPct(value)}</p>
              <p className={`hidden text-xs sm:block ${toneMeta.textClass}`}>{formatPeerPercentile(percentile)}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const FundProfileSummary: React.FC<{ profile?: Record<string, unknown>; compact?: boolean }> = ({ profile, compact = false }) => {
  const taxonomy = readRecord(profile, ['taxonomy']);
  const readiness = readRecord(profile, ['strategyReadiness', 'strategy_readiness']);
  const dataCoverage = readRecord(profile, ['dataCoverage', 'data_coverage']);
  const assetClass = readString(taxonomy, ['assetClass', 'asset_class']);
  const strategyFamily = readString(taxonomy, ['strategyFamily', 'strategy_family']);
  const holdingHorizon = readString(taxonomy, ['holdingHorizon', 'holding_horizon']);
  const styleTags = readStringArray(taxonomy, ['styleTags', 'style_tags']);
  const readinessStatus = readString(readiness, ['status']);
  const coverageStatus = readString(dataCoverage, ['status']);

  if (!Object.keys(taxonomy).length && !Object.keys(readiness).length) {
    return (
      <div className="rounded-xl border border-dashed border-border/60 bg-card/50 px-3 py-2 text-xs text-secondary-text">
        刷新后生成基金画像。
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Badge variant="info">画像：{labelFromMap(ASSET_CLASS_LABELS, assetClass)}</Badge>
      <Badge variant="default">{labelFromMap(STRATEGY_FAMILY_LABELS, strategyFamily)}</Badge>
      {holdingHorizon ? <Badge variant="default">期限 {holdingHorizon}</Badge> : null}
      {compact ? null : styleTags.map((tag) => <Badge key={tag} variant="history">{tag}</Badge>)}
      <Badge variant={coverageVariant(coverageStatus)}>数据 {coverageLabel(coverageStatus)}</Badge>
      <Badge variant={readinessStatus === 'ready_for_rule_signal' ? 'success' : 'warning'}>
        {labelFromMap(READINESS_LABELS, readinessStatus)}
      </Badge>
    </div>
  );
};

const StrategyFoundationPanel: React.FC<{ profile?: Record<string, unknown> }> = ({ profile }) => {
  const policy = readRecord(profile, ['strategyPolicy', 'strategy_policy']);
  const marketContext = readRecord(profile, ['marketContext', 'market_context']);
  const tradingRules = readRecord(profile, ['tradingRules', 'trading_rules']);
  const researchEvidence = readRecord(profile, ['researchEvidence', 'research_evidence']);
  const calibration = readRecord(profile, ['calibrationStatus', 'calibration_status']);
  const returnWeights = readRecord(policy, ['returnWeights', 'return_weights']);
  const thresholds = readRecord(policy, ['actionThresholds', 'action_thresholds']);
  const executionNotes = readStringArray(policy, ['executionNotes', 'execution_notes']);
  const availableProxies = readStringArray(marketContext, ['availableProxies', 'available_proxies']);
  const missingInputs = readStringArray(marketContext, ['missingInputs', 'missing_inputs']);
  const referenceIndices = readRecordArray(marketContext, ['referenceIndices', 'reference_indices']);
  const styleRotation = readRecord(marketContext, ['styleRotation', 'style_rotation']);
  const industryAllocation = readRecord(marketContext, ['industryAllocation', 'industry_allocation']);
  const stockHoldings = readRecord(marketContext, ['stockHoldings', 'stock_holdings']);
  const fundReports = readRecord(marketContext, ['fundReports', 'fund_reports']);
  const industries = readRecordArray(industryAllocation, ['items']);
  const holdings = readRecordArray(stockHoldings, ['items']);
  const reports = readRecordArray(fundReports, ['items']);
  const feeTables = readRecord(tradingRules, ['feeTables', 'fee_tables']);
  const subscriptionFees = readRecordArray(feeTables, ['subscription']);
  const redemptionFees = readRecordArray(feeTables, ['redemption']);
  const evidenceCategories = readRecord(researchEvidence, ['categories']);
  const fundReportEvidence = readRecord(evidenceCategories, ['fund_reports', 'fundReports']);
  const industryEvidence = readRecord(evidenceCategories, ['industry_news', 'industryNews']);
  const holdingEvidence = readRecord(evidenceCategories, ['holding_company_news', 'holdingCompanyNews']);
  const macroEvidence = readRecord(evidenceCategories, ['macro_market_news', 'macroMarketNews']);
  const evidenceItems = readRecordArray(researchEvidence, ['items']);
  const researchPlan = readStringArray(calibration, ['researchPlan', 'research_plan']);
  const marketStatus = readString(marketContext, ['status']);
  const calibrationStatus = readString(calibration, ['status']);
  const validationStatus = readString(policy, ['validationStatus', 'validation_status']);
  const regimeHint = readString(marketContext, ['regimeHint', 'regime_hint']);
  const confidence = readString(marketContext, ['confidence']);
  const marketSource = readString(marketContext, ['source']);
  const tradingStatus = readString(tradingRules, ['status']);
  const purchaseStatus = readString(tradingRules, ['purchaseStatus', 'purchase_status']);
  const redemptionStatus = readString(tradingRules, ['redemptionStatus', 'redemption_status']);
  const nextOpenDate = readString(tradingRules, ['nextOpenDate', 'next_open_date']);
  const researchStatus = readString(researchEvidence, ['status']);
  const sampleDays = readNumber(calibration, ['sampleDays', 'sample_days']);
  const requiredSampleDays = readNumber(calibration, ['requiredSampleDays', 'required_sample_days']);
  const readinessScore = readNumber(calibration, ['readinessScore', 'readiness_score']);
  const weight3m = readNumber(returnWeights, ['3m', '3M']);
  const peerWeight = readNumber(returnWeights, ['peer_1y', 'peer1y', 'peer1Y']);
  const minPurchaseAmount = readNumber(tradingRules, ['minPurchaseAmount', 'min_purchase_amount']);
  const dailyLimitAmount = readNumber(tradingRules, ['dailyLimitAmount', 'daily_limit_amount']);
  const frontFee = readNumber(tradingRules, ['frontFee', 'front_fee']);
  const enabledSources = readNumber(researchEvidence, ['enabledSources', 'enabled_sources']);
  const mainIndex = referenceIndices[0] || {};
  const mainIndexSymbol = readString(mainIndex, ['symbol']);
  const mainIndexReturn = readNumber(mainIndex, ['return20dPct', 'return_20d_pct']);
  const mainIndexValuation = readNumber(mainIndex, ['valuationPercentile5y', 'valuation_percentile_5y']);
  const mainIndexPe = readNumber(mainIndex, ['peTtm', 'pe_ttm']);
  const mainIndexPb = readNumber(mainIndex, ['pb']);
  const styleLeader = readString(styleRotation, ['leader']);
  const styleLeaderReturn = readNumber(styleRotation, ['leaderReturn20dPct', 'leader_return_20d_pct']);
  const categoryRows = [
    { label: '报告', record: fundReportEvidence, count: reports.length },
    { label: '行业', record: industryEvidence, count: readRecordArray(industryEvidence, ['items']).length },
    { label: '重仓', record: holdingEvidence, count: readRecordArray(holdingEvidence, ['items']).length },
    { label: '宏观', record: macroEvidence, count: readRecordArray(macroEvidence, ['items']).length },
  ];

  if (
    !Object.keys(policy).length &&
    !Object.keys(marketContext).length &&
    !Object.keys(tradingRules).length &&
    !Object.keys(researchEvidence).length &&
    !Object.keys(calibration).length
  ) {
    return null;
  }

  return (
    <Card title="策略底座" subtitle="Signal foundation" className="min-w-0 xl:col-span-2">
      <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-5">
        <div className="min-w-0 rounded-xl border border-subtle bg-surface-2 px-4 py-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="label-uppercase">分类型参数</p>
              <p className="mt-1 break-words text-sm font-medium text-foreground">{readString(policy, ['label']) || '--'}</p>
            </div>
            <Badge variant="warning" className="shrink-0 whitespace-nowrap">
              {labelFromMap(VALIDATION_STATUS_LABELS, validationStatus)}
            </Badge>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-lg border border-border/45 bg-card/60 px-2 py-2">
              <p className="text-muted-text">3月权重</p>
              <p className="mt-1 font-semibold text-foreground">{formatPolicyWeight(weight3m)}</p>
            </div>
            <div className="rounded-lg border border-border/45 bg-card/60 px-2 py-2">
              <p className="text-muted-text">同类权重</p>
              <p className="mt-1 font-semibold text-foreground">{formatPolicyWeight(peerWeight)}</p>
            </div>
            <div className="rounded-lg border border-border/45 bg-card/60 px-2 py-2">
              <p className="text-muted-text">买入门槛</p>
              <p className="mt-1 font-semibold text-foreground">{formatNumber(readNumber(thresholds, ['buy']), 0)}</p>
            </div>
            <div className="rounded-lg border border-border/45 bg-card/60 px-2 py-2">
              <p className="text-muted-text">定投门槛</p>
              <p className="mt-1 font-semibold text-foreground">{formatNumber(readNumber(thresholds, ['dca']), 0)}</p>
            </div>
          </div>
          {executionNotes.length ? (
            <p className="mt-3 text-xs leading-5 text-secondary-text">{executionNotes[0]}</p>
          ) : null}
        </div>

        <div className="min-w-0 rounded-xl border border-subtle bg-surface-2 px-4 py-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="label-uppercase">市场上下文</p>
              <p className="mt-1 text-sm font-medium text-foreground">{labelFromMap(MARKET_REGIME_LABELS, regimeHint)}</p>
            </div>
            <Badge variant={contextVariant(marketStatus)} className="shrink-0 whitespace-nowrap">
              {labelFromMap(MARKET_CONTEXT_LABELS, marketStatus)}
            </Badge>
          </div>
          <div className="mt-3 space-y-2 text-xs">
            <div className="rounded-lg border border-border/45 bg-card/60 px-2 py-2">
              <p className="text-muted-text">参考指数</p>
              <p className="mt-1 font-semibold text-foreground">{mainIndexSymbol || '--'} · {formatPct(mainIndexReturn)}</p>
            </div>
            <div className="rounded-lg border border-border/45 bg-card/60 px-2 py-2">
              <p className="text-muted-text">估值分位</p>
              <p className="mt-1 font-semibold text-foreground">
                {formatPct(mainIndexValuation)} <span className="font-normal text-muted-text">PE {formatNumber(mainIndexPe)} / PB {formatNumber(mainIndexPb)}</span>
              </p>
            </div>
            <p className="leading-5 text-secondary-text">
              风格领先 {styleLeader || '--'} {styleLeaderReturn !== null ? formatPct(styleLeaderReturn) : ''} · 置信度 {confidence || '--'}
            </p>
            <p className="leading-5 text-muted-text">{formatSource(marketSource)}</p>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {industries.slice(0, 2).map((item) => (
              <Badge key={String(item.industry)} variant="info">
                {readString(item, ['industry'])} {formatPct(readNumber(item, ['navRatioPct', 'nav_ratio_pct']))}
              </Badge>
            ))}
            {holdings.slice(0, 2).map((item) => (
              <Badge key={String(item.stock_name || item.stockName)} variant="default">
                {readString(item, ['stockName', 'stock_name'])} {formatPct(readNumber(item, ['navRatioPct', 'nav_ratio_pct']))}
              </Badge>
            ))}
          </div>
          {missingInputs.length ? (
            <p className="mt-3 text-xs leading-5 text-warning">待补：{missingInputs.slice(0, 2).join(' / ')}</p>
          ) : availableProxies.length ? (
            <p className="mt-3 text-xs leading-5 text-secondary-text">{availableProxies.slice(0, 2).join(' / ')}</p>
          ) : null}
        </div>

        <div className="min-w-0 rounded-xl border border-subtle bg-surface-2 px-4 py-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="label-uppercase">交易规则/费用</p>
              <p className="mt-1 text-sm font-medium text-foreground">{purchaseStatus || '--'}</p>
            </div>
            <Badge variant={coverageVariant(tradingStatus)} className="shrink-0 whitespace-nowrap">
              {coverageLabel(tradingStatus)}
            </Badge>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-lg border border-border/45 bg-card/60 px-2 py-2">
              <p className="text-muted-text">赎回</p>
              <p className="mt-1 truncate font-semibold text-foreground">{redemptionStatus || '--'}</p>
            </div>
            <div className="rounded-lg border border-border/45 bg-card/60 px-2 py-2">
              <p className="text-muted-text">起购</p>
              <p className="mt-1 font-semibold text-foreground">{formatMoneyAmount(minPurchaseAmount)}</p>
            </div>
            <div className="rounded-lg border border-border/45 bg-card/60 px-2 py-2">
              <p className="text-muted-text">日限额</p>
              <p className="mt-1 font-semibold text-foreground">{formatMoneyAmount(dailyLimitAmount)}</p>
            </div>
            <div className="rounded-lg border border-border/45 bg-card/60 px-2 py-2">
              <p className="text-muted-text">前端费</p>
              <p className="mt-1 font-semibold text-foreground">{formatPct(frontFee)}</p>
            </div>
          </div>
          <p className="mt-3 text-xs leading-5 text-secondary-text">
            赎回费：{redemptionFees.length ? feeRowText(redemptionFees[0]) : '--'}
          </p>
          {nextOpenDate ? <p className="mt-1 text-xs text-muted-text">下一开放日 {formatDate(nextOpenDate)}</p> : null}
          {subscriptionFees.length ? <p className="mt-1 text-xs text-muted-text">申购费：{feeRowText(subscriptionFees[0])}</p> : null}
        </div>

        <div className="min-w-0 rounded-xl border border-subtle bg-surface-2 px-4 py-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="label-uppercase">资讯佐证</p>
              <p className="mt-1 text-sm font-medium text-foreground">{labelFromMap(EVIDENCE_STATUS_LABELS, researchStatus)}</p>
            </div>
            <Badge variant={evidenceVariant(researchStatus)} className="shrink-0 whitespace-nowrap">
              {enabledSources === null ? '--' : `${enabledSources} 源`}
            </Badge>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
            {categoryRows.map((item) => {
              const status = readString(item.record, ['status']);
              return (
                <div key={item.label} className="rounded-lg border border-border/45 bg-card/60 px-2 py-2">
                  <p className="text-muted-text">{item.label}</p>
                  <p className="mt-1 font-semibold text-foreground">
                    {item.count ? `${item.count}条` : labelFromMap(EVIDENCE_STATUS_LABELS, status)}
                  </p>
                </div>
              );
            })}
          </div>
          <p className="mt-3 line-clamp-2 text-xs leading-5 text-secondary-text">
            {readString(evidenceItems[0], ['title']) || readString(reports[0], ['title']) || '已预留行业新闻、重仓公司财报和权威解读接入口。'}
          </p>
          {enabledSources === 0 ? (
            <p className="mt-1 text-xs text-warning">新闻源未配置，当前主要使用基金公告/报告。</p>
          ) : null}
        </div>

        <div className="min-w-0 rounded-xl border border-subtle bg-surface-2 px-4 py-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="label-uppercase">回测校准</p>
              <p className="mt-1 text-sm font-medium text-foreground">{labelFromMap(CALIBRATION_STATUS_LABELS, calibrationStatus)}</p>
            </div>
            <Badge variant={contextVariant(calibrationStatus)} className="shrink-0 whitespace-nowrap">
              {readinessScore === null ? '--' : `${readinessScore.toFixed(0)}%`}
            </Badge>
          </div>
          <div className="mt-4">
            <div className="flex items-center justify-between text-xs text-secondary-text">
              <span>样本</span>
              <span>{sampleDays ?? 0} / {requiredSampleDays ?? '--'} 天</span>
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-card">
              <div
                className="h-full rounded-full bg-cyan/75"
                style={{ width: `${Math.max(4, Math.min(100, readinessScore ?? 0))}%` }}
              />
            </div>
          </div>
          {researchPlan.length ? (
            <p className="mt-3 text-xs leading-5 text-secondary-text">{researchPlan[0]}</p>
          ) : null}
        </div>
      </div>
    </Card>
  );
};

const FundProfilePanel: React.FC<{ profile?: Record<string, unknown> }> = ({ profile }) => {
  const taxonomy = readRecord(profile, ['taxonomy']);
  const readiness = readRecord(profile, ['strategyReadiness', 'strategy_readiness']);
  const dataCoverage = readRecord(profile, ['dataCoverage', 'data_coverage']);
  const marketContext = readRecord(profile, ['marketContext', 'market_context']);
  const dimensions = Array.isArray(dataCoverage.dimensions)
    ? dataCoverage.dimensions.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
    : [];
  const marketNeeds = readStringArray(marketContext, ['missingInputs', 'missing_inputs']);
  const blockers = readStringArray(readiness, ['blockers']);
  const warnings = readStringArray(readiness, ['warnings']);
  const nextLayers = readStringArray(readiness, ['nextLayers', 'next_layers']);
  const strategyFamily = readString(taxonomy, ['strategyFamily', 'strategy_family']);
  const coverageStatus = readString(dataCoverage, ['status']);
  const layerViews = nextLayers.map(nextLayerView);

  return (
    <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
      <Card title="基金画像" subtitle={labelFromMap(STRATEGY_FAMILY_LABELS, strategyFamily)} className="min-w-0">
        <FundProfileSummary profile={profile} />
        <div className="mt-4 space-y-3">
          <div>
            <p className="label-uppercase">市场上下文缺口</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {marketNeeds.length ? marketNeeds.map((item) => (
                <Badge key={item} variant="default">{item}</Badge>
              )) : <span className="text-sm text-secondary-text">暂无</span>}
            </div>
          </div>
          <div>
            <p className="label-uppercase">策略准备度</p>
            <div className="mt-2 space-y-2 text-sm text-secondary-text">
              {blockers.length ? blockers.map((item) => (
                <p key={item} className="rounded-xl border border-warning/20 bg-warning/10 px-3 py-2 text-warning">{item}</p>
              )) : (
                <p className="rounded-xl border border-success/20 bg-success/10 px-3 py-2 text-success">基础规则信号输入已齐备，可进入分类型回测校准。</p>
              )}
              {!blockers.length && warnings.length ? warnings.map((item) => (
                <p key={item} className="rounded-xl border border-cyan/20 bg-cyan/10 px-3 py-2 text-cyan">{item}</p>
              )) : null}
            </div>
          </div>
        </div>
      </Card>

      <Card title="数据覆盖" subtitle="Data foundation" className="min-w-0">
        <div className="mb-4 flex flex-col gap-3 rounded-xl border border-subtle bg-surface-2 px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="label-uppercase">底座状态</p>
            <p className="mt-1 text-sm text-secondary-text">用于判断当前信号是否有足够公开数据支撑。</p>
          </div>
          <Badge variant={coverageVariant(coverageStatus)} size="md">{coverageText(coverageStatus)}</Badge>
        </div>
        {dimensions.length ? (
          <div className="grid gap-2 md:grid-cols-2">
            {dimensions.map((item) => {
              const label = readString(item, ['label']) || '--';
              const status = readString(item, ['status']);
              const source = readString(item, ['source']);
              const freshness = readString(item, ['freshness']);
              const fields = readStringArray(item, ['fields']);
              return (
                <div key={String(item.key || label)} className="rounded-xl border border-subtle bg-surface-2 px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-sm font-medium text-foreground">{label}</p>
                    <Badge variant={coverageVariant(status)}>{coverageLabel(status)}</Badge>
                  </div>
                  <p className="mt-1 truncate text-xs text-secondary-text">{formatSource(source)}</p>
                  {freshness ? <p className="mt-1 text-xs text-muted-text">日期 {formatDate(freshness)}</p> : null}
                  {fields.length ? <p className="mt-1 truncate text-xs text-muted-text">字段 {fields.length} 项</p> : null}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-border/60 bg-card/50 px-3 py-4 text-sm text-secondary-text">
            刷新分析后会生成数据覆盖明细。
          </div>
        )}
        {layerViews.length ? (
          <div className="mt-5">
            <div className="mb-3 flex items-center gap-2">
              <GitBranch className="h-4 w-4 text-cyan" />
              <p className="label-uppercase">能力路线图</p>
            </div>
            <div className="grid gap-2 md:grid-cols-2">
              {layerViews.map((item, index) => (
                <div key={`${item.title}-${index}`} className="rounded-xl border border-subtle bg-card/70 px-3 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-start gap-2">
                      <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-cyan/25 bg-cyan/10 text-xs font-semibold text-cyan">
                        {index + 1}
                      </div>
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-foreground">{item.title}</p>
                        <p className="mt-1 text-xs leading-5 text-secondary-text">{item.description}</p>
                      </div>
                    </div>
                    <Badge variant={nextLayerVariant(item.status)} className="shrink-0 whitespace-nowrap">
                      {item.status === 'next' ? '下一步' : '规划中'}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </Card>

      <StrategyFoundationPanel profile={profile} />
    </div>
  );
};

const FundSignalDiagnostics: React.FC<{ analysis: FundAnalysisSnapshot }> = ({ analysis }) => {
  const hasLimitations = analysis.limitations.length > 0;
  const qualityVariant = analysis.dataQuality === 'ok' && !hasLimitations ? 'success' : 'warning';

  return (
    <Card title="信号解释与可信度" subtitle="Why this signal" className="min-w-0">
      <div className="grid gap-4 lg:grid-cols-[1.05fr_0.95fr]">
        <div className="min-w-0 rounded-xl border border-subtle bg-surface-2 px-4 py-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="label-uppercase">触发依据</p>
              <p className="mt-1 text-sm text-secondary-text">这些字段共同推高或压低当前基金类信号。</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge variant={actionVariant(analysis.action)}>{analysis.actionLabel}</Badge>
              <Badge variant={riskTone(analysis.riskLevel)}>风险 {analysis.riskLevel}</Badge>
            </div>
          </div>

          <ol className="mt-4 space-y-3">
            {analysis.reasons.map((reason, index) => (
              <li key={reason} className="grid grid-cols-[28px_minmax(0,1fr)] gap-3">
                <div className="flex h-7 w-7 items-center justify-center rounded-full border border-cyan/25 bg-cyan/10 text-xs font-semibold text-cyan">
                  {index + 1}
                </div>
                <div className="min-w-0 border-b border-border/40 pb-3 last:border-b-0 last:pb-0">
                  <p className="break-words text-sm text-foreground">{reason}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>

        <div className="min-w-0 rounded-xl border border-subtle bg-surface-2 px-4 py-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="label-uppercase">数据可信度</p>
              <p className="mt-1 text-sm text-secondary-text">这里说明哪些指标是直取公开数据，哪些只能估算。</p>
            </div>
            <Badge variant={qualityVariant}>{hasLimitations ? '存在边界' : '覆盖完整'}</Badge>
          </div>

          <div className="mt-4 rounded-xl border border-border/50 bg-card/70 px-3 py-3">
            <div className="flex items-start gap-3">
              {hasLimitations ? (
                <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warning" />
              ) : (
                <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-success" />
              )}
              <div className="min-w-0">
                <p className="text-sm font-medium text-foreground">
                  {hasLimitations ? '当前建议需要带边界解读' : '本轮公开数据覆盖良好'}
                </p>
                <p className="mt-1 text-xs leading-5 text-secondary-text">
                  {hasLimitations
                    ? '系统仍会给出跟踪信号，但不把估算指标包装成平台已披露数据。'
                    : '净值、收益、风险和同类比较均可作为本轮分析输入。'}
                </p>
              </div>
            </div>
          </div>

          <div className="mt-3 space-y-2">
            {hasLimitations ? analysis.limitations.map((item) => (
              <div key={item} className="rounded-xl border border-warning/20 bg-warning/10 px-3 py-2 text-sm leading-5 text-warning">
                {item}
              </div>
            )) : (
              <div className="rounded-xl border border-success/20 bg-success/10 px-3 py-2 text-sm leading-5 text-success">
                暂无明显数据缺口；后续仍需接入市场周期和回测校准来提升决策可信度。
              </div>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
};

const MarketRankingRow: React.FC<{ item: FundMarketRankingItem; rankType: string }> = ({ item, rankType }) => {
  const metrics = item.metrics || {};
  const flow = readNumber(metrics, ['mainNetInflowAmount', 'main_net_inflow_amount']);
  const outflow = readNumber(metrics, ['proxyNetOutflowAmount', 'proxy_net_outflow_amount']);
  const amount = readNumber(metrics, ['amount', 'proxyTurnoverAmount', 'proxy_turnover_amount']);
  const return3m = readNumber(metrics, ['return3mPct', 'return_3m_pct']);
  const return6m = readNumber(metrics, ['return6mPct', 'return_6m_pct']);
  const changePct = readNumber(metrics, ['changePct', 'change_pct', 'dailyGrowthPct', 'daily_growth_pct']);
  const primaryMetric = rankType === 'etf_net_outflow'
    ? { label: '净流出', value: formatLargeAmount(outflow), className: 'text-danger' }
    : rankType === 'etf_net_inflow'
      ? { label: '净流入', value: formatLargeAmount(flow), className: 'text-success' }
      : rankType === 'etf_turnover_heat'
        ? { label: '成交额', value: formatLargeAmount(amount), className: 'text-foreground' }
        : { label: '近3月', value: formatPct(return3m), className: return3m !== null && return3m < 0 ? 'text-danger' : 'text-success' };
  const secondaryMetric = rankType.startsWith('etf')
    ? `涨跌 ${formatPct(changePct)} · 成交 ${formatLargeAmount(amount)}`
    : `近6月 ${formatPct(return6m)} · 申购 ${readString(metrics, ['purchaseStatus', 'purchase_status']) || '--'}`;
  const role = item.recommendationRole ? MARKET_ROLE_LABELS[item.recommendationRole] || item.recommendationRole : '公开证据';
  const dataDate = readString(item.freshness, ['dataDate', 'data_date']);

  return (
    <div className="grid gap-3 border-t border-subtle px-3 py-3 text-sm sm:grid-cols-[40px_minmax(0,1.25fr)_minmax(118px,0.55fr)_minmax(160px,0.75fr)] sm:items-center">
      <div className="text-xs font-semibold text-muted-text">#{item.rank}</div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <p className="truncate font-semibold text-foreground">{item.name || `基金${item.code}`}</p>
          <Badge variant="info">{item.code}</Badge>
          {item.fundType ? <Badge variant="default">{item.fundType}</Badge> : null}
        </div>
        <p className="mt-1 truncate text-xs text-secondary-text">{secondaryMetric}</p>
      </div>
      <div>
        <p className="text-xs text-muted-text">{primaryMetric.label}</p>
        <p className={`mt-1 font-semibold ${primaryMetric.className}`}>{primaryMetric.value}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2 sm:justify-end">
        <Badge variant={statusVariant(item.status)}>{MARKET_STATUS_LABELS[item.status] || item.status}</Badge>
        <Badge variant="default">{role}</Badge>
        <span className="text-xs text-muted-text">{formatDate(dataDate || undefined)}</span>
      </div>
    </div>
  );
};

type MarketCandidateAddPayload = {
  code: string;
  name?: string | null;
};

function recommendationEvidenceText(evidence: Record<string, unknown>): string {
  const rankType = readString(evidence, ['rankType', 'rank_type']) || 'market_evidence';
  const rank = readNumber(evidence, ['rank']);
  const metrics = readRecord(evidence, ['metrics']);
  const flow = readNumber(metrics, ['mainNetInflowAmount', 'main_net_inflow_amount']);
  const outflow = readNumber(metrics, ['proxyNetOutflowAmount', 'proxy_net_outflow_amount']);
  const amount = readNumber(metrics, ['amount', 'proxyTurnoverAmount', 'proxy_turnover_amount']);
  const return3m = readNumber(metrics, ['return3mPct', 'return_3m_pct']);
  const changePct = readNumber(metrics, ['changePct', 'change_pct', 'dailyGrowthPct', 'daily_growth_pct']);
  const label = MARKET_RANK_TYPE_LABELS[rankType] || rankType;
  const prefix = rank ? `${label} #${rank}` : label;

  if (rankType === 'etf_net_inflow') return `${prefix} · 净流入 ${formatLargeAmount(flow)} · 涨跌 ${formatPct(changePct)}`;
  if (rankType === 'etf_net_outflow') return `${prefix} · 净流出 ${formatLargeAmount(outflow)} · 涨跌 ${formatPct(changePct)}`;
  if (rankType === 'etf_turnover_heat') return `${prefix} · 成交额 ${formatLargeAmount(amount)} · 涨跌 ${formatPct(changePct)}`;
  if (rankType === 'open_fund_return_rank') return `${prefix} · 近3月 ${formatPct(return3m)}`;
  return prefix;
}

const RecommendationEvidenceCard: React.FC<{
  candidate: FundRecommendationCandidate;
  index: number;
  inPool: boolean;
  isAdding: boolean;
  onAddCandidate: (candidate: MarketCandidateAddPayload, shouldAnalyze: boolean) => void;
}> = ({
  candidate,
  index,
  inPool,
  isAdding,
  onAddCandidate,
}) => {
  const readinessStatus = readString(candidate.backtestReadiness, ['status']);
  const navSampleCount = readNumber(candidate.backtestReadiness, ['navSampleCount', 'nav_sample_count']);
  const latestActionLabel = candidate.latestAnalysis?.actionLabel || null;
  const evidence = candidate.marketEvidence || [];
  const riskFlags = candidate.riskFlags || [];

  return (
    <div className="rounded-2xl border border-subtle bg-surface-2/55 px-3 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-muted-text">#{index + 1}</span>
            <p className="truncate text-sm font-semibold text-foreground">{candidate.name || `基金${candidate.code}`}</p>
            <Badge variant="info">{candidate.code}</Badge>
            {candidate.fundType ? <Badge variant="default">{candidate.fundType}</Badge> : null}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Badge variant={candidate.marketAction === 'add_to_pool' ? 'success' : 'default'}>
              {MARKET_ACTION_LABELS[candidate.marketAction] || candidate.marketAction}
            </Badge>
            <Badge variant="default">市场级</Badge>
            <Badge variant={candidate.personalized ? 'success' : 'default'}>
              {candidate.personalized ? '已个性化' : '未用个人数据'}
            </Badge>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-[11px] uppercase tracking-[0.18em] text-muted-text">Score</p>
          <p className="mt-1 text-lg font-semibold text-foreground">{formatNumber(candidate.score, 1)}</p>
        </div>
      </div>

      <div className="mt-3 space-y-2">
        {evidence.length ? evidence.slice(0, 2).map((item, evidenceIndex) => {
          const freshness = readRecord(item, ['freshness']);
          const dataDate = readString(freshness, ['dataDate', 'data_date']);
          const roleKey = readString(item, ['recommendationRole', 'recommendation_role']);
          return (
            <div key={`${candidate.code}-evidence-${evidenceIndex}`} className="rounded-xl border border-border/50 bg-card/65 px-3 py-2">
              <p className="text-xs font-medium text-foreground">{recommendationEvidenceText(item)}</p>
              <p className="mt-1 text-[11px] text-muted-text">
                {roleKey ? MARKET_ROLE_LABELS[roleKey] || roleKey : '公开证据'}
                {dataDate ? ` · ${formatDate(dataDate)}` : ''}
              </p>
            </div>
          );
        }) : (
          <div className="rounded-xl border border-warning/20 bg-warning/10 px-3 py-2 text-xs text-warning">
            暂无可解释的市场证据，不能作为关注候选。
          </div>
        )}
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <div className="rounded-xl border border-subtle bg-card/50 px-3 py-2">
          <p className="text-[11px] uppercase tracking-[0.16em] text-muted-text">回测准备</p>
          <p className="mt-1 text-sm font-semibold text-foreground">
            {BACKTEST_READINESS_LABELS[readinessStatus || ''] || readinessStatus || '--'}
          </p>
          <p className="mt-1 text-xs text-secondary-text">NAV 样本 {navSampleCount ?? '--'}</p>
        </div>
        <div className="rounded-xl border border-subtle bg-card/50 px-3 py-2">
          <p className="text-[11px] uppercase tracking-[0.16em] text-muted-text">单品画像</p>
          <p className="mt-1 text-sm font-semibold text-foreground">
            {latestActionLabel || (candidate.latestAnalysis ? '已有分析' : '待分析')}
          </p>
          <p className="mt-1 text-xs text-secondary-text">{candidate.dataQualitySummary || '--'}</p>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {riskFlags.length ? riskFlags.slice(0, 3).map((flag) => (
          <Badge key={flag} variant={flag.includes('insufficient') || flag.includes('not_') ? 'warning' : 'default'}>
            {RECOMMENDATION_RISK_LABELS[flag] || flag}
          </Badge>
        )) : (
          <Badge variant="success">暂无显著风险标记</Badge>
        )}
      </div>

      {candidate.invalidIf.length ? (
        <p className="mt-3 line-clamp-2 text-xs leading-5 text-secondary-text">
          失效条件：{candidate.invalidIf.slice(0, 2).join('；')}
        </p>
      ) : null}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant={inPool ? 'secondary' : 'primary'}
          onClick={() => onAddCandidate(candidate, true)}
          isLoading={isAdding}
          loadingText={inPool ? '刷新中' : '加入中'}
        >
          {inPool ? <RefreshCw className="h-4 w-4" /> : <ListPlus className="h-4 w-4" />}
          {inPool ? '刷新分析' : '加入并分析'}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => onAddCandidate(candidate, false)}
          disabled={inPool || isAdding}
        >
          <Target className="h-4 w-4" />
          仅加关注
        </Button>
      </div>
    </div>
  );
};

const MarketRankingWorkbench: React.FC<{
  rankings: FundMarketRankingsResponse | null;
  recommendations: FundRecommendationTodayResponse | null;
  isLoading: boolean;
  recommendationLoading: boolean;
  error: ParsedApiError | null;
  recommendationError: ParsedApiError | null;
  selectedRankType: string | null;
  onSelectRankType: (rankType: string) => void;
  onRefresh: () => void;
  onAddCandidate: (candidate: MarketCandidateAddPayload, shouldAnalyze: boolean) => void;
  poolCodes: Set<string>;
  addingCode: string | null;
}> = ({
  rankings,
  recommendations,
  isLoading,
  recommendationLoading,
  error,
  recommendationError,
  selectedRankType,
  onSelectRankType,
  onRefresh,
  onAddCandidate,
  poolCodes,
  addingCode,
}) => {
  const groups = rankings?.groups || [];
  const selectedGroup = groups.find((group) => group.rankType === selectedRankType) || groups[0] || null;
  const marketCandidates = rankings?.recommendationCandidates || [];
  const recommendationCandidates = recommendations?.candidates || [];
  const personalizationStatus = readString(recommendations?.personalization, ['status'])
    || readString(rankings?.personalization, ['status']);
  const asOfDate = rankings?.asOfDate || readString(selectedGroup?.freshness, ['dataDate', 'data_date']) || undefined;

  return (
    <section className="rounded-[28px] border border-cyan/15 bg-cyan/[0.035] p-3 sm:p-4">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(340px,0.85fr)]">
      <Card className="min-w-0" padding="lg">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="info" size="md">公开市场级</Badge>
              <Badge variant={statusVariant(rankings?.status || (isLoading ? 'partial' : null))} size="md">
                {isLoading ? '更新中' : MARKET_STATUS_LABELS[rankings?.status || ''] || rankings?.status || '待加载'}
              </Badge>
              <Badge variant="default" size="md">未使用个人持仓</Badge>
            </div>
            <h2 className="mt-3 text-2xl font-semibold text-foreground">市场公开榜单</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-secondary-text">
              先看市场层面的资金流、成交热度和收益实证，再进入候选基金与个人基金池；真实加减仓动作会等用户画像和已确认持仓齐备后再出现。
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2 lg:justify-end">
            <div className="rounded-xl border border-subtle bg-surface-2/70 px-3 py-2 text-right">
              <p className="text-[11px] uppercase tracking-[0.18em] text-muted-text">As of</p>
              <p className="mt-1 text-sm font-semibold text-foreground">{formatDate(asOfDate)}</p>
            </div>
            <Button variant="secondary" size="sm" onClick={onRefresh} isLoading={isLoading} loadingText="更新中">
              <RefreshCw className="h-4 w-4" />
              更新榜单
            </Button>
          </div>
        </div>

        {error ? (
          <div className="mt-4">
            <ApiErrorAlert error={error} />
          </div>
        ) : null}

        <div className="mt-5 grid grid-cols-3 gap-2">
          <div className="rounded-xl border border-subtle bg-surface-2/55 px-2 py-3 sm:px-3">
            <p className="text-[10px] uppercase tracking-[0.14em] text-secondary-text">榜单组</p>
            <p className="mt-1 text-xl font-semibold text-foreground sm:text-2xl">{groups.length || '--'}</p>
            <p className="mt-1 hidden text-xs text-secondary-text sm:block">ETF 资金流 / 开放式收益</p>
          </div>
          <div className="rounded-xl border border-subtle bg-surface-2/55 px-2 py-3 sm:px-3">
            <p className="text-[10px] uppercase tracking-[0.14em] text-secondary-text">候选池</p>
            <p className="mt-1 text-xl font-semibold text-foreground sm:text-2xl">
              {recommendationCandidates.length || marketCandidates.length || '--'}
            </p>
            <p className="mt-1 hidden text-xs text-secondary-text sm:block">已接荐基证据卡</p>
          </div>
          <div className="rounded-xl border border-subtle bg-surface-2/55 px-2 py-3 sm:px-3">
            <p className="text-[10px] uppercase tracking-[0.14em] text-secondary-text">个性化</p>
            <p className="mt-1 text-base font-semibold text-foreground sm:text-lg">{personalizationStatus === 'market_only' ? '未启用' : personalizationStatus || '--'}</p>
            <p className="mt-1 hidden text-xs text-secondary-text sm:block">需画像 + 持仓后才给动作</p>
          </div>
        </div>

        <div className="mt-5 overflow-x-auto">
          <div className="flex min-w-max gap-2 pb-1">
            {groups.map((group) => {
              const active = selectedGroup?.rankType === group.rankType;
              return (
                <button
                  key={group.rankType}
                  type="button"
                  onClick={() => onSelectRankType(group.rankType)}
                  className={`rounded-xl border px-3 py-2 text-left transition-colors ${active ? 'border-cyan/50 bg-cyan/10 text-cyan' : 'border-subtle bg-card/70 text-secondary-text hover:bg-hover/60'}`}
                >
                  <p className="text-sm font-semibold">{MARKET_RANK_TYPE_LABELS[group.rankType] || group.title}</p>
                  <p className="mt-1 text-xs opacity-80">{group.items.length} 只 · {MARKET_STATUS_LABELS[group.status] || group.status}</p>
                </button>
              );
            })}
          </div>
        </div>

        <div className="mt-4 overflow-hidden rounded-2xl border border-subtle">
          <div className="flex flex-col gap-2 bg-surface-2/70 px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-semibold text-foreground">{selectedGroup?.title || '等待榜单数据'}</p>
              <p className="mt-1 text-xs text-secondary-text">{selectedGroup?.description || '公开数据源返回后展示。'}</p>
            </div>
            {selectedGroup?.sourceUrl ? (
              <a
                href={selectedGroup.sourceUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-xs text-cyan hover:text-cyan/80"
              >
                {formatSource(selectedGroup.source)}
                <ArrowUpRight className="h-3.5 w-3.5" />
              </a>
            ) : null}
          </div>
          {isLoading && !selectedGroup ? (
            <div className="flex items-center gap-3 border-t border-subtle px-3 py-6 text-sm text-secondary-text">
              <RefreshCw className="h-4 w-4 animate-spin text-cyan" />
              正在读取公开市场榜单...
            </div>
          ) : selectedGroup?.items.length ? (
            selectedGroup.items.slice(0, 8).map((item) => (
              <MarketRankingRow key={`${selectedGroup.rankType}-${item.code}`} item={item} rankType={selectedGroup.rankType} />
            ))
          ) : (
            <div className="border-t border-subtle px-3 py-6 text-sm text-secondary-text">
              当前榜单暂无可展示条目。公开源失败时不会补造数据。
            </div>
          )}
        </div>
      </Card>

      <Card className="min-w-0" padding="lg">
        <div className="flex items-start justify-between gap-3">
          <div>
            <Badge variant="success" size="md">荐基证据</Badge>
            <h2 className="mt-3 text-xl font-semibold text-foreground">今日市场级候选</h2>
            <p className="mt-2 text-sm leading-6 text-secondary-text">
              候选来自公开榜单，并叠加单品画像和回测准备度；这里仍不输出个人买卖动作。
            </p>
          </div>
          <TrendingUp className="h-5 w-5 shrink-0 text-success" />
        </div>

        {recommendationError ? (
          <div className="mt-4">
            <ApiErrorAlert error={recommendationError} />
          </div>
        ) : null}

        <div className="mt-4 space-y-2">
          {recommendationLoading && !recommendationCandidates.length ? (
            <div className="flex items-center gap-3 rounded-xl border border-subtle bg-surface-2/55 px-3 py-4 text-sm text-secondary-text">
              <RefreshCw className="h-4 w-4 animate-spin text-cyan" />
              正在生成荐基证据卡...
            </div>
          ) : recommendationCandidates.length ? (
            recommendationCandidates.slice(0, 5).map((candidate, index) => (
              <RecommendationEvidenceCard
                key={candidate.code}
                candidate={candidate}
                index={index}
                inPool={poolCodes.has(candidate.code)}
                isAdding={addingCode === candidate.code}
                onAddCandidate={onAddCandidate}
              />
            ))
          ) : marketCandidates.length ? (
            marketCandidates.slice(0, 5).map((candidate, index) => {
              const inPool = poolCodes.has(candidate.code);
              return (
                <div key={candidate.code} className="rounded-xl border border-subtle bg-surface-2/55 px-3 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs font-semibold text-muted-text">#{index + 1}</span>
                        <p className="truncate text-sm font-semibold text-foreground">{candidate.name || `基金${candidate.code}`}</p>
                        <Badge variant="info">{candidate.code}</Badge>
                      </div>
                      <p className="mt-2 text-xs text-secondary-text">
                        证据：{candidate.evidenceRankTypes.map((type) => MARKET_RANK_TYPE_LABELS[type] || type).join(' / ') || '--'}
                      </p>
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="text-[11px] uppercase tracking-[0.18em] text-muted-text">Score</p>
                      <p className="mt-1 text-lg font-semibold text-foreground">{formatNumber(candidate.score, 1)}</p>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Button
                      size="sm"
                      variant={inPool ? 'secondary' : 'primary'}
                      onClick={() => onAddCandidate(candidate, true)}
                      isLoading={addingCode === candidate.code}
                      loadingText={inPool ? '刷新中' : '加入中'}
                    >
                      {inPool ? <RefreshCw className="h-4 w-4" /> : <ListPlus className="h-4 w-4" />}
                      {inPool ? '刷新分析' : '加入并分析'}
                    </Button>
                    <Badge variant={candidate.personalized ? 'success' : 'default'}>
                      {candidate.personalized ? '已个性化' : '市场级'}
                    </Badge>
                  </div>
                </div>
              );
            })
          ) : (
            <div className="rounded-xl border border-dashed border-border/60 bg-card/50 px-3 py-5 text-sm text-secondary-text">
              暂无候选。市场公开源失败时，系统不会生成伪候选。
            </div>
          )}
        </div>

        {recommendations?.limitations?.length ? (
          <div className="mt-4 rounded-xl border border-warning/20 bg-warning/10 px-3 py-3 text-xs leading-5 text-warning">
            {recommendations.limitations[0]}
          </div>
        ) : null}
      </Card>
      </div>
    </section>
  );
};

const PERSONAL_SOURCE_LABELS: Record<string, string> = {
  alipay: '支付宝',
  jd_finance: '京东金融',
  xueqiu: '雪球',
  fund_e_account: '基金E账户',
  other: '其他平台',
};

function personalActionVariant(action: string): 'default' | 'success' | 'warning' | 'danger' | 'info' {
  if (action === 'increase' || action === 'dca') return 'success';
  if (action === 'reduce' || action === 'sell_watch') return 'danger';
  if (action === 'refresh_analysis' || action === 'complete_profile') return 'warning';
  if (action === 'hold') return 'info';
  return 'default';
}

function confidenceVariant(confidence: string): 'default' | 'success' | 'warning' | 'danger' | 'info' {
  if (confidence === 'high') return 'success';
  if (confidence === 'medium') return 'info';
  if (confidence === 'low') return 'warning';
  return 'default';
}

const PersonalActionsPanel: React.FC<{
  actions: FundPersonalActionsResponse | null;
  isLoading: boolean;
  error: ParsedApiError | null;
  onRefresh: () => void;
}> = ({ actions, isLoading, error, onRefresh }) => {
  const summary = actions?.summary || {};
  const holdingCount = readNumber(summary, ['holdingCount', 'holding_count']);
  const actionableCount = readNumber(summary, ['actionableCount', 'actionable_count']);
  const blockerCount = readNumber(summary, ['blockerCount', 'blocker_count']);
  const items = actions?.actions || [];

  return (
    <section className="rounded-[28px] border border-success/15 bg-success/[0.035] p-3 sm:p-4">
      <Card className="min-w-0" padding="lg">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={statusVariant(actions?.status || (isLoading ? 'partial' : null))} size="md">
                {isLoading ? '生成中' : actions?.status === 'actionable' ? '可执行' : actions?.status === 'blocked' ? '阻塞' : actions?.status || '待加载'}
              </Badge>
              <Badge variant="default" size="md">使用确认持仓</Badge>
              <Badge variant="default" size="md">使用账本画像</Badge>
            </div>
            <h2 className="mt-3 text-xl font-semibold text-foreground">个人持仓动作</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-secondary-text">
              这里把确认持仓、账本画像和单品分析合成动作；缺资料时只显示阻塞项。
            </p>
          </div>
          <Button variant="secondary" size="sm" onClick={onRefresh} isLoading={isLoading} loadingText="刷新中">
            <RefreshCw className="h-4 w-4" />
            刷新动作
          </Button>
        </div>

        {error ? (
          <div className="mt-4">
            <ApiErrorAlert error={error} />
          </div>
        ) : null}

        <div className="mt-5 grid grid-cols-3 gap-2">
          <div className="rounded-xl border border-subtle bg-surface-2/55 px-3 py-3">
            <p className="text-[10px] uppercase tracking-[0.14em] text-secondary-text">持仓</p>
            <p className="mt-1 text-xl font-semibold text-foreground">{holdingCount ?? '--'}</p>
          </div>
          <div className="rounded-xl border border-subtle bg-surface-2/55 px-3 py-3">
            <p className="text-[10px] uppercase tracking-[0.14em] text-secondary-text">动作</p>
            <p className="mt-1 text-xl font-semibold text-foreground">{actionableCount ?? '--'}</p>
          </div>
          <div className="rounded-xl border border-subtle bg-surface-2/55 px-3 py-3">
            <p className="text-[10px] uppercase tracking-[0.14em] text-secondary-text">阻塞</p>
            <p className="mt-1 text-xl font-semibold text-foreground">{blockerCount ?? '--'}</p>
          </div>
        </div>

        <div className="mt-4 grid gap-3 xl:grid-cols-2">
          {isLoading && !actions ? (
            <div className="flex items-center gap-3 rounded-xl border border-subtle bg-surface-2/55 px-3 py-5 text-sm text-secondary-text">
              <RefreshCw className="h-4 w-4 animate-spin text-cyan" />
              正在生成个人动作...
            </div>
          ) : items.length ? (
            items.slice(0, 8).map((item) => (
              <div key={`${item.sourcePlatform}-${item.ledgerId}-${item.code}`} className="rounded-2xl border border-subtle bg-surface-2/55 px-3 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="truncate text-sm font-semibold text-foreground">{item.name || `基金${item.code}`}</p>
                      <Badge variant="info">{item.code}</Badge>
                      {item.ledgerName ? <Badge variant="default">{item.ledgerName}</Badge> : null}
                    </div>
                    <p className="mt-2 text-xs text-secondary-text">
                      {item.sourcePlatform ? PERSONAL_SOURCE_LABELS[item.sourcePlatform] || item.sourcePlatform : '未知来源'}
                      {item.analysisAction ? ` · 单品信号 ${item.analysisAction}` : ''}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <Badge variant={personalActionVariant(item.personalAction)}>{item.actionLabel}</Badge>
                    <div className="mt-2">
                      <Badge variant={confidenceVariant(item.confidence)}>{item.confidence}</Badge>
                    </div>
                  </div>
                </div>

                {item.blockerLabels.length ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {item.blockerLabels.slice(0, 3).map((label) => (
                      <Badge key={label} variant="warning">{label}</Badge>
                    ))}
                  </div>
                ) : (
                  <div className="mt-3 rounded-xl border border-success/20 bg-success/10 px-3 py-2 text-xs text-success">
                    已具备确认持仓、账本画像和单品分析，可进入动作复核。
                  </div>
                )}

                {item.invalidIf.length ? (
                  <p className="mt-3 line-clamp-2 text-xs leading-5 text-secondary-text">
                    失效条件：{item.invalidIf.slice(0, 2).join('；')}
                  </p>
                ) : null}
              </div>
            ))
          ) : (
            <div className="rounded-xl border border-dashed border-border/60 bg-card/50 px-3 py-5 text-sm text-secondary-text">
              {actions?.blockerLabels?.length ? actions.blockerLabels.join('；') : '暂无个人动作。'}
            </div>
          )}
        </div>

        {actions?.limitations?.length ? (
          <div className="mt-4 rounded-xl border border-warning/20 bg-warning/10 px-3 py-3 text-xs leading-5 text-warning">
            {actions.limitations[0]}
          </div>
        ) : null}
      </Card>
    </section>
  );
};

const FundLedgerSwitcher: React.FC<{
  ledgers: FundLedger[];
  selectedLedgerId: number | 'all';
  totalCount: number;
  visibleCount: number;
  newLedgerName: string;
  newLedgerColor: string;
  creatingLedger: boolean;
  profileDraft: FundLedgerProfileDraft;
  savingProfile: boolean;
  onSelect: (ledgerId: number | 'all') => void;
  onNameChange: (value: string) => void;
  onColorChange: (value: string) => void;
  onCreate: () => void;
  onProfileChange: (field: keyof FundLedgerProfileDraft, value: string) => void;
  onSaveProfile: () => void;
}> = ({
  ledgers,
  selectedLedgerId,
  totalCount,
  visibleCount,
  newLedgerName,
  newLedgerColor,
  creatingLedger,
  profileDraft,
  savingProfile,
  onSelect,
  onNameChange,
  onColorChange,
  onCreate,
  onProfileChange,
  onSaveProfile,
}) => {
  const selectedLedger = selectedLedgerId === 'all'
    ? null
    : ledgers.find((ledger) => ledger.id === selectedLedgerId) || null;
  const selectedColor = selectedLedger?.color || LEDGER_THEME_COLORS[0];
  const profileFilledCount = Object.values(profileDraft).filter((value) => value.trim()).length;

  return (
    <Card
      className="min-w-0"
      style={{
        borderColor: hexToRgba(selectedColor, 0.45),
        boxShadow: `0 0 0 1px ${hexToRgba(selectedColor, 0.18)} inset`,
      }}
    >
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0 xl:max-w-[520px]">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="default" size="md">我的基金池</Badge>
            <Badge variant="info" size="md">{selectedLedger ? selectedLedger.name : '全部账本'}</Badge>
          </div>
          <h2 className="mt-3 text-xl font-semibold text-foreground">跟踪、回测与后续个人动作</h2>
          <p className="mt-2 text-sm leading-6 text-secondary-text">
            当前显示 {visibleCount} 只，全部基金池 {totalCount} 只。账本只作为筛选和归属，不再承担选基首页主入口。
          </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] xl:w-[460px]">
          <Input
            label="新建账本"
            value={newLedgerName}
            onChange={(event) => onNameChange(event.target.value)}
            placeholder="例如 长期定投、行业主题、观察仓"
            onKeyDown={(event) => {
              if (event.key === 'Enter') onCreate();
            }}
          />
          <Button
            variant="secondary"
            onClick={onCreate}
            isLoading={creatingLedger}
            loadingText="创建中"
            className="w-full sm:w-auto"
          >
            <ListPlus className="h-4 w-4" />
            新建
          </Button>
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
        <div className="overflow-x-auto">
          <div className="flex min-w-max gap-2 pb-1">
          <button
            type="button"
            onClick={() => onSelect('all')}
            className="inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm transition-all hover:bg-hover/60"
            style={{
              borderColor: selectedLedgerId === 'all' ? hexToRgba(LEDGER_THEME_COLORS[0], 0.7) : hexToRgba(LEDGER_THEME_COLORS[0], 0.22),
              background: selectedLedgerId === 'all' ? hexToRgba(LEDGER_THEME_COLORS[0], 0.14) : hexToRgba(LEDGER_THEME_COLORS[0], 0.06),
            }}
          >
            <Layers3 className="h-4 w-4" style={{ color: LEDGER_THEME_COLORS[0] }} />
            <span className="font-semibold text-foreground">全部</span>
            <span className="text-secondary-text">{totalCount}</span>
          </button>
          {ledgers.map((ledger) => {
            const active = selectedLedgerId === ledger.id;
            return (
              <button
                key={ledger.id}
                type="button"
                onClick={() => onSelect(ledger.id)}
                className="inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm transition-all hover:bg-hover/60"
                style={{
                  borderColor: active ? hexToRgba(ledger.color, 0.75) : hexToRgba(ledger.color, 0.24),
                  background: active ? hexToRgba(ledger.color, 0.16) : hexToRgba(ledger.color, 0.06),
                  boxShadow: active ? `0 0 0 1px ${hexToRgba(ledger.color, 0.24)} inset` : undefined,
                }}
              >
                <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: ledger.color }} />
                <span className="max-w-[120px] truncate font-semibold text-foreground">{ledger.name}</span>
                <span className="text-secondary-text">{ledger.fundCount}</span>
              </button>
            );
          })}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 lg:justify-end">
          <span className="text-xs text-muted-text">新账本色</span>
          {LEDGER_THEME_COLORS.map((color) => (
            <button
              key={color}
              type="button"
              aria-label={`选择主题色 ${color}`}
              onClick={() => onColorChange(color)}
              className={`h-6 w-6 rounded-full border transition-all ${newLedgerColor === color ? 'scale-110 border-foreground' : 'border-border/60'}`}
              style={{ backgroundColor: color, boxShadow: newLedgerColor === color ? `0 0 0 4px ${hexToRgba(color, 0.18)}` : undefined }}
            />
          ))}
        </div>
      </div>

      <div className="mt-4 rounded-2xl border border-subtle bg-surface-2/55 px-3 py-3">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="info">画像问卷</Badge>
              <Badge variant={profileFilledCount >= 4 ? 'success' : 'default'}>{profileFilledCount}/6</Badge>
              {selectedLedger ? <Badge variant="default">{selectedLedger.name}</Badge> : null}
            </div>
            <h3 className="mt-2 text-base font-semibold text-foreground">账本画像</h3>
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={onSaveProfile}
            isLoading={savingProfile}
            loadingText="保存中"
            disabled={!selectedLedger}
            className="w-full lg:w-auto"
          >
            <CheckCircle2 className="h-4 w-4" />
            保存画像
          </Button>
        </div>

        {selectedLedger ? (
          <div className="mt-4 grid gap-3 xl:grid-cols-3">
            <Select
              label="账户类型"
              value={profileDraft.accountType}
              onChange={(value) => onProfileChange('accountType', value)}
              options={LEDGER_ACCOUNT_TYPE_OPTIONS}
            />
            <Select
              label="风险目标"
              value={profileDraft.riskTarget}
              onChange={(value) => onProfileChange('riskTarget', value)}
              options={LEDGER_RISK_TARGET_OPTIONS}
            />
            <Select
              label="投资期限"
              value={profileDraft.investmentHorizon}
              onChange={(value) => onProfileChange('investmentHorizon', value)}
              options={LEDGER_HORIZON_OPTIONS}
            />
            <Select
              label="调仓频率"
              value={profileDraft.rebalanceFrequency}
              onChange={(value) => onProfileChange('rebalanceFrequency', value)}
              options={LEDGER_REBALANCE_OPTIONS}
            />
            <Input
              label="资金用途"
              value={profileDraft.purpose}
              onChange={(event) => onProfileChange('purpose', event.target.value)}
              placeholder="例如 教育金、养老、短期现金"
            />
            <label className="flex flex-col text-sm font-medium text-foreground">
              <span className="mb-2">备注</span>
              <textarea
                value={profileDraft.notes}
                onChange={(event) => onProfileChange('notes', event.target.value)}
                maxLength={500}
                rows={3}
                className="input-surface input-focus-glow min-h-[92px] resize-y rounded-xl border bg-transparent px-4 py-2.5 text-sm text-foreground outline-none"
                placeholder="例如 最大回撤容忍、现金流安排、不可触碰资产"
              />
            </label>
          </div>
        ) : (
          <div className="mt-4 rounded-xl border border-dashed border-border/60 bg-card/50 px-3 py-4 text-sm text-secondary-text">
            选择单个账本后可维护画像；全部视图只做汇总，不直接写入个人偏好。
          </div>
        )}
      </div>
    </Card>
  );
};

const FundSearchCard: React.FC<{
  item: FundSearchItem;
  inPool: boolean;
  isAdding: boolean;
  onAdd: (item: FundSearchItem) => void;
}> = ({ item, inPool, isAdding, onAdd }) => {
  const latest = item.latest || {};
  const returns = item.returns || {};
  const peerPercentiles = (item.peer?.percentiles || {}) as Record<string, unknown>;
  const dailyGrowth = latest.dailyGrowthPct ?? null;
  const return3m = periodNumber(returns, '3m');
  const sourceMap = item.dataSources || {};

  return (
    <Card className="min-w-0" hoverable>
      <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0 xl:flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="break-words text-base font-semibold text-foreground">{item.name || `基金${item.code}`}</h3>
            <Badge variant="info">{item.code}</Badge>
            {item.fundType ? <Badge variant="default">{item.fundType}</Badge> : null}
          </div>
          <p className="mt-2 text-xs text-muted-text">
            榜单分类：{item.category || '--'} · 排名：{item.rank ?? '--'} / {item.sampleSize ?? '--'} · 数据日：{formatDate(latest.navDate || undefined)}
          </p>
          <div className="mt-3">
            <FundProfileSummary profile={item.profile} compact />
          </div>
        </div>
        <Button
          variant={inPool ? 'secondary' : 'primary'}
          size="sm"
          onClick={() => onAdd(item)}
          isLoading={isAdding}
          loadingText={inPool ? '刷新中' : '加入中'}
          className="w-full shrink-0 whitespace-nowrap sm:w-auto sm:min-w-[112px]"
        >
          {inPool ? <RefreshCw className="h-4 w-4" /> : <ListPlus className="h-4 w-4" />}
          {inPool ? '刷新分析' : '加入并分析'}
        </Button>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <div className="rounded-xl border border-subtle bg-card/70 px-3 py-3">
          <p className="label-uppercase">最新净值</p>
          <p className="mt-2 text-xl font-semibold text-foreground">{formatNumber(latest.unitNav, 4)}</p>
          <p className={`mt-1 text-sm ${dailyGrowth !== null && dailyGrowth < 0 ? 'text-danger' : 'text-success'}`}>
            日涨幅 {formatPct(dailyGrowth)}
          </p>
        </div>
        <div className="rounded-xl border border-subtle bg-card/70 px-3 py-3">
          <p className="label-uppercase">累计净值</p>
          <p className="mt-2 text-xl font-semibold text-foreground">{formatNumber(latest.accumulatedNav, 4)}</p>
          <p className="mt-1 text-sm text-secondary-text">手续费 {latest.fee || '--'}</p>
        </div>
        <div className="rounded-xl border border-subtle bg-card/70 px-3 py-3">
          <p className="label-uppercase">近期表现</p>
          <p className={`mt-2 text-xl font-semibold ${return3m !== null && return3m < 0 ? 'text-danger' : 'text-foreground'}`}>
            {formatPct(return3m)}
          </p>
          <p className="mt-1 text-sm text-secondary-text">近 3 月榜单收益</p>
        </div>
      </div>

      <div className="mt-4">
        <FundReturnGrid returns={returns} percentiles={peerPercentiles} compact />
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-muted-text">
        <Badge variant="default">名称：{formatSource(sourceMap.metadata)}</Badge>
        <Badge variant="default">净值/收益：{formatSource(sourceMap.returns || sourceMap.latest)}</Badge>
        {item.limitations.length ? <Badge variant="warning">部分字段不可用</Badge> : <Badge variant="success">公开榜单字段可用</Badge>}
      </div>
    </Card>
  );
};

const FundBacktestPanel: React.FC<{
  result?: FundBacktestResponse | null;
  isLoading: boolean;
  onRun: () => void;
}> = ({ result, isLoading, onRun }) => {
  const summary = result?.summary || {};
  const signals = result?.signals || [];
  const status = result?.status || 'not_run';
  const strategyReturn = readNumber(summary, ['strategyReturnPct']);
  const buyHoldReturn = readNumber(summary, ['buyHoldReturnPct']);
  const excessReturn = readNumber(summary, ['excessReturnPct']);
  const drawdown = readNumber(summary, ['maxDrawdownStrategyPct']);
  const hitRate = readNumber(summary, ['hitRatePct']);
  const signalCount = readNumber(summary, ['signalCount']);
  const transactionCount = readNumber(summary, ['transactionCount']);
  const feeDrag = readNumber(summary, ['feeDragPct']);
  const finalValue = readNumber(summary, ['strategyFinalValue']);
  const sampleDays = readNumber(summary, ['sampleDays']);
  const requiredSampleDays = readNumber(summary, ['requiredSampleDays']);
  const recentSignals = signals.slice(-5).reverse();
  const statusVariant = status === 'completed' ? 'success' : status === 'insufficient_data' ? 'warning' : 'default';

  return (
    <Card
      title="策略回测"
      subtitle={result ? `${result.engineVersion} · 本地净值滚动校验` : 'Walk-forward NAV backtest'}
      className="min-w-0"
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={statusVariant} size="md">
              {status === 'completed' ? '已完成' : status === 'insufficient_data' ? '样本不足' : '未运行'}
            </Badge>
            {result ? <Badge variant="default">信号 {formatNumber(signalCount, 0)}</Badge> : null}
            {result ? <Badge variant="default">交易 {formatNumber(transactionCount, 0)}</Badge> : null}
          </div>
          <p className="mt-3 text-sm leading-6 text-secondary-text">
            用每个历史信号日前的净值窗口重新生成动作，再评估后续窗口表现；结果用于校准规则，不代表真实账户收益。
          </p>
        </div>
        <Button
          variant={result ? 'secondary' : 'primary'}
          size="sm"
          onClick={onRun}
          isLoading={isLoading}
          loadingText="回测中"
          className="w-full lg:w-auto"
        >
          <BarChart3 className="h-4 w-4" />
          {result ? '重算回测' : '运行回测'}
        </Button>
      </div>

      {!result ? (
        <div className="mt-4 rounded-2xl border border-dashed border-border/60 bg-card/50 px-4 py-5 text-sm text-secondary-text">
          当前不会自动外部拉取数据；请先刷新分析确保历史净值已缓存，再运行回测。
        </div>
      ) : status === 'insufficient_data' ? (
        <div className="mt-4 rounded-2xl border border-warning/25 bg-warning/10 px-4 py-4 text-sm text-warning">
          本地净值样本 {formatNumber(sampleDays, 0)} 条，当前参数至少需要 {formatNumber(requiredSampleDays, 0)} 条。先刷新历史净值，或降低回测窗口。
        </div>
      ) : (
        <>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-xl border border-cyan/20 bg-card/70 px-3 py-3">
              <p className="label-uppercase">策略收益</p>
              <p className={`mt-2 text-2xl font-semibold ${strategyReturn !== null && strategyReturn < 0 ? 'text-danger' : 'text-foreground'}`}>
                {formatPct(strategyReturn)}
              </p>
              <p className="mt-1 text-xs text-muted-text">期末 {formatCurrency(finalValue)}</p>
            </div>
            <div className="rounded-xl border border-subtle bg-card/70 px-3 py-3">
              <p className="label-uppercase">买入持有</p>
              <p className={`mt-2 text-2xl font-semibold ${buyHoldReturn !== null && buyHoldReturn < 0 ? 'text-danger' : 'text-foreground'}`}>
                {formatPct(buyHoldReturn)}
              </p>
              <p className="mt-1 text-xs text-muted-text">超额 {formatPct(excessReturn)}</p>
            </div>
            <div className="rounded-xl border border-subtle bg-card/70 px-3 py-3">
              <p className="label-uppercase">最大回撤</p>
              <p className="mt-2 text-2xl font-semibold text-foreground">{formatPct(drawdown)}</p>
              <p className="mt-1 text-xs text-muted-text">策略曲线</p>
            </div>
            <div className="rounded-xl border border-subtle bg-card/70 px-3 py-3">
              <p className="label-uppercase">命中率 / 费用</p>
              <p className="mt-2 text-2xl font-semibold text-foreground">{formatPct(hitRate)}</p>
              <p className="mt-1 text-xs text-muted-text">费用拖累 {formatPct(feeDrag)}</p>
            </div>
          </div>

          <div className="mt-4 overflow-x-auto rounded-2xl border border-subtle">
            <div className="min-w-[620px]">
              <div className="grid grid-cols-[0.9fr_0.8fr_0.8fr_0.8fr_0.8fr] gap-2 bg-muted/20 px-3 py-2 text-xs text-muted-text">
                <span>信号日</span>
                <span>动作</span>
                <span>后续收益</span>
                <span>回撤</span>
                <span>结果</span>
              </div>
              {recentSignals.map((signal) => {
                const outcome = readString(signal, ['outcome']);
                return (
                <div
                  key={`${readString(signal, ['signalDate'])}-${readString(signal, ['action'])}`}
                  className="grid grid-cols-[0.9fr_0.8fr_0.8fr_0.8fr_0.8fr] gap-2 border-t border-subtle px-3 py-2 text-xs text-secondary-text"
                >
                  <span className="text-foreground">{formatDate(readString(signal, ['signalDate']) || undefined)}</span>
                  <span>{readString(signal, ['actionLabel']) || '--'}</span>
                  <span>{formatPct(readNumber(signal, ['fundForwardReturnPct']))}</span>
                  <span>{formatPct(readNumber(signal, ['fundForwardDrawdownPct']))}</span>
                  <span>
                    <Badge variant={outcomeVariant(outcome)}>{readString(signal, ['outcomeLabel']) || '--'}</Badge>
                  </span>
                </div>
                );
              })}
            </div>
          </div>

          <div className="mt-4 flex flex-wrap gap-2 text-xs text-muted-text">
            <Badge variant="default">无未来函数</Badge>
            <Badge variant="default">基准：首个信号日买入持有</Badge>
            <Badge variant="default">费用：公开费率静态假设</Badge>
            {result.limitations.slice(0, 2).map((item) => (
              <Badge key={item} variant="warning">{item}</Badge>
            ))}
          </div>
        </>
      )}
    </Card>
  );
};

const FundPeerComparisonPanel: React.FC<{
  peer: Record<string, unknown>;
  returns: Record<string, unknown>;
  percentiles: Record<string, unknown>;
  trendLabel: string;
  riskSource: unknown;
}> = ({ peer, returns, percentiles, trendLabel, riskSource }) => {
  const rank = readNumber(peer, ['rank']);
  const sampleSize = readNumber(peer, ['sampleSize', 'sample_size']);
  const category = readString(peer, ['category']) || '--';
  const rankBasedPercentile = rankPercentile(rank, sampleSize);
  const rows = FUND_RETURN_PERIODS
    .filter((period) => ['1w', '1m', '3m', '6m', '1y', 'ytd'].includes(period.key))
    .map((period) => ({
      ...period,
      value: periodNumber(returns, period.key),
      percentile: periodNumber(percentiles, period.key),
    }));
  const availableRows = rows.filter((row) => row.percentile !== null);
  const primaryRow = rows.find((row) => row.key === '1y' && row.percentile !== null)
    || rows.find((row) => row.key === '3m' && row.percentile !== null)
    || availableRows[0];
  const primaryPercentile = primaryRow?.percentile ?? rankBasedPercentile;
  const primaryTone = PEER_TONE_META[peerTone(primaryPercentile)];
  const strongest = [...availableRows].sort((left, right) => (right.percentile ?? 0) - (left.percentile ?? 0))[0];
  const weakest = [...availableRows].sort((left, right) => (left.percentile ?? 0) - (right.percentile ?? 0))[0];
  const markerLeft = `${Math.max(0, Math.min(100, primaryPercentile ?? 0))}%`;

  return (
    <Card title="同类比较" subtitle={category} className="min-w-0">
      <div className="space-y-4">
        <div className="rounded-2xl border border-subtle bg-surface-2/60 p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={primaryTone.badge} size="md">{primaryTone.label}</Badge>
                <Badge variant="default">排名 {formatRank(rank, sampleSize)}</Badge>
              </div>
              <p className={`mt-3 text-3xl font-semibold ${primaryTone.textClass}`}>
                {formatPeerLead(primaryPercentile)}
              </p>
              <p className="mt-2 text-sm text-secondary-text">
                {primaryRow ? `${primaryRow.label}分位` : '按公开同类排名折算'}，样本 {formatNumber(sampleSize, 0)} 只。
              </p>
            </div>
            <dl className="grid shrink-0 grid-cols-2 gap-3 text-sm sm:text-right">
              <div>
                <dt className="text-muted-text">趋势</dt>
                <dd className="mt-1 text-foreground">{trendLabel}</dd>
              </div>
              <div>
                <dt className="text-muted-text">风险来源</dt>
                <dd className="mt-1 text-foreground">{formatSource(riskSource)}</dd>
              </div>
              <div>
                <dt className="text-muted-text">强项</dt>
                <dd className="mt-1 text-success">{strongest ? `${strongest.shortLabel} ${formatPeerPercentile(strongest.percentile)}` : '--'}</dd>
              </div>
              <div>
                <dt className="text-muted-text">短板</dt>
                <dd className="mt-1 text-warning">{weakest ? `${weakest.shortLabel} ${formatPeerPercentile(weakest.percentile)}` : '--'}</dd>
              </div>
            </dl>
          </div>

          <div className="mt-4">
            <div className="relative h-3 rounded-full bg-surface-2">
              <div
                className={`absolute left-0 top-0 h-3 rounded-full ${primaryTone.fillClass}`}
                style={{ width: markerLeft }}
              />
              <div
                className="absolute top-1/2 h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-background bg-foreground shadow-soft-card"
                style={{ left: markerLeft }}
              />
            </div>
            <div className="mt-2 flex justify-between text-[11px] text-muted-text">
              <span>落后</span>
              <span>中位</span>
              <span>领先</span>
            </div>
          </div>
        </div>

        <div className="space-y-2">
          {rows.map((row) => {
            const tone = PEER_TONE_META[peerTone(row.percentile)];
            const width = `${Math.max(0, Math.min(100, row.percentile ?? 0))}%`;
            return (
              <div key={row.key} className="grid gap-2 rounded-xl border border-subtle bg-card/55 px-3 py-3 sm:grid-cols-[76px_minmax(0,1fr)_92px] sm:items-center">
                <div>
                  <p className="text-sm font-medium text-foreground">{row.shortLabel}</p>
                  <p className={`mt-0.5 text-xs ${row.value !== null && row.value < 0 ? 'text-danger' : 'text-secondary-text'}`}>
                    收益 {formatPct(row.value)}
                  </p>
                </div>
                <div className={`h-3 overflow-hidden rounded-full ${tone.railClass}`}>
                  {row.percentile !== null ? (
                    <div className={`h-full rounded-full ${tone.fillClass}`} style={{ width }} />
                  ) : null}
                </div>
                <div className="flex items-center justify-between gap-2 sm:block sm:text-right">
                  <p className={`text-sm font-semibold ${tone.textClass}`}>{formatPeerPercentile(row.percentile)}</p>
                  <Badge variant={tone.badge}>{tone.label}</Badge>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
};

const FundAnalysisPanel: React.FC<{
  analysis: FundAnalysisSnapshot;
  backtest?: FundBacktestResponse | null;
  isBacktesting: boolean;
  onRunBacktest: () => void;
}> = ({ analysis, backtest, isBacktesting, onRunBacktest }) => {
  const returns = (analysis.metrics.returns || {}) as Record<string, unknown>;
  const peer = analysis.peer || {};
  const peerPercentiles = (peer.percentiles || {}) as Record<string, unknown>;
  const metricSources = (analysis.metrics.metricSources || {}) as Record<string, unknown>;
  const trendState = String(analysis.metrics.trendState || 'unknown');
  const trendLabel = {
    uptrend: '上行',
    sideways: '震荡',
    downtrend: '下行',
    unknown: '未知',
  }[trendState] || trendState;
  const latestNav = metricNumber(analysis.metrics, 'latestNav');
  const drawdown = metricNumber(analysis.metrics, 'maxDrawdown1yPct');
  const volatility = metricNumber(analysis.metrics, 'volatility1yPct');
  const sharpe = metricNumber(analysis.metrics, 'sharpe1y', 'sharpe1Y');
  const peer1y = periodNumber(peerPercentiles, '1y');
  const return1w = periodNumber(returns, '1w');
  const return1m = periodNumber(returns, '1m');
  const return3m = periodNumber(returns, '3m');
  const return1y = periodNumber(returns, '1y');
  const profile = readRecord(analysis.metrics, ['profile']);
  const latestDate = typeof analysis.metrics.latestDate === 'string' ? analysis.metrics.latestDate : analysis.analysisDate;

  return (
    <div className="mt-4 space-y-4">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="最新净值"
          value={latestNav === null ? '--' : latestNav.toFixed(4)}
          hint={`净值日期 ${formatDate(latestDate)}`}
          tone="primary"
          icon={<LineChart className="h-5 w-5" />}
        />
        <StatCard
          label="近期收益"
          value={formatPct(return3m)}
          hint={`1周 ${formatPct(return1w)} · 1月 ${formatPct(return1m)} · 1年 ${formatPct(return1y)}`}
          tone={returnTone(return3m)}
          icon={<BarChart3 className="h-5 w-5" />}
        />
        <StatCard
          label="近 1 年回撤"
          value={formatPct(drawdown)}
          hint={`年化波动 ${formatPct(volatility)}`}
          tone={drawdown !== null && drawdown < -20 ? 'danger' : 'warning'}
          icon={<ShieldAlert className="h-5 w-5" />}
        />
        <StatCard
          label="同类分位"
          value={peer1y === null ? '--' : `${peer1y.toFixed(1)}%`}
          hint={`Sharpe ${formatNumber(sharpe)}`}
          tone={peer1y !== null && peer1y >= 65 ? 'success' : 'default'}
          icon={<Target className="h-5 w-5" />}
        />
      </div>

      <Card title="多周期公开收益" subtitle={formatSource(metricSources.returns)} className="min-w-0">
        <FundReturnGrid returns={returns} percentiles={peerPercentiles} />
      </Card>

      <FundProfilePanel profile={profile} />

      <FundBacktestPanel result={backtest} isLoading={isBacktesting} onRun={onRunBacktest} />

      <div className="grid gap-4 lg:grid-cols-[1.25fr_0.75fr]">
        <Card title="基金类建议" subtitle="Fund signal" className="min-w-0">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={actionVariant(analysis.action)} size="md">{analysis.actionLabel}</Badge>
                <Badge variant={riskTone(analysis.riskLevel)} size="md">风险 {analysis.riskLevel}</Badge>
                <Badge variant={analysis.dataQuality === 'ok' ? 'success' : 'warning'} size="md">
                  数据 {analysis.dataQuality}
                </Badge>
              </div>
              <p className="mt-3 break-words text-sm leading-6 text-secondary-text">{analysis.summary}</p>
            </div>
            <div className="grid shrink-0 grid-cols-2 gap-2 text-right">
              <div>
                <p className="text-xs text-muted-text">信号分</p>
                <p className="text-xl font-semibold text-foreground">{formatNumber(analysis.signalScore, 1)}</p>
              </div>
              <div>
                <p className="text-xs text-muted-text">风险分</p>
                <p className="text-xl font-semibold text-foreground">{formatNumber(analysis.riskScore, 1)}</p>
              </div>
            </div>
          </div>
        </Card>

        <FundPeerComparisonPanel
          peer={peer}
          returns={returns}
          percentiles={peerPercentiles}
          trendLabel={trendLabel}
          riskSource={metricSources.risk}
        />
      </div>

      <FundSignalDiagnostics analysis={analysis} />
    </div>
  );
};

const FundPoolRow: React.FC<{
  item: FundPoolItem;
  ledgers: FundLedger[];
  ledgerById: Map<number, FundLedger>;
  selected: boolean;
  assigningLedgerCode: string | null;
  refreshingCode: string | null;
  onSelect: (fundCode: string) => void;
  onAssignLedger: (fundCode: string, ledgerId: number) => void;
  onRefresh: (fundCode: string) => void;
  onRemove: (fundCode: string) => void;
}> = ({
  item,
  ledgers,
  ledgerById,
  selected,
  assigningLedgerCode,
  refreshingCode,
  onSelect,
  onAssignLedger,
  onRefresh,
  onRemove,
}) => {
  const itemLedger = item.ledgerId ? ledgerById.get(item.ledgerId) : null;
  const itemColor = itemLedger?.color || LEDGER_THEME_COLORS[0];
  const analysis = item.latestAnalysis;
  const returns = (analysis?.metrics.returns || {}) as Record<string, unknown>;
  const return3m = periodNumber(returns, '3m');
  const riskLevel = analysis?.riskLevel || '--';
  const dataQuality = analysis?.dataQuality || 'pending';

  return (
    <div
      className={`rounded-2xl border p-3 transition-colors ${selected ? 'border-cyan/45 bg-cyan/10 shadow-soft-card' : 'border-subtle bg-card/70 hover:bg-hover/45'}`}
      style={{
        borderColor: selected ? hexToRgba(itemColor, 0.62) : hexToRgba(itemColor, 0.22),
        boxShadow: selected ? `0 0 0 1px ${hexToRgba(itemColor, 0.22)} inset` : undefined,
      }}
    >
      <button
        type="button"
        onClick={() => onSelect(item.code)}
        aria-pressed={selected}
        className="w-full min-w-0 text-left"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: itemColor }} />
              <h3 className="min-w-0 truncate text-sm font-semibold text-foreground">
                {item.name || `基金${item.code}`}
              </h3>
              <Badge variant="info">{item.code}</Badge>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-secondary-text">
              {item.fundType ? <Badge variant="default">{item.fundType}</Badge> : null}
              {itemLedger ? (
                <Badge variant="default" style={{ borderColor: hexToRgba(itemColor, 0.5), color: itemColor }}>
                  {itemLedger.name}
                </Badge>
              ) : null}
              <Badge variant={analysis ? actionVariant(analysis.action) : 'default'}>
                {analysis?.actionLabel || '待分析'}
              </Badge>
            </div>
          </div>
          <div className="shrink-0 text-right">
            <p className={`text-base font-semibold ${return3m !== null && return3m < 0 ? 'text-danger' : 'text-foreground'}`}>
              {formatPct(return3m)}
            </p>
            <p className="mt-0.5 text-[11px] text-muted-text">近 3 月</p>
          </div>
        </div>

        <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
          <div className="rounded-xl border border-subtle bg-surface-2/55 px-2 py-2">
            <p className="text-muted-text">风险</p>
            <p className="mt-1 font-semibold text-foreground">{riskLevel}</p>
          </div>
          <div className="rounded-xl border border-subtle bg-surface-2/55 px-2 py-2">
            <p className="text-muted-text">信号</p>
            <p className="mt-1 font-semibold text-foreground">{formatNumber(analysis?.signalScore, 1)}</p>
          </div>
          <div className="rounded-xl border border-subtle bg-surface-2/55 px-2 py-2">
            <p className="text-muted-text">数据</p>
            <p className="mt-1 font-semibold text-foreground">{coverageText(dataQuality)}</p>
          </div>
        </div>
      </button>

      <div className="mt-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center">
        <label className="flex min-w-0 items-center gap-2 rounded-xl border border-subtle bg-background/70 px-2 py-1.5 text-xs text-muted-text">
          账本
          <select
            value={item.ledgerId ?? ''}
            disabled={assigningLedgerCode === item.code || !ledgers.length}
            onChange={(event) => {
              const nextLedgerId = Number(event.target.value);
              if (Number.isFinite(nextLedgerId) && nextLedgerId > 0) {
                onAssignLedger(item.code, nextLedgerId);
              }
            }}
            className="h-8 min-w-0 flex-1 rounded-md border border-border/60 bg-background px-2 text-xs text-foreground outline-none focus:border-cyan/50"
          >
            {!ledgers.length ? <option value="">未建账本</option> : null}
            {ledgers.map((ledger) => (
              <option key={ledger.id} value={ledger.id}>{ledger.name}</option>
            ))}
          </select>
        </label>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => onRefresh(item.code)}
          isLoading={refreshingCode === item.code}
          loadingText="刷新中"
          className="w-full sm:w-auto"
        >
          <RefreshCw className="h-4 w-4" />
          刷新
        </Button>
        <Button
          variant="danger-subtle"
          size="sm"
          onClick={() => onRemove(item.code)}
          aria-label={`移出 ${item.code}`}
          className="w-full sm:w-auto"
        >
          <Trash2 className="h-4 w-4" />
          移出
        </Button>
      </div>
    </div>
  );
};

const FundPoolWorkspace: React.FC<{
  items: FundPoolItem[];
  selectedItem: FundPoolItem | null;
  ledgers: FundLedger[];
  ledgerById: Map<number, FundLedger>;
  selectedLedger: FundLedger | null;
  assigningLedgerCode: string | null;
  refreshingCode: string | null;
  backtestsByCode: Record<string, FundBacktestResponse>;
  backtestingCode: string | null;
  onSelect: (fundCode: string) => void;
  onAssignLedger: (fundCode: string, ledgerId: number) => void;
  onRefresh: (fundCode: string) => void;
  onRemove: (fundCode: string) => void;
  onRunBacktest: (fundCode: string) => void;
}> = ({
  items,
  selectedItem,
  ledgers,
  ledgerById,
  selectedLedger,
  assigningLedgerCode,
  refreshingCode,
  backtestsByCode,
  backtestingCode,
  onSelect,
  onAssignLedger,
  onRefresh,
  onRemove,
  onRunBacktest,
}) => {
  const selectedLedgerName = selectedLedger?.name || '全部账本';
  const selectedAnalysis = selectedItem?.latestAnalysis || null;
  const selectedItemLedger = selectedItem?.ledgerId ? ledgerById.get(selectedItem.ledgerId) : null;
  const selectedColor = selectedItemLedger?.color || selectedLedger?.color || LEDGER_THEME_COLORS[0];

  return (
    <section className="rounded-[28px] border border-success/15 bg-success/[0.035] p-3 sm:p-4">
      <div className="flex flex-col gap-3 border-b border-success/15 pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="success" size="md">个人基金池</Badge>
            <Badge variant="default" size="md">{selectedLedgerName}</Badge>
            <Badge variant="info" size="md">{items.length} 只</Badge>
          </div>
          <h2 className="mt-3 text-xl font-semibold text-foreground">列表筛选，单品深挖</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-secondary-text">
            已添加产品用紧凑列表管理，页面只展开当前选中的基金分析；后续几十只产品也不会把工作台拖成超长清单。
          </p>
        </div>
        <div className="rounded-2xl border border-success/15 bg-background/70 px-3 py-2 text-xs text-secondary-text">
          列表内滚动 · 选中后查看回测与信号
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(300px,0.82fr)_minmax(0,1.65fr)]">
        <aside className="min-w-0 rounded-2xl border border-subtle bg-background/75">
          <div className="flex items-center justify-between gap-3 border-b border-subtle px-3 py-3">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-foreground">已添加产品</p>
              <p className="mt-0.5 text-xs text-muted-text">点击切换详情</p>
            </div>
            <Badge variant="default">{items.length}</Badge>
          </div>
          <div className="max-h-[520px] space-y-2 overflow-y-auto p-2 xl:max-h-[760px]">
            {items.map((item) => (
              <FundPoolRow
                key={item.code}
                item={item}
                ledgers={ledgers}
                ledgerById={ledgerById}
                selected={selectedItem?.code === item.code}
                assigningLedgerCode={assigningLedgerCode}
                refreshingCode={refreshingCode}
                onSelect={onSelect}
                onAssignLedger={onAssignLedger}
                onRefresh={onRefresh}
                onRemove={onRemove}
              />
            ))}
          </div>
        </aside>

        <div
          className="min-w-0 rounded-2xl border bg-background/80 p-3 sm:p-4"
          style={{
            borderColor: hexToRgba(selectedColor, 0.32),
            boxShadow: `0 0 0 1px ${hexToRgba(selectedColor, 0.1)} inset`,
          }}
        >
          {selectedItem ? (
            <>
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="break-words text-lg font-semibold text-foreground">
                      {selectedItem.name || `基金${selectedItem.code}`}
                    </h2>
                    <Badge variant="info">{selectedItem.code}</Badge>
                    {selectedItem.fundType ? <Badge variant="default">{selectedItem.fundType}</Badge> : null}
                    {selectedItemLedger ? (
                      <Badge variant="default" style={{ borderColor: hexToRgba(selectedColor, 0.5), color: selectedColor }}>
                        {selectedItemLedger.name}
                      </Badge>
                    ) : null}
                  </div>
                  <p className="mt-2 text-xs text-muted-text">
                    最近刷新：{formatDateTime(selectedItem.lastRefreshedAt)} · 来源：{selectedItem.source || 'akshare'}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => onRefresh(selectedItem.code)}
                    isLoading={refreshingCode === selectedItem.code}
                    loadingText="刷新中"
                  >
                    <RefreshCw className="h-4 w-4" />
                    刷新分析
                  </Button>
                  <Button
                    variant="danger-subtle"
                    size="sm"
                    onClick={() => onRemove(selectedItem.code)}
                    aria-label={`移出 ${selectedItem.code}`}
                  >
                    <Trash2 className="h-4 w-4" />
                    移出
                  </Button>
                </div>
              </div>

              {selectedAnalysis ? (
                <FundAnalysisPanel
                  analysis={selectedAnalysis}
                  backtest={backtestsByCode[selectedItem.code]}
                  isBacktesting={backtestingCode === selectedItem.code}
                  onRunBacktest={() => onRunBacktest(selectedItem.code)}
                />
              ) : (
                <div className="mt-4 rounded-2xl border border-dashed border-border/60 bg-card/50 px-4 py-5 text-sm text-secondary-text">
                  还没有分析快照。点击“刷新分析”后会拉取净值、生成风险指标和动作信号。
                </div>
              )}
            </>
          ) : (
            <EmptyState
              icon={<LineChart className="h-8 w-8" />}
              title="请选择一只基金"
              description="左侧列表用于快速切换，右侧展示当前基金的完整分析。"
            />
          )}
        </div>
      </div>
    </section>
  );
};

const FundsPage: React.FC = () => {
  const [items, setItems] = useState<FundPoolItem[]>([]);
  const [ledgers, setLedgers] = useState<FundLedger[]>([]);
  const [selectedLedgerId, setSelectedLedgerId] = useState<number | 'all'>('all');
  const [selectedFundCode, setSelectedFundCode] = useState<string | null>(null);
  const [newLedgerName, setNewLedgerName] = useState('');
  const [newLedgerColor, setNewLedgerColor] = useState(LEDGER_THEME_COLORS[1]);
  const [creatingLedger, setCreatingLedger] = useState(false);
  const [ledgerProfileDraft, setLedgerProfileDraft] = useState<FundLedgerProfileDraft>(EMPTY_LEDGER_PROFILE_DRAFT);
  const [savingLedgerProfile, setSavingLedgerProfile] = useState(false);
  const [assigningLedgerCode, setAssigningLedgerCode] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [query, setQuery] = useState('');
  const [searchResults, setSearchResults] = useState<FundSearchItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [addingCode, setAddingCode] = useState<string | null>(null);
  const [refreshingCode, setRefreshingCode] = useState<string | null>(null);
  const [refreshingPool, setRefreshingPool] = useState(false);
  const [marketRankings, setMarketRankings] = useState<FundMarketRankingsResponse | null>(null);
  const [marketLoading, setMarketLoading] = useState(true);
  const [marketError, setMarketError] = useState<ParsedApiError | null>(null);
  const [todayRecommendations, setTodayRecommendations] = useState<FundRecommendationTodayResponse | null>(null);
  const [recommendationLoading, setRecommendationLoading] = useState(true);
  const [recommendationError, setRecommendationError] = useState<ParsedApiError | null>(null);
  const [personalActions, setPersonalActions] = useState<FundPersonalActionsResponse | null>(null);
  const [personalActionsLoading, setPersonalActionsLoading] = useState(true);
  const [personalActionsError, setPersonalActionsError] = useState<ParsedApiError | null>(null);
  const [selectedRankType, setSelectedRankType] = useState<string | null>('etf_net_inflow');
  const [backtestsByCode, setBacktestsByCode] = useState<Record<string, FundBacktestResponse>>({});
  const [backtestingCode, setBacktestingCode] = useState<string | null>(null);

  useEffect(() => {
    document.title = '选基 - DSA';
  }, []);

  const loadPool = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fundsApi.listPool();
      setItems(response.items);
      setLedgers(response.ledgers || []);
      setSelectedLedgerId((current) => (
        current !== 'all' && !response.ledgers.some((ledger) => ledger.id === current)
          ? 'all'
          : current
      ));
      setError(null);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPool();
  }, [loadPool]);

  const loadMarketRankings = useCallback(async () => {
    setMarketLoading(true);
    try {
      const response = await fundsApi.getMarketRankings({ limit: 10, fundType: '全部' });
      setMarketRankings(response);
      setSelectedRankType((current) => (
        current && response.groups.some((group) => group.rankType === current)
          ? current
          : response.groups[0]?.rankType || current
      ));
      setMarketError(null);
    } catch (err) {
      setMarketError(getParsedApiError(err));
    } finally {
      setMarketLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadMarketRankings();
  }, [loadMarketRankings]);

  const loadTodayRecommendations = useCallback(async () => {
    setRecommendationLoading(true);
    try {
      const response = await fundsApi.getTodayRecommendations({ limit: 10, fundType: '全部' });
      setTodayRecommendations(response);
      setRecommendationError(null);
    } catch (err) {
      setRecommendationError(getParsedApiError(err));
    } finally {
      setRecommendationLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTodayRecommendations();
  }, [loadTodayRecommendations]);

  const loadPersonalActions = useCallback(async () => {
    setPersonalActionsLoading(true);
    try {
      const response = await fundsApi.getPersonalActions();
      setPersonalActions(response);
      setPersonalActionsError(null);
    } catch (err) {
      setPersonalActionsError(getParsedApiError(err));
    } finally {
      setPersonalActionsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPersonalActions();
  }, [loadPersonalActions]);

  const poolCodes = useMemo(() => new Set(items.map((item) => item.code)), [items]);
  const ledgerById = useMemo(() => new Map(ledgers.map((ledger) => [ledger.id, ledger])), [ledgers]);
  const selectedLedger = selectedLedgerId === 'all' ? null : ledgerById.get(selectedLedgerId) || null;
  const visibleItems = useMemo(() => {
    if (selectedLedgerId === 'all') return items;
    return items.filter((item) => item.ledgerId === selectedLedgerId);
  }, [items, selectedLedgerId]);
  const selectedSummary = useMemo(() => {
    const actionable = visibleItems.filter((item) => item.latestAnalysis?.action && item.latestAnalysis.action !== 'watch');
    return `${visibleItems.length} 只跟踪中，${actionable.length} 只有明确动作信号`;
  }, [visibleItems]);
  const selectedFundItem = useMemo(() => {
    if (!visibleItems.length) return null;
    return visibleItems.find((item) => item.code === selectedFundCode) || visibleItems[0];
  }, [selectedFundCode, visibleItems]);

  useEffect(() => {
    if (!selectedLedger) {
      setLedgerProfileDraft(EMPTY_LEDGER_PROFILE_DRAFT);
      return;
    }
    setLedgerProfileDraft({
      accountType: selectedLedger.accountType || '',
      purpose: selectedLedger.purpose || '',
      riskTarget: selectedLedger.riskTarget || '',
      investmentHorizon: selectedLedger.investmentHorizon || '',
      rebalanceFrequency: selectedLedger.rebalanceFrequency || '',
      notes: selectedLedger.notes || '',
    });
  }, [selectedLedger]);

  useEffect(() => {
    if (!visibleItems.length) {
      if (selectedFundCode !== null) setSelectedFundCode(null);
      return;
    }
    if (!selectedFundCode || !visibleItems.some((item) => item.code === selectedFundCode)) {
      setSelectedFundCode(visibleItems[0].code);
    }
  }, [selectedFundCode, visibleItems]);

  const handleSearch = async () => {
    const trimmed = query.trim();
    if (!trimmed) {
      setError({
        title: '请输入搜索条件',
        message: '可以输入基金名称、6 位代码或拼音缩写，例如 财通成长、021528、CTCC。',
        rawMessage: '',
        status: 400,
        category: 'http_error',
      });
      return;
    }
    setSearching(true);
    setHasSearched(true);
    try {
      const response = await fundsApi.searchFunds(trimmed, 12);
      setSearchResults(response.items);
      setError(null);
    } catch (err) {
      setSearchResults([]);
      setError(getParsedApiError(err));
    } finally {
      setSearching(false);
    }
  };

  const handleAddFromSearch = async (item: FundSearchItem) => {
    setAddingCode(item.code);
    try {
      if (!poolCodes.has(item.code)) {
        await fundsApi.addToPool({
          code: item.code,
          name: item.name || undefined,
          ledgerId: selectedLedgerId === 'all' ? undefined : selectedLedgerId,
        });
      }
      await fundsApi.refreshFund(item.code);
      setBacktestsByCode((prev) => {
        const next = { ...prev };
        delete next[item.code];
        return next;
      });
      await loadPool();
      setSelectedFundCode(item.code);
      await loadPersonalActions();
      setError(null);
    } catch (err) {
      setError(getParsedApiError(err));
      await loadPool();
    } finally {
      setAddingCode(null);
    }
  };

  const handleAddMarketCandidate = async (candidate: MarketCandidateAddPayload, shouldAnalyze: boolean) => {
    setAddingCode(candidate.code);
    try {
      if (!poolCodes.has(candidate.code)) {
        await fundsApi.addToPool({
          code: candidate.code,
          name: candidate.name || undefined,
          ledgerId: selectedLedgerId === 'all' ? undefined : selectedLedgerId,
          notes: '市场公开榜单候选',
        });
      }
      if (shouldAnalyze) {
        await fundsApi.refreshFund(candidate.code);
      }
      setBacktestsByCode((prev) => {
        const next = { ...prev };
        delete next[candidate.code];
        return next;
      });
      await loadPool();
      setSelectedFundCode(candidate.code);
      await loadTodayRecommendations();
      await loadPersonalActions();
      setError(null);
    } catch (err) {
      setError(getParsedApiError(err));
      await loadPool();
    } finally {
      setAddingCode(null);
    }
  };

  const handleRefreshFund = async (fundCode: string) => {
    setRefreshingCode(fundCode);
    try {
      await fundsApi.refreshFund(fundCode);
      setBacktestsByCode((prev) => {
        const next = { ...prev };
        delete next[fundCode];
        return next;
      });
      await loadPool();
      if (selectedFundCode === fundCode) setSelectedFundCode(null);
      await loadPersonalActions();
      setError(null);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setRefreshingCode(null);
    }
  };

  const handleRefreshPool = async () => {
    setRefreshingPool(true);
    try {
      await fundsApi.refreshPool();
      setBacktestsByCode({});
      await loadPool();
      await loadPersonalActions();
      setError(null);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setRefreshingPool(false);
    }
  };

  const handleRemove = async (fundCode: string) => {
    try {
      await fundsApi.removeFromPool(fundCode);
      setBacktestsByCode((prev) => {
        const next = { ...prev };
        delete next[fundCode];
        return next;
      });
      await loadPool();
      setError(null);
    } catch (err) {
      setError(getParsedApiError(err));
    }
  };

  const handleCreateLedger = async () => {
    const name = newLedgerName.trim();
    if (!name) {
      setError({
        title: '请输入账本名称',
        message: '例如 长期定投、行业主题、观察仓。',
        rawMessage: '',
        status: 400,
        category: 'http_error',
      });
      return;
    }
    setCreatingLedger(true);
    try {
      const ledger = await fundsApi.createLedger({ name, color: newLedgerColor });
      setNewLedgerName('');
      await loadPool();
      setSelectedLedgerId(ledger.id);
      setError(null);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setCreatingLedger(false);
    }
  };

  const handleLedgerProfileChange = (field: keyof FundLedgerProfileDraft, value: string) => {
    setLedgerProfileDraft((prev) => ({ ...prev, [field]: value }));
  };

  const handleSaveLedgerProfile = async () => {
    if (!selectedLedger) return;
    setSavingLedgerProfile(true);
    try {
      await fundsApi.updateLedgerProfile(selectedLedger.id, {
        accountType: ledgerProfileDraft.accountType || null,
        purpose: ledgerProfileDraft.purpose || null,
        riskTarget: ledgerProfileDraft.riskTarget || null,
        investmentHorizon: ledgerProfileDraft.investmentHorizon || null,
        rebalanceFrequency: ledgerProfileDraft.rebalanceFrequency || null,
        notes: ledgerProfileDraft.notes || null,
      });
      await loadPool();
      await loadPersonalActions();
      setError(null);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setSavingLedgerProfile(false);
    }
  };

  const handleAssignLedger = async (fundCode: string, ledgerId: number) => {
    setAssigningLedgerCode(fundCode);
    try {
      await fundsApi.assignLedger(fundCode, ledgerId);
      await loadPool();
      setError(null);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setAssigningLedgerCode(null);
    }
  };

  const handleRunBacktest = async (fundCode: string) => {
    setBacktestingCode(fundCode);
    try {
      const result = await fundsApi.getBacktest(fundCode);
      setBacktestsByCode((prev) => ({ ...prev, [fundCode]: result }));
      setError(null);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setBacktestingCode(null);
    }
  };

  return (
    <AppPage className="space-y-5">
      <PageHeader
        eyebrow="Fund Screening"
        title="选基决策工作台"
        description="先汇总公开市场榜单和荐基候选，再把产品加入基金池做画像、回测和后续个人持仓动作。"
        actions={(
          <Button
            variant="secondary"
            onClick={() => void handleRefreshPool()}
            isLoading={refreshingPool}
            loadingText="刷新中"
            disabled={!items.length}
          >
            <RefreshCw className="h-4 w-4" />
            刷新基金池
          </Button>
        )}
      />

      <MarketRankingWorkbench
        rankings={marketRankings}
        recommendations={todayRecommendations}
        isLoading={marketLoading}
        recommendationLoading={recommendationLoading}
        error={marketError}
        recommendationError={recommendationError}
        selectedRankType={selectedRankType}
        onSelectRankType={setSelectedRankType}
        onRefresh={() => {
          void loadMarketRankings();
          void loadTodayRecommendations();
        }}
        onAddCandidate={(candidate, shouldAnalyze) => void handleAddMarketCandidate(candidate, shouldAnalyze)}
        poolCodes={poolCodes}
        addingCode={addingCode}
      />

      <InlineAlert
        variant="info"
        title="决策分层"
        message="公开榜单只回答“市场上哪些产品值得观察”；加入基金池后才做单品画像和回测；只有用户画像与已确认持仓齐备时，才会进入个人加减仓动作。"
      />

      <section className="rounded-[28px] border border-border/70 bg-surface-2/35 p-3 sm:p-4">
        <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="default" size="md">搜基入口</Badge>
              <Badge variant="info" size="md">加入后分析</Badge>
            </div>
            <p className="mt-2 text-sm text-secondary-text">已知名称或代码时，从这里把产品加入个人基金池。</p>
          </div>
          <p className="text-xs text-muted-text">{selectedSummary}</p>
        </div>

        <Card>
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
            <Input
              label="搜索基金"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="输入基金名称、代码或拼音，例如 财通成长、021528、CTCC"
              onKeyDown={(event) => {
                if (event.key === 'Enter') void handleSearch();
              }}
            />
            <Button onClick={() => void handleSearch()} isLoading={searching} loadingText="搜索中" className="w-full lg:w-auto">
              <SearchIcon className="h-4 w-4" />
              搜索基金
            </Button>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-text">
            <Badge variant="default">搜索直出：名称、净值、日涨幅、多周期收益、排名、费率</Badge>
            <Badge variant="default">入池刷新：回撤、波动、市场估值、交易费用、佐证线索</Badge>
          </div>
        </Card>

        {searching ? (
          <Card className="mt-3">
            <div className="flex items-center gap-3 text-sm text-secondary-text">
              <RefreshCw className="h-4 w-4 animate-spin text-cyan" />
              正在搜索公开基金库和榜单字段...
            </div>
          </Card>
        ) : hasSearched ? (
          <Card title="搜索结果" subtitle={`${searchResults.length} 只匹配`} className="mt-3">
            {searchResults.length ? (
              <div className="grid gap-3 xl:grid-cols-2">
                {searchResults.map((item) => (
                  <FundSearchCard
                    key={item.code}
                    item={item}
                    inPool={poolCodes.has(item.code)}
                    isAdding={addingCode === item.code}
                    onAdd={(next) => void handleAddFromSearch(next)}
                  />
                ))}
              </div>
            ) : (
              <EmptyState
                icon={<SearchIcon className="h-8 w-8" />}
                title="没有找到匹配基金"
                description="换一个基金简称、6 位代码或拼音缩写再试。"
              />
            )}
          </Card>
        ) : null}
      </section>

      {error ? <ApiErrorAlert error={error} onDismiss={() => setError(null)} /> : null}

      <div className="grid gap-3 md:grid-cols-3">
        <StatCard
          label={selectedLedger ? selectedLedger.name : '基金池'}
          value={`${visibleItems.length}`}
          hint={selectedLedger ? '当前账本产品数' : '持续跟踪产品数'}
          tone="primary"
          icon={<Database className="h-5 w-5" />}
        />
        <StatCard
          label="可执行信号"
          value={`${visibleItems.filter((item) => item.latestAnalysis?.action && item.latestAnalysis.action !== 'watch').length}`}
          hint="非观望动作数量"
          tone="success"
          icon={<Sparkles className="h-5 w-5" />}
        />
        <StatCard
          label="数据可用"
          value={`${visibleItems.filter((item) => item.latestAnalysis?.dataQuality === 'ok').length}`}
          hint="最近快照数据质量 ok"
          tone="default"
          icon={<CheckCircle2 className="h-5 w-5" />}
        />
      </div>

      <FundHoldingImportAssistant
        onImported={() => {
          void loadPool();
          void loadPersonalActions();
        }}
      />

      <PersonalActionsPanel
        actions={personalActions}
        isLoading={personalActionsLoading}
        error={personalActionsError}
        onRefresh={() => void loadPersonalActions()}
      />

      <FundLedgerSwitcher
        ledgers={ledgers}
        selectedLedgerId={selectedLedgerId}
        totalCount={items.length}
        visibleCount={visibleItems.length}
        newLedgerName={newLedgerName}
        newLedgerColor={newLedgerColor}
        creatingLedger={creatingLedger}
        profileDraft={ledgerProfileDraft}
        savingProfile={savingLedgerProfile}
        onSelect={setSelectedLedgerId}
        onNameChange={setNewLedgerName}
        onColorChange={setNewLedgerColor}
        onCreate={() => void handleCreateLedger()}
        onProfileChange={handleLedgerProfileChange}
        onSaveProfile={() => void handleSaveLedgerProfile()}
      />

      {loading ? (
        <Card>
          <div className="flex items-center gap-3 text-sm text-secondary-text">
            <RefreshCw className="h-4 w-4 animate-spin text-cyan" />
            正在加载基金池...
          </div>
        </Card>
      ) : visibleItems.length === 0 ? (
        <EmptyState
          icon={<LineChart className="h-8 w-8" />}
          title={items.length === 0 ? '基金池为空' : '当前账本还没有基金'}
          description={items.length === 0 ? '先搜索并加入一只公募基金，再生成净值指标、风险指标和基金类动作信号。' : '可以从搜索结果加入当前账本，或在已有基金卡片上手动切换账本归属。'}
        />
      ) : (
        <FundPoolWorkspace
          items={visibleItems}
          selectedItem={selectedFundItem}
          ledgers={ledgers}
          ledgerById={ledgerById}
          selectedLedger={selectedLedger}
          assigningLedgerCode={assigningLedgerCode}
          refreshingCode={refreshingCode}
          backtestsByCode={backtestsByCode}
          backtestingCode={backtestingCode}
          onSelect={setSelectedFundCode}
          onAssignLedger={(fundCode, ledgerId) => void handleAssignLedger(fundCode, ledgerId)}
          onRefresh={(fundCode) => void handleRefreshFund(fundCode)}
          onRemove={(fundCode) => void handleRemove(fundCode)}
          onRunBacktest={(fundCode) => void handleRunBacktest(fundCode)}
        />
      )}
    </AppPage>
  );
};

export default FundsPage;
