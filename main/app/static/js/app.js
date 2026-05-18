/* ── Opus Lease Summary Assistant — Frontend ─────────────────────────────── */
'use strict';

const API = '';  // same origin
const CUSTOM_MODEL_VALUE = '__custom__';
const PROVIDER_ORDER = [
  'openai',
  'google',
  'xai',
  'groq',
  'together',
  'fireworks',
  'openrouter',
  'deepseek',
  'moonshot',
  'lmstudio',
  'ollama',
  'custom',
];

const PROVIDER_CATALOG = {
  openai: {
    label: 'OpenAI',
    baseUrl: 'https://api.openai.com/v1',
    requiresKey: true,
    keyPlaceholder: 'sk-…',
    defaultModel: 'gpt-5.4-mini',
  },
  google: {
    label: 'Google Gemini',
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
    requiresKey: true,
    keyPlaceholder: 'AIza…',
    defaultModel: 'gemini-2.5-pro',
  },
  xai: {
    label: 'xAI',
    baseUrl: 'https://api.x.ai/v1',
    requiresKey: true,
    keyPlaceholder: 'xai-…',
    defaultModel: 'grok-4',
  },
  groq: {
    label: 'Groq',
    baseUrl: 'https://api.groq.com/openai/v1',
    requiresKey: true,
    keyPlaceholder: 'gsk_…',
    defaultModel: 'openai/gpt-oss-120b',
  },
  together: {
    label: 'Together AI',
    baseUrl: 'https://api.together.xyz/v1',
    requiresKey: true,
    keyPlaceholder: 'together-…',
    defaultModel: 'openai/gpt-oss-20b',
  },
  fireworks: {
    label: 'Fireworks AI',
    baseUrl: 'https://api.fireworks.ai/inference/v1',
    requiresKey: true,
    keyPlaceholder: 'fw_…',
    defaultModel: 'accounts/fireworks/routers/kimi-k2p5-turbo',
  },
  openrouter: {
    label: 'OpenRouter',
    baseUrl: 'https://openrouter.ai/api/v1',
    requiresKey: true,
    keyPlaceholder: 'sk-or-…',
    defaultModel: 'openai/gpt-5.2',
  },
  deepseek: {
    label: 'DeepSeek',
    baseUrl: 'https://api.deepseek.com',
    requiresKey: true,
    keyPlaceholder: 'sk-…',
    defaultModel: 'deepseek-chat',
  },
  moonshot: {
    label: 'Moonshot',
    baseUrl: 'https://api.moonshot.cn/v1',
    requiresKey: true,
    keyPlaceholder: 'sk-…',
    defaultModel: 'kimi-k2.5',
  },
  lmstudio: {
    label: 'LM Studio (Local)',
    baseUrl: 'http://127.0.0.1:1234/v1',
    requiresKey: false,
    keyPlaceholder: '',
    defaultModel: '',
  },
  ollama: {
    label: 'Ollama',
    baseUrl: 'http://127.0.0.1:11434/v1',
    requiresKey: false,
    keyPlaceholder: '',
    defaultModel: '',
  },
  custom: {
    label: 'Custom OpenAI-compatible',
    baseUrl: '',
    requiresKey: true,
    keyPlaceholder: 'sk-…',
    models: [],
  },
};

// ── Translations ──────────────────────────────────────────────────────────────
const TRANSLATIONS = {
  en: {
    appTitle:        'Lease Summary Assistant',
    appSubtitle:     'Opus Property Advisers · Hong Kong',
    // mode
    modeStandard:    'Standard',
    modeAI:          'AI Enhanced',
    // hero
    heroTitle:       'Lease Summary Assistant',
    heroSubtitle:    'Upload a lease PDF or Word document to populate the Opus HK summary template.',
    // upload cards
    reviewTitle:     'Review & Export',
    reviewDesc:      'Upload a single lease PDF or Word document for interactive review, AI Q&A, and Excel export.',
    selectPDF:       'Select PDF or Word',
    batchTitle:      'Batch Export',
    batchDesc:       'Upload one or more lease PDFs or Word documents and download Excel summaries in one go.',
    selectPDFs:      'Select PDFs or Word docs',
    addMore:         '+ Add More',
    exportAll:       'Export All & Download',
    dropHere:        'Drop PDF or Word here',
    dropHereMulti:   'Drop PDFs or Word docs here',
    // toolbar
    newLease:        'New',
    // tabs
    tabSummary:      'Summary',
    tabChat:         'Chat',
    tabExport:       'Export',
    // export tab
    exportTitle:     'Ready to Export',
    exportSubtitle:  'All extracted fields will be written to the Opus Excel template.',
    exportEmpty:     'Upload a lease to enable export.',
    exportDocType:   'Document Type',
    exportPages:     'Pages',
    exportFields:    'Fields Extracted',
    exportConfidence:'Avg. Confidence',
    exportFlagged:   'Flagged for Review',
    exportNone:      'None',
    exportIncluded:  'Included in this export',
    exportSecParties:    'Parties',
    exportSecPremises:   'Premises',
    exportSecTerm:       'Lease Term',
    exportSecFinancials: 'Financials',
    exportSecClauses:    'Clauses',
    downloadExcel:   'Download Excel',
    exportHint:      'Output saved as .xlsx · Opus Property Advisers template',
    // chat
    chatEmptyMsg:    'Ask anything about this lease — dates, clauses, financials.',
    chatPlaceholder: 'Ask about this lease…',
    chatNoKey:       'Configure an LLM provider in Settings to enable AI Q&A.',
    chatSugg1:       'When does the lease expire?',
    chatSugg2:       'What is the monthly rent?',
    chatSugg3:       'Is there a break clause or rent-free period?',
    chatSugg4:       'Summarise the restoration obligations.',
    // summary meta
    metaType:        'Type',
    metaPages:       'Pages',
    editBtn:         'Edit',
    saveBtn:         'Save',
    cancelBtn:       'Cancel',
    notDetected:     'not detected',
    sectionParties:  'Parties',
    sectionPremises: 'Premises',
    sectionTerm:     'Lease Term',
    sectionFinancials:'Financials',
    sectionClauses:  'Clauses',
    // settings
    settingsTitle:   'Settings',
    providerLabel:   'LLM Provider',
    providerHint:    'OpenAI-compatible providers only. Choose the backend for AI clause extraction and Q&A.',
    apiKeyLabel:     'LLM API Key',
    apiKeyHint:      'Saved separately for each provider. Leave blank for LM Studio, Ollama, or localhost URLs.',
    baseUrlLabel:    'Base URL',
    baseUrlHint:     'Defaults to the provider\'s official endpoint. Edit only if you need a custom OpenAI-compatible URL.',
    modelLabel:      'Model',
    modelHint:       'Choose a provider model or enter a custom model ID.',
    modelCustomOption:'Custom model…',
    customModelHint: 'Enter a model ID that is not listed above.',
    reloadModels:    'Reload',
    modelStatusLoading: 'Loading models from the selected provider…',
    modelStatusLive: 'Loaded live models from the selected provider.',
    modelStatusFallback: 'No live models detected. Showing the default model only.',
    modelStatusNeedsKey: 'No API key detected — enter a key and click Reload to fetch available models.',
    modelStatusEnterBaseUrl: 'Enter a base URL to load models from this endpoint.',
    modelStatusSelectProvider: 'Select a provider to load available models.',
    modelStatusUnavailable: 'No models detected. Enter a custom model ID if needed.',
    modeLabel:       'Analysis Mode',
    modeHint:        'AI Enhanced uses your configured provider to improve clause extraction.',
    modalCancel:     'Cancel',
    modalSave:       'Save',
    showKey:         'Show key',
    hideKey:         'Hide key',
    // progress
    progressAnalyse: 'Analysing lease…',
    progressBatch:   'Processing leases…',
    stepExtract:     'Extracting text',
    stepAnalyse:     'Detecting fields',
    stepGenerate:    'Generating summary',
    // batch status
    batchPending:    'Pending',
    batchDone:       'Done',
    batchError:      'Error',
    // toast
    uploadError:     'Upload failed',
    batchErrorMsg:   'Batch export failed',
    // lang toggle label (shows the OTHER language)
    langToggle:      '中文',
  },
  'zh-HK': {
    appTitle:        '租約摘要助手',
    appSubtitle:     'Opus 物業顧問 · 香港',
    modeStandard:    '標準',
    modeAI:          'AI 增強',
    heroTitle:       '租約摘要助手',
    heroSubtitle:    '上載租約 PDF，自動填入 Opus HK 摘要範本。',
    reviewTitle:     '審閱及匯出',
    reviewDesc:      '上傳單份租約 PDF，進行互動審閱、AI 問答及 Excel 匯出。',
    selectPDF:       '選擇 PDF',
    batchTitle:      '批量匯出',
    batchDesc:       '上傳一份或多份租約 PDF 或 Word 文件，一次性下載 Excel 摘要。',
    selectPDFs:      '選擇 PDF 或 Word',
    addMore:         '+ 新增文件',
    exportAll:       '全部匯出並下載',
    dropHere:        '將 PDF 或 Word 拖放至此',
    dropHereMulti:   '將 PDF 或 Word 拖放至此',
    newLease:        '新增',
    tabSummary:      '摘要',
    tabChat:         '對話',
    tabExport:       '匯出',
    exportTitle:     '可以匯出',
    exportSubtitle:  '所有擷取到的欄位將寫入 Opus Excel 範本。',
    exportEmpty:     '請先上載租約以啟用匯出功能。',
    exportDocType:   '文件類型',
    exportPages:     '頁數',
    exportFields:    '已擷取欄位',
    exportConfidence:'平均信心度',
    exportFlagged:   '待人手覆核',
    exportNone:      '無',
    exportIncluded:  '本次匯出包含內容',
    exportSecParties:    '訂約方',
    exportSecPremises:   '物業',
    exportSecTerm:       '租約期限',
    exportSecFinancials: '財務',
    exportSecClauses:    '條款',
    downloadExcel:   '下載 Excel',
    exportHint:      '輸出格式為 .xlsx · Opus 物業顧問範本',
    chatEmptyMsg:    '詢問任何關於此租約的問題 — 日期、條款、財務。',
    chatPlaceholder: '詢問此租約相關問題…',
    chatNoKey:       '請在設定中配置 LLM 供應商以啟用 AI 問答。',
    chatSugg1:       '租約何時屆滿？',
    chatSugg2:       '每月租金是多少？',
    chatSugg3:       '是否有提早終止條款或免租期？',
    chatSugg4:       '請總結復原責任條款。',
    metaType:        '類型',
    metaPages:       '頁數',
    editBtn:         '編輯',
    saveBtn:         '儲存',
    cancelBtn:       '取消',
    notDetected:     '未擷取',
    sectionParties:  '訂約方',
    sectionPremises: '物業',
    sectionTerm:     '租約期限',
    sectionFinancials:'財務',
    sectionClauses:  '條款',
    settingsTitle:   '設定',
    providerLabel:   'LLM 供應商',
    providerHint:    '只列出 OpenAI 相容供應商。選擇 AI 條款擷取及問答所使用的後端。',
    apiKeyLabel:     'LLM API 金鑰',
    apiKeyHint:      '每個供應商分開儲存金鑰；LM Studio、Ollama 或 localhost URL 可留空。',
    baseUrlLabel:    'Base URL',
    baseUrlHint:     '預設為供應商官方端點；只有在你需要自訂 OpenAI 相容 URL 時才修改。',
    modelLabel:      '模型',
    modelHint:       '選擇供應商模型，或輸入自訂模型 ID。',
    modelCustomOption:'自訂模型…',
    customModelHint: '如上方未列出所需模型，請輸入模型 ID。',
    reloadModels:    '重新載入',
    modelStatusLoading: '正在從所選供應商載入模型…',
    modelStatusLive: '已從所選供應商載入即時模型列表。',
    modelStatusFallback: '未能檢測到可用模型，僅顯示預設模型。',
    modelStatusNeedsKey: '未檢測到 API 金鑰 — 請輸入金鑰後按重新載入以獲取可用模型。',
    modelStatusEnterBaseUrl: '請先輸入 Base URL 才能載入模型。',
    modelStatusSelectProvider: '請選擇供應商以載入可用模型。',
    modelStatusUnavailable: '未檢測到可用模型；如有需要可手動輸入模型 ID。',
    modeLabel:       '分析模式',
    modeHint:        'AI 增強模式會使用您配置的供應商提升條款擷取效果。',
    modalCancel:     '取消',
    modalSave:       '儲存',
    showKey:         '顯示金鑰',
    hideKey:         '隱藏金鑰',
    progressAnalyse: '正在分析租約…',
    progressBatch:   '正在處理租約…',
    stepExtract:     '正在擷取文字',
    stepAnalyse:     '正在偵測欄位',
    stepGenerate:    '正在生成摘要',
    batchPending:    '待處理',
    batchDone:       '完成',
    batchError:      '錯誤',
    uploadError:     '上傳失敗',
    batchErrorMsg:   '批量匯出失敗',
    langToggle:      'EN',
  },
};

