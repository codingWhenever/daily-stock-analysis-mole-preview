import type React from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { CheckCircle2, Eye, EyeOff, FileText, RefreshCw, Trash2, Upload } from 'lucide-react';
import {
  fundsApi,
  type FundHoldingCandidate,
  type FundHoldingConfirmResponse,
  type FundHoldingImportPreviewResponse,
  type FundHoldingListResponse,
  type FundHoldingSnapshot,
} from '../../api/funds';
import { getParsedApiError, type ParsedApiError } from '../../api/error';
import { ApiErrorAlert, Badge, Button, InlineAlert, Input } from '../common';

const SOURCE_OPTIONS = [
  { value: 'alipay', label: '支付宝' },
  { value: 'jd_finance', label: '京东金融' },
  { value: 'xueqiu', label: '雪球' },
  { value: 'fund_e_account', label: '基金E账户' },
  { value: 'other', label: '其他平台' },
];

const SOURCE_LABELS = Object.fromEntries(SOURCE_OPTIONS.map((item) => [item.value, item.label]));

type NumberField = 'marketValue' | 'units' | 'costAmount' | 'pnlAmount' | 'pnlPct' | 'latestNav';

function parseNumber(value: string): number | null {
  const trimmed = value.trim().replace(/,/g, '');
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function numberText(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '';
  return Number(value).toFixed(digits).replace(/\.?0+$/, '');
}

function maskedNumber(value: number | null | undefined): string {
  return value === null || value === undefined || Number.isNaN(value) ? '--' : '••••';
}

function exactAmountText(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return `${Number(value).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}元`;
}

function displayExactAmount(value: number | null | undefined, visible: boolean): string {
  return visible ? exactAmountText(value) : maskedNumber(value);
}

function recordText(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  return typeof value === 'string' ? value : '';
}

function recordNumber(record: Record<string, unknown>, key: string): number | null {
  const value = record[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function sourceLabel(value: string | null | undefined): string {
  if (!value) return '未知来源';
  return SOURCE_LABELS[value] || value;
}

function normalizeHoldingImportError(error: unknown): ParsedApiError {
  const parsed = getParsedApiError(error);
  const text = `${parsed.title} ${parsed.message} ${parsed.rawMessage}`.toLowerCase();
  if (parsed.status === 405 || text.includes('method not allowed')) {
    return {
      ...parsed,
      title: '持仓导入接口未接通',
      message: '当前页面没有把 /api 请求正确转发到后端。请确认后端服务已启动，并用 Vite 代理或正确的 VITE_API_URL 打开页面后重试。',
      category: 'local_connection_failed',
    };
  }
  return parsed;
}

export const FundHoldingImportAssistant: React.FC<{
  onImported?: (result: FundHoldingConfirmResponse) => void;
}> = ({ onImported }) => {
  const [sourcePlatform, setSourcePlatform] = useState('alipay');
  const [ocrText, setOcrText] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [preview, setPreview] = useState<FundHoldingImportPreviewResponse | null>(null);
  const [candidates, setCandidates] = useState<FundHoldingCandidate[]>([]);
  const [latestConfirm, setLatestConfirm] = useState<FundHoldingConfirmResponse | null>(null);
  const [holdingsSnapshot, setHoldingsSnapshot] = useState<FundHoldingListResponse | null>(null);
  const [holdingsLoading, setHoldingsLoading] = useState(true);
  const [amountsVisible, setAmountsVisible] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<ParsedApiError | null>(null);

  const selectedSourceLabel = useMemo(
    () => SOURCE_OPTIONS.find((item) => item.value === sourcePlatform)?.label || '其他平台',
    [sourcePlatform],
  );
  const previewStatusTitle = files.length ? '正在识别截图' : '正在解析文本';
  const previewStatusMessage = files.length
    ? `已选择 ${files.length} 张截图，正在提取可确认的持仓候选。`
    : '正在从粘贴文本中提取可确认的持仓候选。';
  const confirmedHoldings = holdingsSnapshot?.items || [];
  const aggregatedHoldings = holdingsSnapshot?.aggregatedByCode || [];
  const canPreview = Boolean(ocrText.trim() || files.length);
  const canConfirm = candidates.length > 0 && candidates.every((item) => /^\d{6}$/.test(item.code));

  const loadHoldings = useCallback(async () => {
    setHoldingsLoading(true);
    try {
      const result = await fundsApi.listHoldings();
      setHoldingsSnapshot(result);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setHoldingsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadHoldings();
  }, [loadHoldings]);

  const updateCandidate = (index: number, patch: Partial<FundHoldingCandidate>) => {
    setCandidates((current) => current.map((item, itemIndex) => (
      itemIndex === index ? { ...item, ...patch } : item
    )));
  };

  const removeCandidate = (index: number) => {
    setCandidates((current) => current.filter((_, itemIndex) => itemIndex !== index));
  };

  const handlePreview = async (override?: { ocrText?: string; files?: File[] }) => {
    const nextOcrText = override?.ocrText ?? ocrText;
    const nextFiles = override?.files ?? files;
    const hasPreviewInput = Boolean(nextOcrText.trim() || nextFiles.length);
    if (!hasPreviewInput) {
      setError({
        title: '没有可解析内容',
        message: '请上传截图，或粘贴 OCR 文本后再预览。',
        rawMessage: '',
        status: 400,
        category: 'http_error',
      });
      return;
    }
    setPreviewing(true);
    setLatestConfirm(null);
    setPreview(null);
    setCandidates([]);
    setError(null);
    try {
      const result = await fundsApi.previewHoldingImport({
        sourcePlatform,
        ocrText: nextOcrText,
        files: nextFiles,
      });
      setPreview(result);
      setCandidates(result.candidates || []);
      setError(null);
    } catch (err) {
      setError(normalizeHoldingImportError(err));
    } finally {
      setPreviewing(false);
    }
  };

  const handleFilesSelected = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(event.target.files || []);
    event.target.value = '';
    setFiles(selectedFiles);
    setPreview(null);
    setCandidates([]);
    setLatestConfirm(null);
    if (selectedFiles.length) {
      void handlePreview({ files: selectedFiles, ocrText });
    }
  };

  const handleConfirm = async () => {
    setConfirming(true);
    try {
      const result = await fundsApi.confirmHoldingImport({
        sourcePlatform,
        holdings: candidates,
        replace: true,
      });
      setLatestConfirm(result);
      setError(null);
      await loadHoldings();
      onImported?.(result);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setConfirming(false);
    }
  };

  const renderNumberInput = (
    item: FundHoldingCandidate,
    index: number,
    field: NumberField,
    label: string,
    suffix = '',
    digits = 2,
  ) => (
    <label className="block min-w-[108px]">
      <span className="text-[11px] text-muted-text">{label}</span>
      {amountsVisible ? (
        <input
          value={numberText(item[field], digits)}
          onChange={(event) => updateCandidate(index, { [field]: parseNumber(event.target.value) })}
          inputMode="decimal"
          className="mt-1 h-9 w-full rounded-lg border border-border/60 bg-background px-2 text-sm text-foreground outline-none focus:border-cyan/50"
          aria-label={`${item.code} ${label}`}
        />
      ) : (
        <div className="mt-1 h-9 rounded-lg border border-border/50 bg-surface-2/60 px-2 py-2 text-sm font-semibold text-secondary-text">
          {maskedNumber(item[field])}{item[field] == null ? '' : suffix}
        </div>
      )}
    </label>
  );

  return (
    <section className="rounded-[28px] border border-warning/15 bg-warning/[0.035] p-3 sm:p-4">
      <div className="flex flex-col gap-3 border-b border-warning/15 pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="warning" size="md">持仓来源</Badge>
            <Badge variant="default" size="md">{selectedSourceLabel}</Badge>
            <Badge variant="info" size="md">确认后入账</Badge>
          </div>
          <h2 className="mt-3 text-xl font-semibold text-foreground">持仓导入助手</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-secondary-text">
            只把确认后的当前持仓写入账本；OCR 候选和原始截图不会作为真实成本收益进入决策。
          </p>
        </div>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => setAmountsVisible((visible) => !visible)}
          aria-pressed={amountsVisible}
        >
          {amountsVisible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          {amountsVisible ? '隐藏金额' : '显示金额'}
        </Button>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[0.82fr_1.18fr]">
        <div className="rounded-2xl border border-subtle bg-background/75 p-3">
          <div className="grid gap-3 sm:grid-cols-[170px_minmax(0,1fr)]">
            <label className="block">
              <span className="mb-2 block text-sm font-medium text-foreground">来源平台</span>
              <select
                value={sourcePlatform}
                onChange={(event) => setSourcePlatform(event.target.value)}
                className="input-surface input-focus-glow h-11 w-full rounded-xl border bg-transparent px-3 text-sm text-foreground outline-none"
              >
                {SOURCE_OPTIONS.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
            </label>
            <Input
              label="截图"
              value={files.length ? `${files.length} 张已选择` : ''}
              readOnly
              placeholder="JPEG / PNG / WebP"
              trailingAction={(
                <label className="inline-flex h-8 cursor-pointer items-center justify-center rounded-lg border border-cyan/30 bg-cyan/10 px-2 text-cyan hover:bg-cyan/15">
                  <Upload className="h-4 w-4" />
                  <input
                    type="file"
                    accept="image/jpeg,image/png,image/webp"
                    multiple
                    className="hidden"
                    onChange={handleFilesSelected}
                  />
                </label>
              )}
            />
          </div>

          <label className="mt-3 block">
            <span className="mb-2 block text-sm font-medium text-foreground">OCR 文本</span>
            <textarea
              value={ocrText}
              onChange={(event) => setOcrText(event.target.value)}
              placeholder="可粘贴截图识别后的持仓文本"
              className="input-surface input-focus-glow min-h-[132px] w-full rounded-xl border bg-transparent px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-text"
            />
          </label>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button
              type="button"
              onClick={() => void handlePreview()}
              isLoading={previewing}
              loadingText="解析中"
              disabled={!canPreview}
            >
              <FileText className="h-4 w-4" />
              预览候选
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                setFiles([]);
                setOcrText('');
                setPreview(null);
                setCandidates([]);
                setLatestConfirm(null);
              }}
            >
              清空
            </Button>
          </div>

          {previewing ? (
            <div
              className="mt-3 flex items-start gap-3 rounded-2xl border border-cyan/20 bg-cyan/10 px-4 py-3 text-cyan"
              role="status"
              aria-live="polite"
            >
              <RefreshCw className="mt-0.5 h-4 w-4 shrink-0 animate-spin" />
              <div className="min-w-0">
                <p className="text-sm font-semibold">{previewStatusTitle}</p>
                <p className="mt-1 text-xs opacity-85">{previewStatusMessage}</p>
              </div>
            </div>
          ) : null}

          {preview?.limitations.length ? (
            <div className="mt-3 space-y-2">
              {preview.limitations.slice(0, 3).map((item) => (
                <InlineAlert key={item} variant={preview.status === 'blocked' ? 'warning' : 'info'} message={item} />
              ))}
            </div>
          ) : null}
          {error ? <div className="mt-3"><ApiErrorAlert error={error} onDismiss={() => setError(null)} /></div> : null}
        </div>

        <div className="min-w-0 rounded-2xl border border-subtle bg-background/75">
          <div className="flex flex-col gap-2 border-b border-subtle px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-semibold text-foreground">确认持仓</p>
              <p className="mt-0.5 text-xs text-muted-text">
                {previewing ? previewStatusTitle : candidates.length ? `${candidates.length} 条候选` : '等待预览结果'}
              </p>
            </div>
            <Button
              type="button"
              size="sm"
              onClick={() => void handleConfirm()}
              isLoading={confirming}
              loadingText="写入中"
              disabled={!canConfirm}
            >
              <CheckCircle2 className="h-4 w-4" />
              确认覆盖
            </Button>
          </div>

          {previewing ? (
            <div className="flex items-center gap-3 px-3 py-10 text-sm text-secondary-text">
              <RefreshCw className="h-4 w-4 animate-spin text-cyan" />
              {previewStatusTitle}，请稍候...
            </div>
          ) : candidates.length ? (
            <div className="overflow-x-auto p-3">
              <div className="min-w-[760px] space-y-2">
                {candidates.map((item, index) => (
                  <div key={`${item.code}-${index}`} className="rounded-2xl border border-subtle bg-card/65 p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="grid min-w-0 flex-1 gap-2 sm:grid-cols-[118px_minmax(180px,1fr)_120px]">
                        <Input
                          label="代码"
                          value={item.code}
                          onChange={(event) => updateCandidate(index, { code: event.target.value.trim() })}
                          maxLength={6}
                        />
                        <Input
                          label="名称"
                          value={item.name || ''}
                          onChange={(event) => updateCandidate(index, { name: event.target.value })}
                        />
                        <label className="block">
                          <span className="mb-2 block text-sm font-medium text-foreground">日期</span>
                          <input
                            value={item.asOfDate || ''}
                            onChange={(event) => updateCandidate(index, { asOfDate: event.target.value || null })}
                            placeholder="YYYY-MM-DD"
                            className="input-surface input-focus-glow h-11 w-full rounded-xl border bg-transparent px-3 text-sm text-foreground outline-none"
                          />
                        </label>
                      </div>
                      <Button
                        type="button"
                        variant="danger-subtle"
                        size="sm"
                        onClick={() => removeCandidate(index)}
                        aria-label={`删除 ${item.code}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>

                    <div className="mt-3 grid gap-2 sm:grid-cols-3 xl:grid-cols-6">
                      {renderNumberInput(item, index, 'marketValue', '市值')}
                      {renderNumberInput(item, index, 'units', '份额')}
                      {renderNumberInput(item, index, 'costAmount', '成本')}
                      {renderNumberInput(item, index, 'pnlAmount', '收益')}
                      {renderNumberInput(item, index, 'pnlPct', '收益率', '%')}
                      {renderNumberInput(item, index, 'latestNav', '净值', '', 4)}
                    </div>

                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <Badge variant={item.confidence === 'high' || item.confidence === 'user_confirmed' ? 'success' : item.confidence === 'low' ? 'warning' : 'default'}>
                        {item.confidence}
                      </Badge>
                      {item.warnings?.map((warning) => (
                        <Badge key={warning} variant="warning">{warning}</Badge>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="px-3 py-10 text-sm text-secondary-text">
              上传截图或粘贴 OCR 文本后，这里会出现可编辑的持仓候选。
            </div>
          )}
        </div>
      </div>

      {latestConfirm ? (
        <InlineAlert
          className="mt-3"
          variant="success"
          title={`${latestConfirm.sourcePlatformLabel} 已导入`}
          message={`写入 ${latestConfirm.confirmedCount} 条确认持仓，默认进入 ${latestConfirm.ledger.name}。`}
        />
      ) : null}

      <div className="mt-4 rounded-2xl border border-subtle bg-background/75">
        <div className="flex flex-col gap-3 border-b border-subtle px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="info">已确认持仓</Badge>
              <Badge variant="default">{confirmedHoldings.length} 条明细</Badge>
              <Badge variant="default">{aggregatedHoldings.length} 只产品</Badge>
            </div>
            <p className="mt-2 text-sm text-secondary-text">全部视图按基金代码聚合，各平台账本明细保持分开。</p>
          </div>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => void loadHoldings()}
            isLoading={holdingsLoading}
            loadingText="刷新中"
          >
            <RefreshCw className="h-4 w-4" />
            刷新持仓
          </Button>
        </div>

        {holdingsLoading && !holdingsSnapshot ? (
          <div className="flex items-center gap-3 px-3 py-8 text-sm text-secondary-text">
            <RefreshCw className="h-4 w-4 animate-spin text-cyan" />
            正在读取确认持仓...
          </div>
        ) : confirmedHoldings.length ? (
          <div className="p-3">
            <div className="grid gap-2 lg:grid-cols-2 xl:grid-cols-4">
              {aggregatedHoldings.slice(0, 8).map((item) => {
                const code = recordText(item, 'code');
                const name = recordText(item, 'name');
                const marketValue = recordNumber(item, 'marketValue');
                const costAmount = recordNumber(item, 'costAmount');
                const pnlAmount = recordNumber(item, 'pnlAmount');
                const sourceBreakdown = Array.isArray(item.sourceBreakdown) ? item.sourceBreakdown : [];
                return (
                  <div key={code} className="rounded-xl border border-subtle bg-card/65 px-3 py-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-foreground">{name || `基金${code}`}</p>
                        <p className="mt-1 text-xs text-muted-text">{code}</p>
                      </div>
                      <Badge variant="default">{sourceBreakdown.length} 源</Badge>
                    </div>
                    <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                      <div>
                        <p className="text-muted-text">市值</p>
                        <p className="mt-1 font-semibold text-foreground">{displayExactAmount(marketValue, amountsVisible)}</p>
                      </div>
                      <div>
                        <p className="text-muted-text">成本</p>
                        <p className="mt-1 font-semibold text-foreground">{displayExactAmount(costAmount, amountsVisible)}</p>
                      </div>
                      <div>
                        <p className="text-muted-text">盈亏</p>
                        <p className={`mt-1 font-semibold ${pnlAmount !== null && pnlAmount < 0 ? 'text-danger' : 'text-success'}`}>
                          {displayExactAmount(pnlAmount, amountsVisible)}
                        </p>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="mt-3 overflow-x-auto rounded-xl border border-subtle">
              <div className="min-w-[880px]">
                <div className="grid grid-cols-[120px_minmax(200px,1fr)_120px_130px_130px_120px_130px] gap-2 bg-surface-2/70 px-3 py-2 text-xs font-semibold text-muted-text">
                  <span>来源</span>
                  <span>基金</span>
                  <span>日期</span>
                  <span>市值</span>
                  <span>成本</span>
                  <span>份额</span>
                  <span>收益</span>
                </div>
                {confirmedHoldings.slice(0, 24).map((item: FundHoldingSnapshot) => (
                  <div
                    key={`${item.sourcePlatform}-${item.ledgerId}-${item.code}-${item.id || item.updatedAt || item.importedAt}`}
                    className="grid grid-cols-[120px_minmax(200px,1fr)_120px_130px_130px_120px_130px] gap-2 border-t border-subtle px-3 py-2 text-sm"
                  >
                    <span className="truncate text-secondary-text">{sourceLabel(item.sourcePlatform)}</span>
                    <span className="truncate font-medium text-foreground">{item.name || `基金${item.code}`} · {item.code}</span>
                    <span className="text-secondary-text">{item.asOfDate || '--'}</span>
                    <span className="font-semibold text-foreground">{displayExactAmount(item.marketValue, amountsVisible)}</span>
                    <span className="font-semibold text-foreground">{displayExactAmount(item.costAmount, amountsVisible)}</span>
                    <span className="text-secondary-text">{amountsVisible ? numberText(item.units) || '--' : maskedNumber(item.units)}</span>
                    <span className={item.pnlAmount !== null && item.pnlAmount !== undefined && item.pnlAmount < 0 ? 'text-danger' : 'text-success'}>
                      {displayExactAmount(item.pnlAmount, amountsVisible)}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {holdingsSnapshot?.limitations?.length ? (
              <InlineAlert className="mt-3" variant="info" message={holdingsSnapshot.limitations[0]} />
            ) : null}
          </div>
        ) : (
          <div className="px-3 py-8 text-sm text-secondary-text">
            暂无确认持仓。导入并确认后，这里会展示系统当前用于后续决策的持仓快照。
          </div>
        )}
      </div>
    </section>
  );
};
