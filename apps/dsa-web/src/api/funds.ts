import apiClient from './index';
import { toCamelCase } from './utils';

export type FundAction =
  | 'buy'
  | 'dca'
  | 'watch'
  | 'pause_buy'
  | 'reduce'
  | 'sell_watch';

export type FundAnalysisSnapshot = {
  id?: number | null;
  code: string;
  name?: string | null;
  fundType?: string | null;
  analysisDate: string;
  action: FundAction | string;
  actionLabel: string;
  riskLevel: string;
  riskScore?: number | null;
  signalScore?: number | null;
  summary?: string | null;
  metrics: Record<string, unknown>;
  peer?: Record<string, unknown> | null;
  reasons: string[];
  dataQuality: string;
  limitations: string[];
  createdAt?: string | null;
};

export type FundPoolItem = {
  id?: number | null;
  code: string;
  name?: string | null;
  fundType?: string | null;
  ledgerId?: number | null;
  source?: string | null;
  active: boolean;
  notes?: string | null;
  lastRefreshedAt?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  latestAnalysis?: FundAnalysisSnapshot | null;
};

export type FundLedger = {
  id: number;
  name: string;
  color: string;
  sortOrder: number;
  isDefault: boolean;
  accountType?: string | null;
  purpose?: string | null;
  riskTarget?: string | null;
  investmentHorizon?: string | null;
  rebalanceFrequency?: string | null;
  drawdownTolerance?: string | null;
  liquidityNeed?: string | null;
  investmentExperience?: string | null;
  monthlyBudget?: number | null;
  cashReserveMonths?: number | null;
  preferredFundTypes?: string | null;
  notes?: string | null;
  active: boolean;
  fundCount: number;
  createdAt?: string | null;
  updatedAt?: string | null;
};

export type FundLedgerProfilePayload = {
  name?: string | null;
  color?: string | null;
  accountType?: string | null;
  purpose?: string | null;
  riskTarget?: string | null;
  investmentHorizon?: string | null;
  rebalanceFrequency?: string | null;
  drawdownTolerance?: string | null;
  liquidityNeed?: string | null;
  investmentExperience?: string | null;
  monthlyBudget?: number | null;
  cashReserveMonths?: number | null;
  preferredFundTypes?: string | null;
  notes?: string | null;
};

export type FundPoolResponse = {
  items: FundPoolItem[];
  ledgers: FundLedger[];
  total: number;
};

export type FundSearchLatest = {
  unitNav?: number | null;
  accumulatedNav?: number | null;
  dailyGrowthPct?: number | null;
  navDate?: string | null;
  purchaseStatus?: string | null;
  redemptionStatus?: string | null;
  fee?: string | null;
};

export type FundSearchItem = {
  code: string;
  name?: string | null;
  fundType?: string | null;
  latest?: FundSearchLatest | null;
  returns: Record<string, unknown>;
  peer?: Record<string, unknown> | null;
  rank?: number | null;
  sampleSize?: number | null;
  category?: string | null;
  profile?: Record<string, unknown>;
  limitations: string[];
  dataSources?: Record<string, unknown>;
};

export type FundSearchResponse = {
  items: FundSearchItem[];
  total: number;
  query: string;
};

export type FundMarketRankingItem = {
  rank: number;
  code: string;
  name?: string | null;
  fundType?: string | null;
  industry?: string | null;
  market?: string | null;
  score?: number | null;
  status: string;
  proxyType?: string | null;
  recommendationRole?: string | null;
  metrics: Record<string, unknown>;
  evidenceMetrics: Record<string, unknown>;
  source: string;
  sourceUrl?: string | null;
  freshness: Record<string, unknown>;
  limitations: string[];
};

export type FundMarketRankingGroup = {
  rankType: string;
  title: string;
  description?: string | null;
  status: string;
  source: string;
  sourceUrl?: string | null;
  freshness: Record<string, unknown>;
  items: FundMarketRankingItem[];
  limitations: string[];
};

export type FundMarketRecommendationCandidate = {
  code: string;
  name?: string | null;
  fundType?: string | null;
  market?: string | null;
  score: number;
  evidenceRankTypes: string[];
  actionHint?: string | null;
  personalized: boolean;
  limitations: string[];
};

export type FundMarketRankingsResponse = {
  schemaVersion: string;
  status: 'completed' | 'partial' | 'failed' | string;
  asOfDate?: string | null;
  fetchedAt: string;
  scope: Record<string, unknown>;
  personalization: Record<string, unknown>;
  groups: FundMarketRankingGroup[];
  recommendationCandidates: FundMarketRecommendationCandidate[];
  limitations: string[];
};