// ── State ─────────────────────────────────────────────────────────────────────
let settings   = {
  api_key: '',
  api_keys: {},
  mode: 'regex',
  llm_provider: '',
  llm_base_url: '',
  llm_model: '',
};
let settingsForm = null;
let pdfDoc     = null;
let currentPage = 1;
let summaryData = null;
let chatBusy    = false;
let pdfScale      = 1.2;
let pageObserver  = null;
let batchFiles    = [];
let ocrWordData   = null;  // {pages: {pageNum: [[x0,y0,x1,y1,word], ...]}} for OCR PDFs
let currentLang = localStorage.getItem('opus_lang') || 'en';
let activeUploadController = null;
let _progressTimers = [];
let modelLoadState = {
  available: [],
  statusKey: 'modelStatusFallback',
  tone: '',
  loading: false,
};

// ── Init ──────────────────────────────────────────────────────────────────────
(async () => {
  resetProgressOverlay();
  installGlobalErrorHandlers();
  try {
    await loadSettings();
    applySettings();
    applyI18n();
    bindEvents();
  } catch (err) {
    hideProgress();
    showToast(`Startup failed: ${err.message || err}`, 'error', 9000);
  }
})();

window.addEventListener('pageshow', () => resetProgressOverlay());

// ── i18n ──────────────────────────────────────────────────────────────────────
function t(key) {
  return TRANSLATIONS[currentLang]?.[key] ?? TRANSLATIONS.en[key] ?? key;
}

function applyI18n() {
  document.documentElement.lang = currentLang;
  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
  document.getElementById('btn-lang').textContent = t('langToggle');
  const provider = normaliseProviderId(document.getElementById('input-provider')?.value || settings.llm_provider);
  const baseUrl = getConfiguredBaseUrl(provider, document.getElementById('input-base-url')?.value || settings.llm_base_url);
  renderProviderOptions(provider);
  renderModelOptions(
    modelLoadState.available.length
      ? modelLoadState.available
      : [getProviderConfig(provider).defaultModel].filter(Boolean),
    sanitizeModelForProvider(
      provider,
      getSelectedModelValue() || settings.llm_model || getDefaultModel(provider),
      baseUrl,
    ),
  );
  renderModelStatus();
  setModeBadgeText();
  // Re-render dynamic content
  if (summaryData && !editMode) _drawSummary(summaryData);
  if (summaryData) renderExport(summaryData);
  renderChatSuggestions();
}

function setModeBadgeText() {
  const el = document.getElementById('mode-badge-text');
  if (el) el.textContent = settings.mode === 'llm' ? t('modeAI') : t('modeStandard');
}

function normaliseApiKeys(apiKeys) {
  const result = {};
  if (!apiKeys || typeof apiKeys !== 'object') return result;
  Object.entries(apiKeys).forEach(([provider, apiKey]) => {
    const providerId = (provider || '').toString().trim().toLowerCase();
    const value = (apiKey || '').toString().trim();
    if (providerId && value) result[providerId] = value;
  });
  return result;
}

function normaliseSettings(raw = {}) {
  const provider = normaliseProviderId(raw.llm_provider || '');
  const apiKeys = normaliseApiKeys(raw.api_keys);
  const baseUrl = (raw.llm_base_url || '').toString().trim();
  const configuredBaseUrl = getConfiguredBaseUrl(provider, baseUrl);
  const legacyKey = (raw.api_key || '').toString().trim();
  if (legacyKey && providerUsesApiKey(provider, configuredBaseUrl) && !apiKeys[provider]) {
    apiKeys[provider] = legacyKey;
  }
  if (!providerUsesApiKey(provider, configuredBaseUrl)) {
    delete apiKeys[provider];
  }
  const model = sanitizeModelForProvider(
    provider,
    (raw.llm_model || '').toString().trim(),
    configuredBaseUrl,
  );

  return {
    api_key: apiKeys[provider] || '',
    api_keys: apiKeys,
    mode: raw.mode || 'regex',
    llm_provider: provider,
    llm_base_url: baseUrl,
    llm_model: model,
  };
}

function cloneSettings(config = settings) {
  return normaliseSettings({
    ...config,
    api_keys: { ...normaliseApiKeys(config.api_keys) },
  });
}

function getProviderApiKey(providerId, config = settings) {
  return normaliseApiKeys(config.api_keys)[normaliseProviderId(providerId)] || '';
}

function setProviderApiKey(providerId, apiKey, config) {
  const provider = normaliseProviderId(providerId);
  const nextApiKeys = { ...normaliseApiKeys(config.api_keys) };
  const value = (apiKey || '').trim();
  if (value) nextApiKeys[provider] = value;
  else delete nextApiKeys[provider];
  config.api_keys = nextApiKeys;
  if (normaliseProviderId(config.llm_provider) === provider) config.api_key = value;
}

async function loadSettings() {
  try {
    const r = await fetch(`${API}/api/settings`);
    settings = normaliseSettings(await r.json());
  } catch (_) {
    settings = normaliseSettings(settings);
  }
}

function applySettings(config = settings) {
  const provider = normaliseProviderId(config.llm_provider);
  const baseUrl = getConfiguredBaseUrl(provider, config.llm_base_url);
  const desiredModel = sanitizeModelForProvider(
    provider,
    config.llm_model || getDefaultModel(provider),
    baseUrl,
  );

  renderProviderOptions(provider);
  document.getElementById('input-provider').value = provider;
  document.getElementById('input-provider').dataset.currentProvider = provider;
  document.getElementById('input-base-url').value = baseUrl;
  applyProviderInputMeta(provider);
  document.getElementById('input-apikey').value = providerUsesApiKey(provider, baseUrl)
    ? getProviderApiKey(provider, config)
    : '';
  renderModelOptions([getProviderConfig(provider).defaultModel].filter(Boolean), desiredModel || getDefaultModel(provider));
  refreshProviderModels({ desiredModel: desiredModel || getDefaultModel(provider) });
  document.querySelectorAll('.mode-opt').forEach(el => {
    el.classList.toggle('active', el.dataset.mode === config.mode);
  });
  setModeBadgeText();
  updateChatAvailability();
}

function normaliseProviderId(providerId) {
  return PROVIDER_CATALOG[providerId] ? providerId : '';
}

function getProviderConfig(providerId) {
  return PROVIDER_CATALOG[normaliseProviderId((providerId || '').toLowerCase())] || {
    label: '',
    baseUrl: '',
    requiresKey: false,
    keyPlaceholder: '',
    defaultModel: '',
  };
}

function getConfiguredBaseUrl(providerId, baseUrl) {
  return (baseUrl || '').trim() || getProviderConfig(providerId).baseUrl || '';
}

function getDefaultModel(providerId) {
  return getProviderConfig(providerId).defaultModel || '';
}

function isLocalBaseUrl(baseUrl) {
  const normalised = (baseUrl || '').trim().toLowerCase();
  return normalised.startsWith('http://127.0.0.1') || normalised.startsWith('http://localhost');
}

function providerUsesApiKey(providerId, baseUrl) {
  const provider = normaliseProviderId(providerId);
  const config = getProviderConfig(provider);
  if (!baseUrl) return false;
  if (!config.requiresKey) return false;
  if (isLocalBaseUrl(baseUrl)) return false;
  return true;
}

function isKnownModelForDifferentProvider(providerId, model) {
  const provider = normaliseProviderId(providerId);
  const value = (model || '').trim();
  if (!value) return false;
  return Object.entries(PROVIDER_CATALOG).some(([candidate, config]) => (
    candidate !== provider && config.defaultModel && config.defaultModel === value
  ));
}

function isMoonshotModelId(model) {
  const value = (model || '').trim().toLowerCase();
  return value.startsWith('moonshot') || value.startsWith('kimi-') || value.startsWith('moonshotai/');
}

function sanitizeModelForProvider(providerId, model, baseUrl) {
  const provider = normaliseProviderId(providerId);
  const value = (model || '').trim();
  if (!value) return '';
  if (provider === 'custom' && !baseUrl) return '';
  if (
    ['custom', 'lmstudio', 'ollama'].includes(provider)
    && (isKnownModelForDifferentProvider(provider, value) || isMoonshotModelId(value))
  ) {
    return '';
  }
  return value;
}

function hasUsableLLM(config = settings) {
  const provider = normaliseProviderId(config.llm_provider);
  if (!provider) return false;
  const baseUrl = getConfiguredBaseUrl(provider, config.llm_base_url);
  const model = sanitizeModelForProvider(provider, config.llm_model || getDefaultModel(provider), baseUrl);
  const apiKey = getProviderApiKey(provider, config);
  if ((provider === 'custom' || provider === 'lmstudio') && !baseUrl) return false;
  if (!model) return false;
  if (!providerUsesApiKey(provider, baseUrl)) return true;
  return !!model && !!apiKey;
}

function renderProviderOptions(selectedProvider = '') {
  const select = document.getElementById('input-provider');
  if (!select) return;

  const selected = normaliseProviderId((selectedProvider || '').toLowerCase());
  select.innerHTML = '';

  const emptyOption = document.createElement('option');
  emptyOption.value = '';
  emptyOption.textContent = '— Select a provider —';
  select.appendChild(emptyOption);

  PROVIDER_ORDER.forEach(providerId => {
    const option = document.createElement('option');
    option.value = providerId;
    option.textContent = getProviderConfig(providerId).label;
    select.appendChild(option);
  });
  select.value = selected;
}

function applyProviderInputMeta(providerId) {
  const config = getProviderConfig(providerId);
  const apiKeyInput = document.getElementById('input-apikey');
  const baseUrlInput = document.getElementById('input-base-url');
  const baseUrl = getConfiguredBaseUrl(providerId, baseUrlInput?.value || '');
  const needsKey = providerUsesApiKey(providerId, baseUrl);
  if (apiKeyInput) {
    if (!providerId) {
      apiKeyInput.placeholder = 'Select a provider first';
      apiKeyInput.disabled = true;
      apiKeyInput.value = '';
    } else {
      apiKeyInput.placeholder = needsKey ? (config.keyPlaceholder || 'sk-…') : 'not required for local models';
      apiKeyInput.disabled = !needsKey;
      if (!needsKey) apiKeyInput.value = '';
    }
  }
  if (baseUrlInput) baseUrlInput.placeholder = config.baseUrl || 'https://api.example.com/v1';
}

function dedupeModels(models) {
  const seen = new Set();
  const result = [];
  (models || []).forEach(model => {
    const value = (model || '').toString().trim();
    if (!value || seen.has(value)) return;
    seen.add(value);
    result.push(value);
  });
  return result;
}

function renderModelOptions(models, desiredModel = '') {
  const select = document.getElementById('input-model');
  const customInput = document.getElementById('input-model-custom');
  if (!select || !customInput) return;

  const options = dedupeModels(models);
  const target = (desiredModel || '').trim();

  select.innerHTML = '';
  options.forEach(modelId => {
    const option = document.createElement('option');
    option.value = modelId;
    option.textContent = modelId;
    select.appendChild(option);
  });

  const customOption = document.createElement('option');
  customOption.value = CUSTOM_MODEL_VALUE;
  customOption.textContent = t('modelCustomOption');
  select.appendChild(customOption);

  if (target && options.includes(target)) {
    select.value = target;
    customInput.value = '';
    customInput.classList.add('is-hidden');
  } else if (target) {
    select.value = CUSTOM_MODEL_VALUE;
    customInput.value = target;
    customInput.classList.remove('is-hidden');
  } else if (options.length) {
    select.value = options[0];
    customInput.value = '';
    customInput.classList.add('is-hidden');
  } else {
    select.value = CUSTOM_MODEL_VALUE;
    customInput.value = '';
    customInput.classList.remove('is-hidden');
  }

  customInput.placeholder = t('customModelHint');
}

function getSelectedModelValue() {
  const select = document.getElementById('input-model');
  const customInput = document.getElementById('input-model-custom');
  if (!select || !customInput) return '';
  return select.value === CUSTOM_MODEL_VALUE
    ? customInput.value.trim()
    : (select.value || '').trim();
}

function handleModelSelectionChange() {
  const select = document.getElementById('input-model');
  const customInput = document.getElementById('input-model-custom');
  if (!select || !customInput) return;
  const isCustom = select.value === CUSTOM_MODEL_VALUE;
  customInput.classList.toggle('is-hidden', !isCustom);
  if (!isCustom) customInput.value = '';
}

function setModelStatus(statusKey, tone = '') {
  modelLoadState.statusKey = statusKey;
  modelLoadState.tone = tone;
  renderModelStatus();
}

function renderModelStatus() {
  const note = document.getElementById('model-source-note');
  if (!note) return;
  note.textContent = t(modelLoadState.statusKey);
  note.className = `form-meta${modelLoadState.tone ? ` ${modelLoadState.tone}` : ''}`;
}

function shouldLoadLiveModels(providerId, apiKey, baseUrl) {
  if (!baseUrl) return false;
  if (providerId === 'ollama' || isLocalBaseUrl(baseUrl)) return true;
  if (providerId === 'openrouter') return true;
  return !!(apiKey || '').trim();
}

async function refreshProviderModels(options = {}) {
  const provider = normaliseProviderId(document.getElementById('input-provider')?.value || settings.llm_provider);
  const config = getProviderConfig(provider);
  const baseUrlInput = document.getElementById('input-base-url');
  const apiKeyInput = document.getElementById('input-apikey');
  const refreshBtn = document.getElementById('btn-refresh-models');
  const baseUrl = getConfiguredBaseUrl(provider, baseUrlInput?.value || '');
  applyProviderInputMeta(provider);
  const desiredModel = sanitizeModelForProvider(
    provider,
    (options.desiredModel ?? getSelectedModelValue() ?? '').trim(),
    baseUrl,
  );
  const modelTarget = desiredModel || getDefaultModel(provider);
  const fallbackModels = [config.defaultModel].filter(Boolean);

  if (!provider) {
    modelLoadState.available = [];
    renderModelOptions([], '');
    setModelStatus('modelStatusSelectProvider');
    return;
  }

  if (!baseUrl) {
    modelLoadState.available = fallbackModels;
    renderModelOptions(fallbackModels, getDefaultModel(provider));
    setModelStatus('modelStatusEnterBaseUrl');
    return;
  }

  if (!shouldLoadLiveModels(provider, apiKeyInput?.value || '', baseUrl)) {
    modelLoadState.available = [];
    renderModelOptions([], modelTarget);
    if (config.requiresKey) {
      setModelStatus('modelStatusNeedsKey', 'warn');
    } else {
      modelLoadState.available = fallbackModels;
      renderModelOptions(fallbackModels, modelTarget);
      setModelStatus('modelStatusFallback');
    }
    return;
  }

  modelLoadState.loading = true;
  if (refreshBtn) refreshBtn.disabled = true;
  setModelStatus('modelStatusLoading');

  try {
    const response = await fetch(`${API}/api/llm/models`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        api_key: (apiKeyInput?.value || '').trim(),
        llm_provider: provider,
        llm_base_url: baseUrl,
      }),
    });
    if (!response.ok) throw new Error('Model list request failed');

    const payload = await response.json();
    const liveModels = dedupeModels(payload.models || []);
    if (liveModels.length) {
      modelLoadState.available = liveModels;
      renderModelOptions(liveModels, modelTarget);
      setModelStatus('modelStatusLive', 'success');
      return;
    }

    modelLoadState.available = fallbackModels;
    renderModelOptions(fallbackModels, modelTarget);
    setModelStatus(fallbackModels.length ? 'modelStatusFallback' : 'modelStatusUnavailable');
  } catch (_) {
    modelLoadState.available = fallbackModels;
    renderModelOptions(fallbackModels, modelTarget);
    setModelStatus(fallbackModels.length ? 'modelStatusFallback' : 'modelStatusUnavailable');
  } finally {
    modelLoadState.loading = false;
    if (refreshBtn) refreshBtn.disabled = false;
  }
}