export type FundRecommendationCandidate = {
  code: string;
  name?: string | null;
  fundType?: string | null;
  score?: number | null;
  marketAction: 'research_only' | 'market_watchlist' | 'add_to_pool' | string;
  personalAction?: string | null;
  personalized: boolean;
  sourceRankTypes: string[];
  marketEvidence: Array<Record<string, unknown>>;
  dataQualitySummary: string;
  latestAnalysis?: FundAnalysisSnapshot | null;
  backtestReadiness: Record<string, unknown>;
  riskFlags: string[];
  invalidIf: string[];
  limitations: string[];
};

export type FundRecommendationTodayResponse = {
  schemaVersion: string;
  status: 'completed' | 'partial' | 'failed' | string;
  fetchedAt: string;
  scope: Record<string, unknown>;
  personalization: Record<string, unknown>;
  candidates: FundRecommendationCandidate[];
  marketRankings: Record<string, unknown>;
  limitations: string[];
};

export type FundPersonalActionItem = {
  code: string;
  name?: string | null;
  ledgerId?: number | null;
  ledgerName?: string | null;
  sourcePlatform?: string | null;
  marketValue?: number | null;
  pnlAmount?: number | null;
  pnlPct?: number | null;
  analysisAction?: string | null;
  personalAction: string;
  actionLabel: string;
  confidence: 'low' | 'medium' | 'high' | string;
  profile: Record<string, unknown>;
  positionContext?: Record<string, unknown>;
  calibrationContext?: Record<string, unknown>;
  marketContext?: Record<string, unknown>;
  scoreBreakdown?: Record<string, unknown>;
  suggestedTrade?: Record<string, unknown>;
  decisionTrace?: string[];
  evidence: Record<string, unknown>;
  blockers: string[];
  blockerLabels: string[];
  invalidIf: string[];
  limitations: string[];
};

export type FundPersonalActionsResponse = {
  schemaVersion: string;
  status: 'actionable' | 'partial' | 'blocked' | string;
  fetchedAt: string;
  summary: Record<string, unknown>;
  prerequisites: Record<string, unknown>;
  actions: FundPersonalActionItem[];
  blockers: string[];
  blockerLabels: string[];
  limitations: string[];
};

export type FundNavPoint = {
  code: string;
  date: string;
  unitNav?: number | null;
  accumulatedNav?: number | null;
  dailyGrowthPct?: number | null;
  source?: string | null;
};

export type FundNavHistoryResponse = {
  code: string;
  items: FundNavPoint[];
  total: number;
};

export type FundBacktestResponse = {
  code: string;
  name?: string | null;
  fundType?: string | null;
  status: 'completed' | 'insufficient_data' | string;
  engineVersion: string;
  parameters: Record<string, unknown>;
  summary: Record<string, unknown>;
  signals: Array<Record<string, unknown>>;
  portfolioCurve: Array<Record<string, unknown>>;
  feeAssumptions: Record<string, unknown>;
  methodology: Record<string, unknown>;
  limitations: string[];
};

export type FundPoolRefreshResponse = {
  items: Array<{
    code: string;
    success: boolean;
    analysis?: FundAnalysisSnapshot | null;
    error?: string | null;
  }>;
  successCount: number;
  failureCount: number;
};

export type FundHoldingCandidate = {
  code: string;
  name?: string | null;
  units?: number | null;
  availableUnits?: number | null;
  marketValue?: number | null;
  costAmount?: number | null;
  pnlAmount?: number | null;
  pnlPct?: number | null;
  latestNav?: number | null;
  asOfDate?: string | null;
  confidence: string;
  fieldConfidence: Record<string, string>;
  sourcePlatform: string;
  sourceChannel: string;
  rawIndex?: number | null;
  warnings: string[];
};

export type FundHoldingImportPreviewResponse = {
  schemaVersion: string;
  status: 'completed' | 'partial' | 'blocked' | string;
  sourcePlatform: string;
  sourcePlatformLabel: string;
  candidateCount: number;
  candidates: FundHoldingCandidate[];
  limitations: string[];
};

export type FundHoldingSnapshot = {
  id?: number | null;
  ledgerId: number;
  sourcePlatform: string;
  sourceChannel: string;
  code: string;
  name?: string | null;
  units?: number | null;
  availableUnits?: number | null;
  marketValue?: number | null;
  costAmount?: number | null;
  pnlAmount?: number | null;
  pnlPct?: number | null;
  latestNav?: number | null;
  asOfDate?: string | null;
  confidence: string;
  importedAt?: string | null;
  updatedAt?: string | null;
};