// ── Event bindings ────────────────────────────────────────────────────────────
function bindEvents() {
  // Single lease upload
  const fileInput  = document.getElementById('file-input');
  const btnBrowse  = document.getElementById('btn-browse');
  const mcSingle   = document.getElementById('mc-single');

  btnBrowse.addEventListener('click', e => { e.stopPropagation(); fileInput.click(); });
  fileInput.addEventListener('change', e => {
    if (e.target.files[0]) uploadFile(e.target.files[0]);
  });
  mcSingle.addEventListener('dragover', e => { e.preventDefault(); mcSingle.classList.add('drag-over'); });
  mcSingle.addEventListener('dragleave', e => { if (!mcSingle.contains(e.relatedTarget)) mcSingle.classList.remove('drag-over'); });
  mcSingle.addEventListener('drop', e => {
    e.preventDefault();
    mcSingle.classList.remove('drag-over');
    const f = e.dataTransfer.files[0];
    if (f && (f.name.toLowerCase().endsWith('.pdf') || f.name.toLowerCase().endsWith('.docx'))) uploadFile(f);
  });

  // Batch upload
  const batchInput     = document.getElementById('batch-file-input');
  const btnBatchBrowse = document.getElementById('btn-batch-browse');
  const btnBatchAdd    = document.getElementById('btn-batch-add');
  const btnBatchRun    = document.getElementById('btn-batch-run');
  const mcBatch        = document.getElementById('mc-batch');

  btnBatchBrowse.addEventListener('click', e => { e.stopPropagation(); batchInput.click(); });
  batchInput.addEventListener('change', e => { addBatchFiles(e.target.files); e.target.value = ''; });
  btnBatchAdd.addEventListener('click', () => batchInput.click());
  btnBatchRun.addEventListener('click', processBatch);
  mcBatch.addEventListener('dragover', e => { e.preventDefault(); mcBatch.classList.add('drag-over'); });
  mcBatch.addEventListener('dragleave', e => { if (!mcBatch.contains(e.relatedTarget)) mcBatch.classList.remove('drag-over'); });
  mcBatch.addEventListener('drop', e => {
    e.preventDefault();
    mcBatch.classList.remove('drag-over');
    const files = [...e.dataTransfer.files].filter(f => {
      const name = f.name.toLowerCase();
      return name.endsWith('.pdf') || name.endsWith('.docx');
    });
    if (files.length) addBatchFiles(files);
  })

  // New lease
  document.getElementById('btn-new-lease').addEventListener('click', showUploadScreen);

  // PDF navigation
  document.getElementById('btn-prev').addEventListener('click', () => goToPage(currentPage - 1));
  document.getElementById('btn-next').addEventListener('click', () => goToPage(currentPage + 1));

  // PDF zoom
  document.getElementById('btn-zoom-in').addEventListener('click',  () => setZoom(pdfScale * 1.25));
  document.getElementById('btn-zoom-out').addEventListener('click', () => setZoom(pdfScale / 1.25));

  // Panel resize
  const handle   = document.getElementById('resize-handle');
  const pdfPanel = document.getElementById('pdf-panel');
  handle.addEventListener('mousedown', e => {
    const startX = e.clientX;
    const startW = pdfPanel.getBoundingClientRect().width;
    handle.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    function onMove(e) {
      const w = Math.max(280, Math.min(startW + e.clientX - startX, window.innerWidth - 340));
      pdfPanel.style.width = w + 'px';
    }
    function onUp() {
      handle.classList.remove('dragging');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    }
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });

  // Tabs
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  // Settings modal
  document.getElementById('btn-settings').addEventListener('click', openModal);
  document.getElementById('btn-modal-cancel').addEventListener('click', closeModal);
  document.getElementById('btn-modal-save').addEventListener('click', saveSettings);
  document.getElementById('btn-refresh-models').addEventListener('click', () => refreshProviderModels());
  document.getElementById('modal-overlay').addEventListener('click', e => {
    if (e.target === document.getElementById('modal-overlay')) closeModal();
  });
  document.getElementById('input-provider').addEventListener('change', () => {
    const workingConfig = settingsForm || settings;
    const providerSelect = document.getElementById('input-provider');
    const previousProvider = normaliseProviderId(providerSelect.dataset.currentProvider || workingConfig.llm_provider);
    const previousBaseUrl = getConfiguredBaseUrl(previousProvider, document.getElementById('input-base-url').value);
    if (providerUsesApiKey(previousProvider, previousBaseUrl)) {
      setProviderApiKey(previousProvider, document.getElementById('input-apikey').value, workingConfig);
    }

    const provider = normaliseProviderId(providerSelect.value);
    const baseUrl = getProviderConfig(provider).baseUrl || '';
    const defaultModel = getDefaultModel(provider);
    workingConfig.llm_provider = provider;
    workingConfig.api_key = providerUsesApiKey(provider, baseUrl)
      ? getProviderApiKey(provider, workingConfig)
      : '';
    workingConfig.llm_base_url = baseUrl;
    workingConfig.llm_model = defaultModel;
    providerSelect.dataset.currentProvider = provider;

    document.getElementById('input-base-url').value = workingConfig.llm_base_url;
    applyProviderInputMeta(provider);
    document.getElementById('input-apikey').value = workingConfig.api_key;
    renderModelOptions([getProviderConfig(provider).defaultModel].filter(Boolean), defaultModel);
    refreshProviderModels({ desiredModel: defaultModel });
  });
  document.getElementById('input-model').addEventListener('change', handleModelSelectionChange);
  document.getElementById('input-base-url').addEventListener('input', () => applyProviderInputMeta(
    normaliseProviderId(document.getElementById('input-provider').value),
  ));
  document.getElementById('input-base-url').addEventListener('change', () => refreshProviderModels());
  document.getElementById('input-apikey').addEventListener('input', () => {
    const workingConfig = settingsForm || settings;
    const provider = normaliseProviderId(document.getElementById('input-provider').value || workingConfig.llm_provider);
    setProviderApiKey(provider, document.getElementById('input-apikey').value, workingConfig);
  });
  document.getElementById('input-apikey').addEventListener('change', () => refreshProviderModels());
  document.querySelectorAll('.mode-opt').forEach(el => {
    el.addEventListener('click', () => {
      document.querySelectorAll('.mode-opt').forEach(o => o.classList.remove('active'));
      el.classList.add('active');
    });
  });
  // API key show/hide
  const btnToggleKey = document.getElementById('btn-toggle-apikey');
  if (btnToggleKey) {
    btnToggleKey.addEventListener('click', () => {
      const inp = document.getElementById('input-apikey');
      const isPwd = inp.type === 'password';
      inp.type = isPwd ? 'text' : 'password';
      const useEl = btnToggleKey.querySelector('use');
      if (useEl) useEl.setAttribute('href', isPwd ? '#ic-eye-off' : '#ic-eye');
      btnToggleKey.title = isPwd ? t('hideKey') : t('showKey');
    });
  }

  // Chat
  document.getElementById('chat-send').addEventListener('click', sendChat);
  document.getElementById('chat-input').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
  });

  // Language toggle
  document.getElementById('btn-lang').addEventListener('click', () => {
    currentLang = currentLang === 'en' ? 'zh-HK' : 'en';
    localStorage.setItem('opus_lang', currentLang);
    applyI18n();
  });
}

// ── Upload ────────────────────────────────────────────────────────────────────
async function uploadFile(file) {
  if (activeUploadController) activeUploadController.abort();
  const controller = new AbortController();
  activeUploadController = controller;
  showProgress(t('progressAnalyse'));
  const timeoutId = setTimeout(() => controller.abort(), 120000);
  try {
    const form = new FormData();
    form.append('file', file);
    const r = await fetch(`${API}/api/upload`, {
      method: 'POST',
      body: form,
      signal: controller.signal,
    });
    if (!r.ok) {
      throw new Error(await responseErrorMessage(r, 'Upload failed'));
    }
    summaryData = await r.json();
    // Fetch OCR word bboxes before rendering pages (needed for highlight on scanned PDFs)
    ocrWordData = null;
    if (summaryData.document?.ocr) {
      try {
        const wr = await fetch(`${API}/api/pdf/words`);
        if (wr.ok) ocrWordData = await wr.json();
      } catch(_) {}
    }
    // Show workspace BEFORE rendering so layout is computed (clientWidth > 0)
    // Use original filename from server response (handles converted Word docs)
    document.getElementById('pdf-filename').textContent = summaryData.document?.original_filename || file.name;
    showWorkspace();
    await loadPDF();
    renderSummary(summaryData);
    renderExport(summaryData);
    renderChatSuggestions();
    updateChatAvailability();
  } catch (err) {
    const message = err.name === 'AbortError'
      ? 'Analysis timed out. Please try Standard mode or check the configured AI provider.'
      : err.message;
    hideProgress();
    showToast(`${t('uploadError')}: ${message}`, 'error', 9000);
  } finally {
    clearTimeout(timeoutId);
    if (activeUploadController === controller) activeUploadController = null;
    hideProgress();
  }
}

// ── PDF viewer ────────────────────────────────────────────────────────────────
async function loadPDF() {
  const url = `${API}/api/pdf?t=${Date.now()}`;
  pdfDoc = await pdfjsLib.getDocument(url).promise;
  currentPage = 1;
  // Wait for layout to settle so clientWidth is valid
  await new Promise(r => requestAnimationFrame(r));
  await new Promise(r => requestAnimationFrame(r));
  // Compute initial scale to fit container width
  const container = document.getElementById('pdf-viewport');
  const containerW = container.clientWidth;
  if (containerW > 32) {
    const firstPage = await pdfDoc.getPage(1);
    const naturalW  = firstPage.getViewport({ scale: 1 }).width;
    pdfScale = Math.min((containerW - 32) / naturalW, 1.5);
  } else {
    pdfScale = 1.2;
  }
  updateZoomLabel();
  await renderAllPages();
  updatePageInfo();
}

async function renderAllPages() {
  const container = document.getElementById('pdf-viewport');
  container.innerHTML = '';
  for (let i = 1; i <= pdfDoc.numPages; i++) {
    const page   = await pdfDoc.getPage(i);
    const vp     = page.getViewport({ scale: pdfScale });
    const wrap   = document.createElement('div');
    wrap.className = 'pdf-page-wrap';
    wrap.id = `page-${i}`;
    wrap.style.width  = vp.width  + 'px';
    wrap.style.height = vp.height + 'px';
    const canvas = document.createElement('canvas');
    canvas.width  = vp.width;
    canvas.height = vp.height;
    const ctx = canvas.getContext('2d', { alpha: false });
    // Text layer overlay — used by the quote highlighter
    const textLayer = document.createElement('div');
    textLayer.className = 'pdf-text-layer';
    textLayer.style.width  = vp.width  + 'px';
    textLayer.style.height = vp.height + 'px';
    // Highlight overlay (sits above the text layer so quote boxes are visible)
    const hlLayer = document.createElement('div');
    hlLayer.className = 'pdf-highlight-layer';
    hlLayer.style.width  = vp.width  + 'px';
    hlLayer.style.height = vp.height + 'px';
    const numLabel = document.createElement('div');
    numLabel.className = 'pdf-page-num';
    numLabel.textContent = `Page ${i}`;
    wrap.append(canvas, textLayer, hlLayer, numLabel);
    container.appendChild(wrap);
    await page.render({ canvasContext: ctx, viewport: vp }).promise;
    // Build a lightweight text-item index for quote search.
    try {
      const textContent = await page.getTextContent();
      wrap._pdfTextItems = textContent.items.map(it => {
        const tx = pdfjsLib.Util.transform(vp.transform, it.transform);
        // tx = [a,b,c,d,e,f]; e/f = x/y of baseline
        const fontHeight = Math.hypot(tx[2], tx[3]) || (it.height * pdfScale);
        return {
          str: it.str,
          x: tx[4],
          y: tx[5] - fontHeight,
          w: it.width * pdfScale,
          h: fontHeight,
        };
      });
    } catch (_) {
      wrap._pdfTextItems = [];
    }
    // For scanned PDFs pdfjs returns no text items; use backend OCR word bboxes instead.
    // PyMuPDF coords (top-left origin, y↓) map to canvas coords by simple scaling:
    //   canvas_x = x0 * pdfScale,  canvas_y = y0 * pdfScale  (y-flip cancels out)
    if (ocrWordData && !wrap._pdfTextItems.length) {
      const pageWords = (ocrWordData.pages || {})[String(i)] || [];
      // _ocrWords: raw unscaled word tuples used by drawOcrHighlight for sequence matching
      wrap._ocrWords = pageWords;
      wrap._pdfTextItems = pageWords.map(([x0, y0, x1, y1, word]) => ({
        str: word,
        x: x0 * pdfScale,
        y: y0 * pdfScale,
        w: (x1 - x0) * pdfScale,
        h: (y1 - y0) * pdfScale,
      }));
    }
  }
  observePages();
}