export type FundHoldingConfirmResponse = {
  schemaVersion: string;
  status: string;
  sourcePlatform: string;
  sourcePlatformLabel: string;
  ledger: FundLedger;
  confirmedCount: number;
  skipped: Array<Record<string, string>>;
  changeSummary: Record<string, unknown>;
  items: FundHoldingSnapshot[];
  limitations: string[];
};

export type FundHoldingPortfolioBucket = {
  key?: string | null;
  label?: string | null;
  ledgerId?: number | null;
  holdingCount?: number;
  productCount?: number;
  marketValue?: number | null;
  weightPct?: number | null;
  missingMarketValueCount?: number;
};

export type FundHoldingPortfolioSummary = {
  status: string;
  scope: Record<string, unknown>;
  holdingCount: number;
  productCount: number;
  platformCount: number;
  ledgerCount: number;
  totalMarketValue?: number | null;
  totalCostAmount?: number | null;
  totalPnlAmount?: number | null;
  pnlPct?: number | null;
  amountPrivacySensitive: boolean;
  riskScore?: number | null;
  riskLevel?: string | null;
  riskReasons?: string[];
  concentration: Record<string, unknown>;
  byPlatform: FundHoldingPortfolioBucket[];
  byLedger: FundHoldingPortfolioBucket[];
  dataQuality: Record<string, unknown>;
  riskFlags: string[];
  limitations: string[];
};

export type FundHoldingListResponse = {
  schemaVersion: string;
  status: string;
  items: FundHoldingSnapshot[];
  aggregatedByCode: Array<Record<string, unknown>>;
  portfolioSummary?: FundHoldingPortfolioSummary;
  total: number;
  ledgerId?: number | null;
  limitations: string[];
};