function observePages() {
  if (pageObserver) pageObserver.disconnect();
  const container = document.getElementById('pdf-viewport');
  const ratios = {};
  pageObserver = new IntersectionObserver(entries => {
    entries.forEach(e => {
      const n = +e.target.id.replace('page-', '');
      if (n) ratios[n] = e.intersectionRatio;
    });
    let best = currentPage, bestR = -1;
    for (const [n, r] of Object.entries(ratios)) {
      if (+r > bestR) { bestR = +r; best = +n; }
    }
    if (best !== currentPage) { currentPage = best; updatePageInfo(); }
  }, { root: container, threshold: [0, 0.1, 0.25, 0.5, 0.75, 1] });
  container.querySelectorAll('.pdf-page-wrap').forEach(el => pageObserver.observe(el));
}

async function setZoom(newScale) {
  if (!pdfDoc) return;
  pdfScale = Math.min(Math.max(newScale, 0.4), 3.0);
  updateZoomLabel();
  await renderAllPages();
}

function updateZoomLabel() {
  const el = document.getElementById('zoom-level');
  if (el) el.textContent = Math.round(pdfScale * 100) + '%';
}

function goToPage(n) {
  if (!pdfDoc) return;
  n = Math.max(1, Math.min(n, pdfDoc.numPages));
  currentPage = n;
  updatePageInfo();
  const wrap = document.getElementById(`page-${n}`);
  if (wrap) wrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function updatePageInfo() {
  const el = document.getElementById('pdf-page-info');
  el.textContent = pdfDoc ? `${currentPage} / ${pdfDoc.numPages}` : '— / —';
}

function highlightPages(pages, quote = '') {
  // Clear previous highlights (page outline + quote boxes)
  document.querySelectorAll('.pdf-page-wrap.highlighted').forEach(el => el.classList.remove('highlighted'));
  document.querySelectorAll('.pdf-highlight-layer').forEach(el => { el.innerHTML = ''; });

  if (!pages || !pages.length) return;

  // Add highlighted class to all target pages (gold border)
  pages.forEach(p => {
    const wrap = document.getElementById(`page-${p}`);
    if (wrap) wrap.classList.add('highlighted');
  });

  // Try to draw quote-level highlight on the first cited page
  let scrollTarget = null;
  if (pages[0] && quote) {
    scrollTarget = drawQuoteHighlight(pages[0], quote);
  }

  // Scroll to the highlight or the page
  if (scrollTarget) {
    scrollTarget.scrollIntoView({ behavior: 'smooth', block: 'center' });
  } else if (pages[0]) {
    const wrap = document.getElementById(`page-${pages[0]}`);
    if (wrap) wrap.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  currentPage = pages[0];
  updatePageInfo();
}

// For scanned/OCR PDFs: find the quote as a consecutive substring in the
// concatenated OCR word stream (same text the extractor worked from), then
// highlight the words that overlap the match. Much more accurate than the
// generic strategies below because it treats the quote as a whole sequence
// rather than matching individual words.
function drawOcrHighlight(pageNum, quote) {
  const wrap = document.getElementById(`page-${pageNum}`);
  if (!wrap) return null;
  const hlLayer = wrap.querySelector('.pdf-highlight-layer');
  if (!hlLayer) return null;
  hlLayer.innerHTML = '';

  const words = wrap._ocrWords || [];
  if (!words.length || !quote.trim()) return null;

  const wordStrs = words.map(w => (w[4] || '').toLowerCase());
  const concatStr = wordStrs.join(' ');

  // Strategy A: case-insensitive substring of the quote in the concatenated text
  let startChar = concatStr.indexOf(quote.toLowerCase().trim());
  let endChar   = startChar === -1 ? -1 : startChar + quote.trim().length;

  // Strategy B: strip punctuation/whitespace from both sides and retry
  if (startChar === -1) {
    const strip = s => s.toLowerCase().replace(/[^a-z0-9]/g, '');
    const qNorm = strip(quote);
    if (qNorm.length > 2) {
      const cNorm = strip(concatStr);
      const nPos  = cNorm.indexOf(qNorm);
      if (nPos !== -1) {
        // Map normalised index back to a position in concatStr
        let normIdx = 0, origIdx = 0;
        while (origIdx < concatStr.length && normIdx < nPos) {
          if (/[a-z0-9]/i.test(concatStr[origIdx])) normIdx++;
          origIdx++;
        }
        startChar = origIdx;
        let normEnd = nPos + qNorm.length;
        while (origIdx < concatStr.length && normIdx < normEnd) {
          if (/[a-z0-9]/i.test(concatStr[origIdx])) normIdx++;
          origIdx++;
        }
        endChar = origIdx;
      }
    }
  }

  if (startChar === -1) return null;

  // Find word bboxes that overlap with [startChar, endChar] in the concat string
  let charPos = 0, firstBox = null;
  for (let i = 0; i < wordStrs.length; i++) {
    const wStart = charPos;
    const wEnd   = charPos + wordStrs[i].length;
    if (wStart < endChar && wEnd > startChar && wordStrs[i].trim()) {
      const [x0, y0, x1, y1] = words[i];
      const box = document.createElement('div');
      box.className = 'pdf-quote-highlight';
      box.style.left   = `${x0 * pdfScale}px`;
      box.style.top    = `${y0 * pdfScale}px`;
      box.style.width  = `${Math.max((x1 - x0) * pdfScale, 4)}px`;
      box.style.height = `${Math.max((y1 - y0) * pdfScale, 8)}px`;
      hlLayer.appendChild(box);
      if (!firstBox) firstBox = box;
    }
    charPos = wEnd + 1; // +1 for the space separator
  }
  return firstBox;
}

// Find a substring of `quote` inside the page's text items and draw a
// translucent box over each matched item. Returns the first highlight box
// element so the caller can scroll it into view.
//
// Matching is intentionally aggressive: both the page text and the quote are
// reduced to lowercase alphanumerics-only before searching, because PDFs love
// to insert spaces / line breaks inside numbers ("HK$ 80,000"), to use unicode
// dashes the extractor normalised away, etc. We also try progressively
// shorter probes so that even partial matches highlight *something*.
function drawQuoteHighlight(pageNum, quote) {
  const wrap = document.getElementById(`page-${pageNum}`);
  if (!wrap) return null;

  // For OCR pages use sequence-based matching (avoids false matches on single words)
  if (wrap._ocrWords && wrap._ocrWords.length) {
    return drawOcrHighlight(pageNum, quote);
  }

  const hlLayer = wrap.querySelector('.pdf-highlight-layer');
  if (!hlLayer) return null;

  // Clear previous highlights
  wrap.classList.remove('no-text-items');
  hlLayer.innerHTML = '';

  // If no text items or empty quote, no highlight
  const items = wrap._pdfTextItems || [];
  if (!items.length || !quote || !quote.trim()) {
    return null;
  }

  // Strategy 1: Try exact substring match (case-insensitive)
  const quoteLower = quote.toLowerCase();
  for (let i = 0; i < items.length; i++) {
    const itemText = (items[i].str || '').toLowerCase();
    if (itemText.includes(quoteLower) || quoteLower.includes(itemText)) {
      // Found a matching item
      const it = items[i];
      const box = createHighlightBox(it, hlLayer);
      return box;
    }
  }

  // Strategy 2: Build word index for fuzzy matching
  const quoteWords = quoteLower.split(/\s+/).filter(w => w.length > 2);
  if (quoteWords.length === 0) return null;

  // Find items that contain any of the quote words
  const matchedIndices = new Set();
  items.forEach((it, idx) => {
    const itemText = (it.str || '').toLowerCase();
    for (const word of quoteWords) {
      // Remove punctuation for matching
      const cleanWord = word.replace(/[^a-z0-9]/g, '');
      const cleanItem = itemText.replace(/[^a-z0-9]/g, '');
      if (cleanWord.length > 2 && cleanItem.includes(cleanWord)) {
        matchedIndices.add(idx);
        break;
      }
    }
  });

  // Strategy 3: Try to find consecutive matches
  if (matchedIndices.size === 0) {
    // Try number-only matching for amounts/dates
    const numbers = quote.match(/\d[\d,\.]*/g);
    if (numbers) {
      for (const num of numbers) {
        const cleanNum = num.replace(/[,\.]/g, '');
        for (let i = 0; i < items.length; i++) {
          const itemNums = (items[i].str || '').match(/\d[\d,\.]*/g);
          if (itemNums) {
            for (const itemNum of itemNums) {
              if (itemNum.replace(/[,\.]/g, '') === cleanNum) {
                matchedIndices.add(i);
              }
            }
          }
        }
      }
    }
  }

  // Draw highlights for matched items
  if (matchedIndices.size > 0) {
    let firstBox = null;
    // Group consecutive indices
    const sortedIndices = Array.from(matchedIndices).sort((a, b) => a - b);
    for (const idx of sortedIndices) {
      const it = items[idx];
      if (!it || !it.str.trim()) continue;
      const box = createHighlightBox(it, hlLayer);
      if (box && !firstBox) firstBox = box;
    }
    return firstBox;
  }

  // No match found - don't highlight anything
  return null;
}

function createHighlightBox(it, hlLayer) {
  if (!it || !hlLayer) return null;
  const box = document.createElement('div');
  box.className = 'pdf-quote-highlight';
  box.style.left   = `${it.x}px`;
  box.style.top    = `${it.y}px`;
  box.style.width  = `${Math.max(it.w, 4)}px`;
  box.style.height = `${Math.max(it.h, 8)}px`;
  hlLayer.appendChild(box);
  return box;
}

// ── Summary ───────────────────────────────────────────────────────────────────

// Strict 1-to-1 with the Opus Lease Summary Template (HK).
// Each entry is one row in the template, in the EXACT order of the template.
// `parts` is the list of backend fields whose values are stacked inside the
// row's value cell. The first part is the "primary" field used for editing,
// confidence pill, and flag display.
const TEMPLATE_ROWS = [
  { label: 'Building Address',           labelZh: '大廈地址',
    parts: [{ src: 'premises', key: 'full_address' }] },
  { label: 'Lease Signing Date',         labelZh: '租約簽署日期',
    parts: [{ src: 'term', key: 'signing_date' }] },
  { label: 'Scheduled Commencement Date', labelZh: '預定開始日期',
    parts: [{ src: 'term', key: 'scheduled_commencement' }] },
  { label: 'Lessor Name / Landlord',     labelZh: '出租人 / 業主',
    parts: [{ src: 'parties', key: 'landlord_name' }] },
  { label: 'Account Name / Tenant',      labelZh: '租客名稱',
    parts: [{ src: 'parties', key: 'tenant_name' }] },
  { label: 'Premises (Floor level & Size)', labelZh: '物業（樓層及面積）',
    parts: [
      { src: 'premises', key: 'floor_suite',  prefix: 'Floor / Suite: ' },
      { src: 'premises', key: 'area_sqft',    prefix: 'Rentable Area: ', suffix: ' sq.ft.' },
      { src: 'premises', key: 'area_comment', prefix: 'Efficiency: ' },
    ] },
  { label: 'Lease Term',                 labelZh: '租約期限',
    parts: [{ src: 'term', key: 'term_months', suffix: ' months' }] },
  { label: 'Lease Commencement Date',    labelZh: '租約開始日期',
    parts: [{ src: 'term', key: 'commencement' }] },
  { label: 'Lease Expiry Date',          labelZh: '租約屆滿日期',
    parts: [{ src: 'term', key: 'expiry' }] },
  { label: 'Option to Renew',            labelZh: '續租選擇權',
    parts: [{ src: 'term', key: 'option_to_renew' }] },
  { label: 'Trigger Date',               labelZh: '觸發日期',
    parts: [{ src: 'term', key: 'trigger_date' }] },
  { label: 'Right of Expansion',         labelZh: '擴展權',
    parts: [{ src: 'term', key: 'right_of_expansion' }] },
  { label: 'Fit-Out Period',             labelZh: '裝修期',
    parts: [{ src: 'term', key: 'fit_out' }] },
  { label: 'Signage',                    labelZh: '招牌',
    parts: [{ src: 'clauses', key: 'signage' }] },
  { label: 'Operating Expenses',         labelZh: '營運開支',
    parts: [
      { src: 'financials', key: 'management_fee',     prefix: 'Air-conditioning & Mgmt Fees: HK$' },
      { src: 'financials', key: 'management_fee_psf', prefix: 'Mgmt Fee PSF: HK$' },
      { src: 'financials', key: 'govt_rent',          prefix: 'Government Rates: HK$' },
    ] },
  { label: 'Tenant Termination Right',   labelZh: '提早終止權',
    parts: [{ src: 'term', key: 'break_clause' }] },
  { label: 'Monthly Rent',               labelZh: '月租',
    parts: [
      { src: 'financials', key: 'monthly_rent',     prefix: 'HK$', suffix: ' / month' },
      { src: 'financials', key: 'monthly_rent_psf', prefix: 'HK$', suffix: ' / sq.ft. / month' },
    ] },
  { label: 'Security Deposit',           labelZh: '按金',
    parts: [
      { src: 'financials', key: 'security_deposit', prefix: 'HK$' },
      { src: 'financials', key: 'deposit_note' },
    ] },
  { label: 'Advance Rent',               labelZh: '預付租金',
    parts: [{ src: 'financials', key: 'advance_rent' }] },
  { label: 'Sub-Letting',                labelZh: '分租',
    parts: [{ src: 'clauses', key: 'subletting' }] },
  { label: 'Parking',                    labelZh: '停車場',
    parts: [{ src: 'clauses', key: 'parking' }] },
  { label: 'Restoration Obligations',    labelZh: '復原責任',
    parts: [{ src: 'clauses', key: 'restoration' }] },
];

const MULTILINE_KEYS = new Set(['full_address','signage','subletting','restoration','break_clause','handover','deposit_note']);

let editMode = false;

function renderSummary(data) {
  editMode = false;
  _drawSummary(data);
}

function _drawSummary(data) {
  const container = document.getElementById('tab-summary');
  container.innerHTML = '';

  // ── Meta strip + actions ─────────────────────────────────────────────────
  const doc = data.document;
  const meta = document.createElement('div');
  meta.className = 'summary-meta';

  const info = document.createElement('div');
  info.className = 'summary-meta-info';
  info.innerHTML = `<span><b>${t('metaType')}:</b> ${fmt(doc.type)}</span>
    <span><b>${t('metaPages')}:</b> ${doc.pages}</span>
    ${doc.ocr ? `<span class="ocr-badge"><svg width="11" height="11"><use href="#ic-warn"/></svg> OCR</span>` : ''}`;

  const actions = document.createElement('div');
  actions.className = 'summary-meta-actions';

  if (editMode) {
    const saveBtn = document.createElement('button');
    saveBtn.className = 'btn-sm btn-save-edits';
    saveBtn.textContent = t('saveBtn');
    saveBtn.onclick = () => _saveEdits(data);
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'btn-sm btn-cancel-edits';
    cancelBtn.textContent = t('cancelBtn');
    cancelBtn.onclick = () => { editMode = false; _drawSummary(data); };
    actions.append(saveBtn, cancelBtn);
  } else {
    const editBtn = document.createElement('button');
    editBtn.className = 'btn-sm btn-edit-summary';
    editBtn.innerHTML = `<svg width="12" height="12" style="vertical-align:-1px;margin-right:4px"><use href="#ic-edit"/></svg>${t('editBtn')}`;
    editBtn.onclick = () => { editMode = true; _drawSummary(data); };
    actions.appendChild(editBtn);
  }

  meta.append(info, actions);
  container.appendChild(meta);

  // ── Single flat table — strict template order, one row per template row ──
  const table = document.createElement('table');
  table.className = 'summary-table';

  for (const row of TEMPLATE_ROWS) {
    const tr = document.createElement('tr');
    tr.className = 'summary-row';
    // Primary part = first part; used for confidence pill, flag, edit save target
    const primary = row.parts[0];
    tr.dataset.src = primary.src;
    tr.dataset.key = primary.key;

    const labelTd = document.createElement('td');
    labelTd.className = 'summary-label';
    labelTd.textContent = currentLang === 'zh-HK' ? row.labelZh : row.label;

    const valueTd = document.createElement('td');
    valueTd.className = 'summary-value';

    if (editMode) {
      valueTd.classList.add('edit-mode');
      _renderRowEdit(valueTd, row, data);
    } else {
      _renderRowDisplay(valueTd, row, data);
      // Click-to-jump: find the first part with a usable page reference and
      // highlight that location in the PDF (with quote-level highlight if
      // available). Skip rows where no part has evidence.
      const cited = _firstCitation(row, data);
      if (cited) {
        tr.classList.add('clickable');
        tr.title = `Page ${cited.page} — click to view in PDF`;
        tr.addEventListener('click', () => {
          highlightPages([cited.page], cited.quote || '');
        });
      }
    }

    tr.append(labelTd, valueTd);
    table.appendChild(tr);
  }

  container.appendChild(table);
}

function _renderRowDisplay(valueTd, row, data) {
  // Build stacked lines for each part that has a value, then attach
  // confidence pill / flag from the primary part.
  const lines = [];
  for (const part of row.parts) {
    const f = data[part.src]?.[part.key];
    const v = (f?.value || '').trim();
    if (!v) continue;
    const text = `${part.prefix || ''}${v}${part.suffix || ''}`;
    lines.push(escHtml(text));
  }

  if (!lines.length) {
    valueTd.innerHTML = `<span class="field-value empty">${escHtml(t('notDetected'))}</span>`;
    return;
  }

  const primary = row.parts[0];
  const pf = data[primary.src]?.[primary.key];
  const conf = pf?.confidence ?? 0;
  const flag = pf?.flag || null;

  const flagEl = flag
    ? `<span class="flag-badge" title="${escHtml(flag)}"><svg width="11" height="11"><use href="#ic-warn"/></svg> Review</span>`
    : '';
  let pillEl = '';
  if (!flag && conf > 0) {
    const pct = Math.round(conf * 100);
    const cls = conf >= 0.85 ? 'conf-high' : conf >= 0.65 ? 'conf-medium' : 'conf-low';
    pillEl = `<span class="conf-pill ${cls}" title="${pct}% confidence">${pct}%</span>`;
  }

  valueTd.style.cssText = 'display:flex;align-items:flex-start;gap:8px;flex-wrap:wrap;';
  valueTd.innerHTML = `<span class="field-value">${lines.join('<br>')}</span>${flagEl}${pillEl}`;
}

// Return {page, quote} for the first part of `row` that has a page reference
// from the backend. If no part has a page, fall back to scanning all rendered
// PDF pages for the part's value text — that way fields whose extractor
// didn't record evidence are still clickable.
function _firstCitation(row, data) {
  for (const part of row.parts) {
    const f = data[part.src]?.[part.key];
    if (f && f.page) {
      // Prefer quote; otherwise use the value itself for highlight matching.
      return { page: f.page, quote: f.quote || f.value || '' };
    }
  }
  // Fallback: search PDF text for the value of any part with a usable value.
  for (const part of row.parts) {
    const f = data[part.src]?.[part.key];
    const v = (f?.value || '').trim();
    if (!v || v.length < 4) continue;
    const hit = _searchPdfForText(v);
    if (hit) return hit;
  }
  return null;
}

// Scan every rendered page's text-item index for the given text. Returns
// {page, quote} or null. Used as a fallback when the backend didn't supply
// evidence coordinates for a field.
function _searchPdfForText(text) {
  const needle = text.replace(/[^a-zA-Z0-9]/g, '').toLowerCase();
  if (needle.length < 4) return null;
  const wraps = document.querySelectorAll('.pdf-page-wrap');
  for (const wrap of wraps) {
    const items = wrap._pdfTextItems;
    if (!items || !items.length) continue;
    let flat = '';
    for (const it of items) {
      for (const ch of (it.str || '')) {
        if (/[a-zA-Z0-9]/.test(ch)) flat += ch.toLowerCase();
      }
    }
    if (flat.indexOf(needle) !== -1) {
      const pageNum = +wrap.id.replace('page-', '');
      return { page: pageNum, quote: text };
    }
  }
  return null;
}

function _renderRowEdit(valueTd, row, data) {
  // One editable input per part, stacked vertically.
  for (const part of row.parts) {
    const f = data[part.src]?.[part.key];
    const value = f?.value || '';
    const isMulti = MULTILINE_KEYS.has(part.key) || value.length > 80;
    const el = document.createElement(isMulti ? 'textarea' : 'input');
    el.className = 'field-edit';
    el.dataset.partSrc = part.src;
    el.dataset.partKey = part.key;
    if (el.tagName === 'INPUT') el.type = 'text';
    if (el.tagName === 'TEXTAREA') el.rows = 2;
    el.value = value;
    if (part.prefix || part.suffix) {
      el.placeholder = `${part.prefix || ''}value${part.suffix || ''}`;
    }
    valueTd.appendChild(el);
  }
}

async function _saveEdits(data) {
  // Each row may contain multiple inputs (one per template-row part).
  // Read by data-part-src/data-part-key on the input itself.
  const inputs = document.querySelectorAll('#tab-summary .field-edit');
  const updates = [];
  inputs.forEach(input => {
    const src = input.dataset.partSrc;
    const key = input.dataset.partKey;
    if (!src || !key) return;
    const val = input.value.trim();
    if (!data[src]) data[src] = {};
    if (!data[src][key]) data[src][key] = { value: val, confidence: 1.0, flag: null };
    else data[src][key].value = val;
    updates.push({ section: src, key, value: val });
  });
  // Persist to server so export reflects edits
  try {
    await fetch(`${API}/api/fields`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    });
  } catch (_) {}
  editMode = false;
  _drawSummary(data);
}

// ── Chat ──────────────────────────────────────────────────────────────────────
function updateChatAvailability() {
  const hasProvider = hasUsableLLM(settings);
  const input   = document.getElementById('chat-input');
  const sendBtn = document.getElementById('chat-send');
  const banner  = document.getElementById('chat-no-key-banner');

  input.disabled   = !hasProvider || chatBusy;
  sendBtn.disabled = !hasProvider || chatBusy;
  banner.style.display = hasProvider ? 'none' : '';

  // Refresh suggestion chip disabled state
  document.querySelectorAll('#chat-suggestions .chat-suggestion').forEach(b => {
    b.disabled = !hasProvider;
  });
}

async function sendChat() {
  const input = document.getElementById('chat-input');
  const q = input.value.trim();
  if (!q || chatBusy) return;

  input.value = '';
  chatBusy = true;
  updateChatAvailability();

  document.getElementById('chat-empty')?.remove();
  appendMessage('user', q);

  const typingEl = appendTyping();

  try {
    const aiEl = document.createElement('div');
    aiEl.className = 'msg ai';
    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    aiEl.appendChild(bubble);

    let fullText = '';
    let pages = [];
    let quote = '';
    let started = false;

    const resp = await fetch(`${API}/api/qa`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || 'Q&A request failed');
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const text = decoder.decode(value);
      for (const line of text.split('\n')) {
        if (!line.startsWith('data: ')) continue;
        let ev;
        try {
          ev = JSON.parse(line.slice(6));
        } catch (_) {
          continue;
        }
        if (ev.type === 'text') {
          if (!started) {
            typingEl.remove();
            document.getElementById('chat-messages').appendChild(aiEl);
            started = true;
          }
          fullText += ev.content;
          bubble.textContent = fullText;
          scrollChat();
        } else if (ev.type === 'done') {
          pages = ev.pages || [];
          quote = ev.quote || '';
        } else if (ev.type === 'error') {
          throw new Error(ev.content || 'Q&A request failed');
        }
      }
    }

    // Page badges
    if (pages.length) {
      const pagesRow = document.createElement('div');
      pagesRow.className = 'msg-pages';
      pages.forEach(p => {
        const badge = document.createElement('span');
        badge.className = 'page-badge';
        badge.textContent = `Page ${p}`;
        badge.addEventListener('click', () => {
          switchTab('summary');  // keep on summary to see PDF
          highlightPages([p], quote);
        });
        pagesRow.appendChild(badge);
      });
      aiEl.appendChild(pagesRow);
    }

    // Highlight pages in PDF viewer (with quote-level highlight if available)
    if (pages.length) highlightPages(pages, quote);

  } catch (err) {
    typingEl.remove();
    appendMessage('ai', `Error: ${err.message}`);
  } finally {
    chatBusy = false;
    updateChatAvailability();
  }
}