export const fundsApi = {
  async searchFunds(query: string, limit = 20): Promise<FundSearchResponse> {
    const response = await apiClient.get('/api/v1/funds/search', {
      params: { q: query, limit },
      timeout: 60000,
    });
    return toCamelCase<FundSearchResponse>(response.data);
  },

  async listPool(): Promise<FundPoolResponse> {
    const response = await apiClient.get('/api/v1/funds/pool');
    return toCamelCase<FundPoolResponse>(response.data);
  },

  async getMarketRankings(params?: { limit?: number; fundType?: string }): Promise<FundMarketRankingsResponse> {
    const response = await apiClient.get('/api/v1/funds/market-rankings', {
      params: {
        limit: params?.limit ?? 10,
        fund_type: params?.fundType ?? '全部',
      },
      timeout: 70000,
    });
    return toCamelCase<FundMarketRankingsResponse>(response.data);
  },

  async getTodayRecommendations(params?: { limit?: number; fundType?: string }): Promise<FundRecommendationTodayResponse> {
    const response = await apiClient.get('/api/v1/funds/recommendations/today', {
      params: {
        limit: params?.limit ?? 10,
        fund_type: params?.fundType ?? '全部',
      },
      timeout: 70000,
    });
    return toCamelCase<FundRecommendationTodayResponse>(response.data);
  },

  async getPersonalActions(): Promise<FundPersonalActionsResponse> {
    const response = await apiClient.get('/api/v1/funds/personal-actions');
    return toCamelCase<FundPersonalActionsResponse>(response.data);
  },

  async addToPool(payload: { code: string; name?: string; notes?: string; ledgerId?: number | null }): Promise<FundPoolItem> {
    const response = await apiClient.post('/api/v1/funds/pool', {
      code: payload.code,
      name: payload.name,
      notes: payload.notes,
      ledger_id: payload.ledgerId,
    }, { timeout: 60000 });
    return toCamelCase<FundPoolItem>(response.data);
  },

  async createLedger(payload: { name: string; color: string }): Promise<FundLedger> {
    const response = await apiClient.post('/api/v1/funds/ledgers', payload);
    return toCamelCase<FundLedger>(response.data);
  },

  async updateLedgerProfile(ledgerId: number, payload: FundLedgerProfilePayload): Promise<FundLedger> {
    const response = await apiClient.patch(`/api/v1/funds/ledgers/${ledgerId}`, {
      name: payload.name,
      color: payload.color,
      account_type: payload.accountType,
      purpose: payload.purpose,
      risk_target: payload.riskTarget,
      investment_horizon: payload.investmentHorizon,
      rebalance_frequency: payload.rebalanceFrequency,
      drawdown_tolerance: payload.drawdownTolerance,
      liquidity_need: payload.liquidityNeed,
      investment_experience: payload.investmentExperience,
      monthly_budget: payload.monthlyBudget,
      cash_reserve_months: payload.cashReserveMonths,
      preferred_fund_types: payload.preferredFundTypes,
      notes: payload.notes,
    });
    return toCamelCase<FundLedger>(response.data);
  },

  async assignLedger(code: string, ledgerId: number): Promise<FundPoolItem> {
    const response = await apiClient.patch(`/api/v1/funds/pool/${encodeURIComponent(code)}/ledger`, {
      ledger_id: ledgerId,
    });
    return toCamelCase<FundPoolItem>(response.data);
  },

  async removeFromPool(code: string): Promise<{ code: string; removed: boolean }> {
    const response = await apiClient.delete(`/api/v1/funds/pool/${encodeURIComponent(code)}`);
    return toCamelCase<{ code: string; removed: boolean }>(response.data);
  },

  async refreshFund(code: string): Promise<FundAnalysisSnapshot> {
    const response = await apiClient.post(`/api/v1/funds/${encodeURIComponent(code)}/refresh`, {}, { timeout: 120000 });
    return toCamelCase<FundAnalysisSnapshot>(response.data);
  },

  async refreshPool(): Promise<FundPoolRefreshResponse> {
    const response = await apiClient.post('/api/v1/funds/pool/refresh', {}, { timeout: 120000 });
    return toCamelCase<FundPoolRefreshResponse>(response.data);
  },

  async getLatestAnalysis(code: string): Promise<FundAnalysisSnapshot> {
    const response = await apiClient.get(`/api/v1/funds/${encodeURIComponent(code)}/analysis`);
    return toCamelCase<FundAnalysisSnapshot>(response.data);
  },

  async getNavHistory(code: string, limit = 260): Promise<FundNavHistoryResponse> {
    const response = await apiClient.get(`/api/v1/funds/${encodeURIComponent(code)}/nav`, { params: { limit } });
    return toCamelCase<FundNavHistoryResponse>(response.data);
  },

  async getBacktest(code: string, params?: {
    lookbackDays?: number;
    evalWindowDays?: number;
    rebalanceIntervalDays?: number;
    initialCash?: number;
    dcaAmount?: number;
    neutralBandPct?: number;
  }): Promise<FundBacktestResponse> {
    const response = await apiClient.get(`/api/v1/funds/${encodeURIComponent(code)}/backtest`, {
      params: params ? {
        lookback_days: params.lookbackDays,
        eval_window_days: params.evalWindowDays,
        rebalance_interval_days: params.rebalanceIntervalDays,
        initial_cash: params.initialCash,
        dca_amount: params.dcaAmount,
        neutral_band_pct: params.neutralBandPct,
      } : undefined,
      timeout: 60000,
    });
    return toCamelCase<FundBacktestResponse>(response.data);
  },

  async previewHoldingImport(payload: { sourcePlatform: string; ocrText?: string; files?: File[] }): Promise<FundHoldingImportPreviewResponse> {
    const formData = new FormData();
    formData.append('source_platform', payload.sourcePlatform);
    if (payload.ocrText?.trim()) {
      formData.append('ocr_text', payload.ocrText.trim());
    }
    for (const file of payload.files || []) {
      formData.append('files', file);
    }
    const response = await apiClient.post('/api/v1/funds/holding-imports/preview', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    });
    return toCamelCase<FundHoldingImportPreviewResponse>(response.data);
  },

  async confirmHoldingImport(payload: {
    sourcePlatform: string;
    ledgerId?: number | null;
    replace?: boolean;
    holdings: FundHoldingCandidate[];
  }): Promise<FundHoldingConfirmResponse> {
    const response = await apiClient.post('/api/v1/funds/holding-imports/confirm', {
      source_platform: payload.sourcePlatform,
      ledger_id: payload.ledgerId,
      replace: payload.replace ?? true,
      holdings: payload.holdings.map((item) => ({
        code: item.code,
        name: item.name,
        units: item.units,
        available_units: item.availableUnits,
        market_value: item.marketValue,
        cost_amount: item.costAmount,
        pnl_amount: item.pnlAmount,
        pnl_pct: item.pnlPct,
        latest_nav: item.latestNav,
        as_of_date: item.asOfDate,
        confidence: item.confidence,
        field_confidence: item.fieldConfidence || {},
        source_platform: item.sourcePlatform,
        source_channel: item.sourceChannel,
        warnings: item.warnings,
      })),
    }, { timeout: 120000 });
    return toCamelCase<FundHoldingConfirmResponse>(response.data);
  },

  async listHoldings(params?: { ledgerId?: number }): Promise<FundHoldingListResponse> {
    const response = await apiClient.get('/api/v1/funds/holdings', {
      params: params?.ledgerId ? { ledger_id: params.ledgerId } : undefined,
    });
    return toCamelCase<FundHoldingListResponse>(response.data);
  },
};