function appendMessage(role, text) {
  const msgs = document.getElementById('chat-messages');
  const el   = document.createElement('div');
  el.className = `msg ${role}`;
  el.innerHTML = `<div class="msg-bubble">${escHtml(text)}</div>`;
  msgs.appendChild(el);
  scrollChat();
  return el;
}

function appendTyping() {
  const msgs = document.getElementById('chat-messages');
  const el   = document.createElement('div');
  el.className = 'msg ai';
  el.innerHTML = `<div class="typing-indicator"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div>`;
  msgs.appendChild(el);
  scrollChat();
  return el;
}

function scrollChat() {
  const msgs = document.getElementById('chat-messages');
  msgs.scrollTop = msgs.scrollHeight;
}

// ── Export tab ────────────────────────────────────────────────────────────────
function renderExport(data) {
  const container = document.getElementById('export-content');
  if (!container) return;
  if (!data) {
    container.innerHTML = `<div class="export-empty">${escHtml(t('exportEmpty'))}</div>`;
    return;
  }

  // Stats: count one per template ROW (filled if its primary part has a value).
  let extracted = 0;
  let confidenceSum = 0;
  let flagged = 0;
  const rowStatuses = []; // [{label, filled}] for the checklist

  for (const row of TEMPLATE_ROWS) {
    const primary = row.parts[0];
    const f = data[primary.src]?.[primary.key];
    const v = (f?.value || '').trim();
    const isFilled = !!v;
    if (isFilled) {
      extracted += 1;
      confidenceSum += (f.confidence ?? 0);
    }
    if (f?.flag) flagged += 1;
    rowStatuses.push({
      label: currentLang === 'zh-HK' ? row.labelZh : row.label,
      filled: isFilled,
    });
  }
  const total = TEMPLATE_ROWS.length;
  const avgConf = extracted ? Math.round((confidenceSum / extracted) * 100) : 0;
  const doc = data.document || {};
  const docType = fmt(doc.type);
  const pages = doc.pages ?? '—';

  container.innerHTML = `
    <div class="export-card">
      <div class="export-card-header">
        <div class="export-card-title">
          <svg width="18" height="18"><use href="#ic-download"/></svg>
          ${escHtml(t('exportTitle'))}
        </div>
        <div class="export-card-subtitle">${escHtml(t('exportSubtitle'))}</div>
      </div>
      <div class="export-stats">
        <div class="export-stat">
          <span class="export-stat-label">${escHtml(t('exportDocType'))}</span>
          <span class="export-stat-value">${escHtml(docType)}${doc.ocr ? ' <span class="stat-suffix">OCR</span>' : ''}</span>
        </div>
        <div class="export-stat">
          <span class="export-stat-label">${escHtml(t('exportPages'))}</span>
          <span class="export-stat-value">${pages}</span>
        </div>
        <div class="export-stat success">
          <span class="export-stat-label">${escHtml(t('exportFields'))}</span>
          <span class="export-stat-value">${extracted}<span class="stat-suffix">/ ${total}</span></span>
        </div>
        <div class="export-stat">
          <span class="export-stat-label">${escHtml(t('exportConfidence'))}</span>
          <span class="export-stat-value">${avgConf}<span class="stat-suffix">%</span></span>
        </div>
        <div class="export-stat ${flagged ? 'warn' : ''}" style="grid-column: 1 / -1">
          <span class="export-stat-label">${escHtml(t('exportFlagged'))}</span>
          <span class="export-stat-value">${flagged ? flagged : escHtml(t('exportNone'))}</span>
        </div>
      </div>
    </div>

    <div class="export-checklist">
      <div class="export-checklist-title">${escHtml(t('exportIncluded'))}</div>
      <ul>
        ${rowStatuses.map(r => `
          <li class="${r.filled ? '' : 'missing'}">
            <span class="check-icon"><svg width="10" height="10"><use href="#${r.filled ? 'ic-check' : 'ic-warn'}"/></svg></span>
            <span>${escHtml(r.label)}</span>
          </li>
        `).join('')}
      </ul>
    </div>

    <div class="export-cta">
      <button class="btn-export" id="btn-export">
        <svg width="18" height="18"><use href="#ic-download"/></svg>
        <span>${escHtml(t('downloadExcel'))}</span>
      </button>
      <div class="export-hint">${escHtml(t('exportHint'))}</div>
    </div>
  `;

  const exportBtn = document.getElementById('btn-export');
  if (exportBtn) {
    exportBtn.addEventListener('click', async () => {
      try {
        exportBtn.disabled = true;
        exportBtn.innerHTML = `<svg width="18" height="18" class="spin"><use href="#ic-refresh"/></svg><span>${escHtml(t('downloadExcel'))}</span>`;

        const resp = await fetch(`${API}/api/export`);
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          throw new Error(err.detail || `Export failed (${resp.status})`);
        }

        const blob = await resp.blob();

        // Check if running in pywebview desktop mode
        if (window.pywebview && window.pywebview.api && window.pywebview.api.save_file) {
          // Desktop mode: use native file dialog
          const arrayBuffer = await blob.arrayBuffer();
          const bytes = new Uint8Array(arrayBuffer);
          let binary = '';
          for (let i = 0; i < bytes.byteLength; i++) {
            binary += String.fromCharCode(bytes[i]);
          }
          const base64 = btoa(binary);

          const disposition = resp.headers.get('Content-Disposition');
          const match = disposition?.match(/filename="(.+)"/);
          const filename = match ? match[1] : 'lease_summary.xlsx';

          const result = await window.pywebview.api.save_file(filename, base64);
          if (result.success) {
            showToast(`Saved to ${result.path}`, 'success');
          } else if (result.error !== 'User cancelled') {
            throw new Error(result.error);
          }
        } else {
          // Browser mode: use anchor tag download
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          const disposition = resp.headers.get('Content-Disposition');
          const match = disposition?.match(/filename="(.+)"/);
          a.download = match ? match[1] : 'lease_summary.xlsx';
          document.body.appendChild(a);
          a.click();
          // Delay cleanup to ensure download starts
          setTimeout(() => {
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
          }, 100);
        }
      } catch (err) {
        showToast(`Export failed: ${err.message}`, 'error');
      } finally {
        exportBtn.disabled = false;
        exportBtn.innerHTML = `<svg width="18" height="18"><use href="#ic-download"/></svg><span>${escHtml(t('downloadExcel'))}</span>`;
      }
    });
  }
}

// ── Chat suggestion chips ─────────────────────────────────────────────────────
function renderChatSuggestions() {
  const container = document.getElementById('chat-suggestions');
  if (!container) return;
  const enabled = hasUsableLLM(settings);
  const keys = ['chatSugg1', 'chatSugg2', 'chatSugg3', 'chatSugg4'];
  container.innerHTML = '';
  for (const key of keys) {
    const text = t(key);
    const btn = document.createElement('button');
    btn.className = 'chat-suggestion';
    btn.type = 'button';
    btn.disabled = !enabled;
    btn.innerHTML = `
      <span class="chat-suggestion-icon"><svg width="14" height="14"><use href="#ic-sparkle"/></svg></span>
      <span class="chat-suggestion-text">${escHtml(text)}</span>
    `;
    btn.addEventListener('click', () => {
      if (btn.disabled) return;
      const input = document.getElementById('chat-input');
      input.value = text;
      switchTab('chat');
      sendChat();
    });
    container.appendChild(btn);
  }
}

// ── Toast notifications ───────────────────────────────────────────────────────
function showToast(message, type = 'info', duration = 5000) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  const iconId = type === 'error'   ? '#ic-warn'
              : type === 'success' ? '#ic-check'
              : '#ic-chat';
  toast.innerHTML = `
    <span class="toast-icon"><svg width="16" height="16"><use href="${iconId}"/></svg></span>
    <span class="toast-body">${escHtml(message)}</span>
    <button class="toast-close" type="button" aria-label="Close">
      <svg width="12" height="12"><use href="#ic-close"/></svg>
    </button>
  `;
  const remove = () => {
    toast.classList.add('toast-out');
    setTimeout(() => toast.remove(), 250);
  };
  toast.querySelector('.toast-close').addEventListener('click', remove);
  container.appendChild(toast);
  if (duration > 0) setTimeout(remove, duration);
}

// ── Settings modal ────────────────────────────────────────────────────────────
function openModal() {
  settingsForm = cloneSettings(settings);
  applySettings(settingsForm);
  // Always open with API key masked
  const inp = document.getElementById('input-apikey');
  const btn = document.getElementById('btn-toggle-apikey');
  if (inp) inp.type = 'password';
  if (btn) {
    const useEl = btn.querySelector('use');
    if (useEl) useEl.setAttribute('href', '#ic-eye');
    btn.title = t('showKey');
  }
  document.getElementById('modal-overlay').classList.add('open');
}

function closeModal() {
  settingsForm = null;
  document.getElementById('modal-overlay').classList.remove('open');
}

async function saveSettings() {
  const draft = cloneSettings(settingsForm || settings);
  const provider = normaliseProviderId(document.getElementById('input-provider').value);
  setProviderApiKey(provider, document.getElementById('input-apikey').value, draft);
  const baseUrl = getConfiguredBaseUrl(provider, document.getElementById('input-base-url').value);
  const model = getSelectedModelValue() || getDefaultModel(provider);
  const mode   = document.querySelector('.mode-opt.active')?.dataset.mode || 'regex';

  settings = normaliseSettings({
    ...draft,
    mode,
    llm_provider: provider,
    llm_base_url: baseUrl,
    llm_model: model,
  });
  try {
    await fetch(`${API}/api/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    });
  } catch (_) {}

  settingsForm = null;
  applySettings();
  closeModal();
}

// ── Tabs ──────────────────────────────────────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.toggle('active', c.id === `tab-${name}`));
}

// ── Screen transitions ────────────────────────────────────────────────────────
function showWorkspace() {
  document.getElementById('upload-screen').style.display = 'none';
  document.getElementById('workspace').classList.add('visible');
  switchTab('summary');
}

function showUploadScreen() {
  document.getElementById('workspace').classList.remove('visible');
  document.getElementById('upload-screen').style.display = '';
  pdfDoc = null;
  summaryData = null;
  ocrWordData = null;
  batchFiles = [];
  document.getElementById('batch-area').classList.remove('visible');
  document.getElementById('batch-file-list').innerHTML = '';
  document.getElementById('pdf-viewport').innerHTML = '';
  document.getElementById('tab-summary').innerHTML = '';
  document.getElementById('chat-messages').innerHTML =
    `<div class="chat-empty" id="chat-empty">
       <svg class="empty-icon"><use href="#ic-chat"/></svg>
       <p class="chat-empty-msg" data-i18n="chatEmptyMsg">${escHtml(t('chatEmptyMsg'))}</p>
       <div class="chat-suggestions" id="chat-suggestions"></div>
     </div>`;
  renderChatSuggestions();
  renderExport(null);
}

function showProgress(label) {
  document.getElementById('progress-label').textContent = label;
  document.getElementById('progress-overlay').classList.add('open');
  _animateProgressSteps();
}

function hideProgress() {
  document.getElementById('progress-overlay').classList.remove('open');
  _clearProgressTimers();
  // Reset step states for next time
  document.querySelectorAll('#progress-steps .step').forEach(s => s.classList.remove('active', 'done'));
}

function resetProgressOverlay() {
  activeUploadController?.abort();
  activeUploadController = null;
  const overlay = document.getElementById('progress-overlay');
  if (overlay) overlay.classList.remove('open');
  _clearProgressTimers();
  document.querySelectorAll('#progress-steps .step').forEach(s => s.classList.remove('active', 'done'));
}

function installGlobalErrorHandlers() {
  window.addEventListener('unhandledrejection', event => {
    resetProgressOverlay();
    const reason = event.reason;
    const message = reason?.message || String(reason || 'Unexpected error');
    showToast(message, 'error', 9000);
  });
  window.addEventListener('error', event => {
    resetProgressOverlay();
    showToast(event.message || 'Unexpected error', 'error', 9000);
  });
}

async function responseErrorMessage(response, fallback) {
  const statusText = `${fallback} (${response.status})`;
  const contentType = response.headers.get('content-type') || '';

  if (contentType.includes('application/json')) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    if (Array.isArray(detail)) {
      return detail
        .map(item => item?.msg || item?.message || JSON.stringify(item))
        .filter(Boolean)
        .join('; ') || statusText;
    }
    if (detail) return String(detail);
    if (payload?.message) return String(payload.message);
  }

  const text = await response.text().catch(() => '');
  return text.trim() || statusText;
}

function _clearProgressTimers() {
  _progressTimers.forEach(id => clearTimeout(id));
  _progressTimers = [];
}

function _animateProgressSteps() {
  _clearProgressTimers();
  const steps = Array.from(document.querySelectorAll('#progress-steps .step'));
  if (!steps.length) return;
  steps.forEach(s => s.classList.remove('active', 'done'));
  steps[0].classList.add('active');
  // Step 1 → 2 after ~1.2s, 2 → 3 after ~2.6s. If still loading, step 3 stays active.
  _progressTimers.push(setTimeout(() => {
    steps[0].classList.remove('active');
    steps[0].classList.add('done');
    if (steps[1]) steps[1].classList.add('active');
  }, 1200));
  _progressTimers.push(setTimeout(() => {
    if (steps[1]) {
      steps[1].classList.remove('active');
      steps[1].classList.add('done');
    }
    if (steps[2]) steps[2].classList.add('active');
  }, 2600));
}

// ── Batch export ──────────────────────────────────────────────────────────────
function addBatchFiles(fileList) {
  for (const f of fileList) {
    const name = f.name.toLowerCase();
    if (!name.endsWith('.pdf') && !name.endsWith('.docx')) continue;
    if (batchFiles.some(b => b.file.name === f.name && b.file.size === f.size)) continue;
    batchFiles.push({ file: f, status: 'pending' });
  }
  renderBatchFileList();
}

function renderBatchFileList() {
  const area = document.getElementById('batch-area');
  const list = document.getElementById('batch-file-list');
  if (!batchFiles.length) { area.classList.remove('visible'); return; }
  area.classList.add('visible');
  list.innerHTML = '';
  batchFiles.forEach((item, idx) => {
    const row = document.createElement('div');
    row.className = 'batch-file-item';
    const sizeMB = (item.file.size / 1024 / 1024).toFixed(1);
    const sc = item.status === 'done' ? 'done' : item.status === 'error' ? 'error' : 'pending';
    const st = item.status === 'done' ? t('batchDone') : item.status === 'error' ? t('batchError') : t('batchPending');
    row.innerHTML = `
      <span class="batch-file-name" title="${escHtml(item.file.name)}">${escHtml(item.file.name)}</span>
      <span class="batch-file-size">${sizeMB} MB</span>
      <span class="batch-file-status ${sc}">${st}</span>
      <button class="btn-remove-file" data-idx="${idx}" title="Remove">
        <svg><use href="#ic-close"/></svg>
      </button>`;
    list.appendChild(row);
  });
  list.querySelectorAll('.btn-remove-file').forEach(btn => {
    btn.addEventListener('click', () => {
      batchFiles.splice(+btn.dataset.idx, 1);
      renderBatchFileList();
    });
  });
}

async function processBatch() {
  if (!batchFiles.length) return;
  showProgress(t('progressBatch'));
  try {
    const form = new FormData();
    batchFiles.forEach(item => form.append('files', item.file));
    const r = await fetch(`${API}/api/batch`, { method: 'POST', body: form });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Batch failed (${r.status})`);
    }

    const blob = await r.blob();
    const filename = batchFiles.length === 1
      ? batchFiles[0].file.name.replace(/\.(pdf|docx)$/i, '.xlsx')
      : 'opus_lease_summaries.zip';

    // Check if running in pywebview desktop mode
    if (window.pywebview && window.pywebview.api && window.pywebview.api.save_file) {
      // Desktop mode: use native file dialog
      const arrayBuffer = await blob.arrayBuffer();
      const bytes = new Uint8Array(arrayBuffer);
      let binary = '';
      for (let i = 0; i < bytes.byteLength; i++) {
        binary += String.fromCharCode(bytes[i]);
      }
      const base64 = btoa(binary);

      const result = await window.pywebview.api.save_file(filename, base64);
      if (result.success) {
        showToast(`Saved to ${result.path}`, 'success');
      } else if (result.error !== 'User cancelled') {
        throw new Error(result.error);
      }
    } else {
      // Browser mode: use anchor tag download
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => {
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }, 100);
    }

    batchFiles.forEach(f => f.status = 'done');
    renderBatchFileList();
  } catch (err) {
    showToast(`${t('batchErrorMsg')}: ${err.message}`, 'error');
    batchFiles.forEach(f => { if (f.status === 'pending') f.status = 'error'; });
    renderBatchFileList();
  } finally {
    hideProgress();
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fmt(str) {
  if (!str) return '—';
  return str.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}
