'use strict';

// Provider settings. Keys are write-only: the server returns only configuration state
// and a short suffix so secrets never get echoed back into the page.
(() => {
  const view = {
    settings: null,
    models: { local: null, openrouter: null, google: null },
    loading: { local: false, openrouter: false, google: false },
    saving: false,
  };

  const el = (id) => document.getElementById(id);

  async function api(path, options) {
    const response = await fetch(path, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Request failed (HTTP ${response.status})`);
    return data;
  }

  function setStatus(message, kind = '') {
    const status = el('settingsStatus');
    status.textContent = message;
    status.className = `settings-status${kind ? ` ${kind}` : ''}`;
    status.hidden = !message;
  }

  function selectedProvider() {
    return document.querySelector('input[name="provider"]:checked')?.value || 'local';
  }

  function updateTestButton() {
    const provider = selectedProvider();
    el('testBtn').disabled = !view.settings?.[provider]?.active || provider !== view.settings.provider;
  }

  function syncPanels() {
    const provider = selectedProvider();
    ['local', 'openrouter', 'google'].forEach((name) => {
      el(`${name}Panel`).hidden = provider !== name;
    });
    updateTestButton();
    if (provider === 'local') loadLocalModels();
    if (provider === 'openrouter') loadOpenrouterModels();
    if (provider === 'google' && view.settings.google.configured) loadGoogleModels();
  }

  function renderKeyState(provider, inputId, stateId, textId, envName) {
    const setting = view.settings[provider];
    const input = el(inputId);
    input.value = '';
    input.placeholder = setting.configured
      ? 'Enter a new key to replace the saved one'
      : (provider === 'openrouter' ? 'sk-or-…' : 'Enter your Gemini API key');
    el(stateId).hidden = !setting.configured;
    el(textId).textContent = setting.key_source === 'environment'
      ? `Using ${envName} from the environment`
      : `Saved key ending ${setting.key_hint}`;
  }

  function replaceOptions(selectId, models, current, labelForModel, emptyText = 'Choose a model…') {
    const select = el(selectId);
    select.replaceChildren(new Option(emptyText, ''));
    models.forEach((model) => select.add(new Option(labelForModel(model), model.id)));
    const currentModel = models.find((model) => (
      model.id === current || model.id === `${current}:latest` || `${model.id}:latest` === current
    ));
    if (currentModel) {
      select.value = currentModel.id;
    } else if (models.length) {
      select.value = models[0].id;
    }
    if (current && !currentModel) {
      const unavailable = new Option(`${current} — unavailable; choose another model`, '', true, true);
      unavailable.disabled = true;
      select.add(unavailable);
    }
  }

  function renderLocalModels(current = view.settings.local.model) {
    const models = view.models.local || [];
    replaceOptions('localModelSelect', models, current, (model) => {
      const detail = [model.parameter_size, model.quantization_level].filter(Boolean).join(' · ');
      return detail ? `${model.name} · ${detail}` : model.name;
    });
    el('localModelCount').textContent = `${models.length} installed`;
  }

  function renderOpenrouterModels(current = view.settings.openrouter.model) {
    const select = el('openrouterModelSelect');
    const models = view.models.openrouter || [];
    select.replaceChildren(new Option('Choose a model…', ''));
    const groups = [
      ['Tool calling supported (recommended)', models.filter((model) => model.supports_tools)],
      ['Text tool compatibility mode', models.filter((model) => !model.supports_tools)],
    ];
    groups.forEach(([label, entries]) => {
      if (!entries.length) return;
      const group = document.createElement('optgroup');
      group.label = label;
      entries.forEach((model) => {
        const context = model.context_length ? ` · ${Math.round(model.context_length / 1000)}k ctx` : '';
        group.appendChild(new Option(`${model.name}${context}`, model.id));
      });
      select.appendChild(group);
    });
    if (current && models.some((model) => model.id === current)) select.value = current;
    if (current && !models.some((model) => model.id === current)) {
      const unavailable = new Option(`${current} — unavailable; choose another model`, '', true, true);
      unavailable.disabled = true;
      select.add(unavailable);
    }
    el('openrouterModelCount').textContent = `${models.length} free models`;
  }

  function renderGoogleModels(current = view.settings.google.model) {
    const models = view.models.google || [];
    replaceOptions('googleModelSelect', models, current, (model) => {
      const context = model.context_length ? ` · ${Math.round(model.context_length / 1000)}k ctx` : '';
      return `${model.name}${context}`;
    });
    el('googleModelCount').textContent = `${models.length} available`;
  }

  async function loadProviderModels(provider, { refresh = false, googleKey = '' } = {}) {
    if (view.loading[provider] || (view.models[provider] && !refresh && !googleKey)) return;
    const selectId = `${provider}ModelSelect`;
    const current = el(selectId).value || view.settings[provider].model;
    view.loading[provider] = true;
    el(selectId).disabled = true;
    el(selectId).replaceChildren(new Option('Loading models…', ''));
    try {
      let result;
      if (provider === 'google') {
        result = await api('/api/google/models', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(googleKey ? { google_api_key: googleKey } : {}),
        });
      } else {
        const endpoint = provider === 'local' ? '/api/local/models' : '/api/openrouter/models';
        result = await api(`${endpoint}${refresh ? '?refresh=1' : ''}`);
      }
      view.models[provider] = result.models;
      if (provider === 'local') renderLocalModels(current);
      if (provider === 'openrouter') renderOpenrouterModels(current);
      if (provider === 'google') renderGoogleModels(current);
      setStatus('');
    } catch (error) {
      view.models[provider] = null;
      el(selectId).replaceChildren(new Option('Could not load models', ''));
      setStatus(error.message, 'error');
    } finally {
      view.loading[provider] = false;
      el(selectId).disabled = false;
    }
  }

  const loadLocalModels = (refresh = false) => loadProviderModels('local', { refresh });
  const loadOpenrouterModels = (refresh = false) => loadProviderModels('openrouter', { refresh });
  const loadGoogleModels = (refresh = false) => loadProviderModels('google', {
    refresh,
    googleKey: el('googleKeyInput').value.trim(),
  });

  function applyToComposer() {
    const select = el('modelPresetSelect');
    if (!select || !view.settings) return;
    const provider = view.settings.provider;
    const model = view.settings[provider].model;
    const label = { local: 'Local', openrouter: 'OpenRouter', google: 'Google AI' }[provider];
    select.innerHTML = `<option value="local">${escapeHtml(label)} · ${escapeHtml(model)}</option>`;
    select.disabled = true;
    select.title = 'Change the provider or model in Settings';
  }

  function renderSettings() {
    renderKeyState('openrouter', 'openrouterKeyInput', 'openrouterKeyState', 'openrouterKeyStateText', 'OPENROUTER_API_KEY');
    renderKeyState('google', 'googleKeyInput', 'googleKeyState', 'googleKeyStateText', 'GOOGLE_API_KEY or GEMINI_API_KEY');
    if (view.models.local) renderLocalModels();
    if (view.models.openrouter) renderOpenrouterModels();
    if (view.models.google) renderGoogleModels();
    updateTestButton();
  }

  async function refresh() {
    view.settings = await api('/api/settings');
    applyToComposer();
  }

  async function open() {
    setStatus('');
    try { await refresh(); } catch (error) { showToast(error.message); return; }
    document.querySelector(`input[name="provider"][value="${view.settings.provider}"]`).checked = true;
    renderSettings();
    syncPanels();
    openModal(el('settingsModal'));
  }

  async function save() {
    if (view.saving) return;
    const provider = selectedProvider();
    const body = { provider };
    const openrouterKey = el('openrouterKeyInput').value.trim();
    const googleKey = el('googleKeyInput').value.trim();
    if (openrouterKey) body.openrouter_api_key = openrouterKey;
    if (googleKey) body.google_api_key = googleKey;
    if (provider === 'local') body.local_model = el('localModelSelect').value;
    if (provider === 'openrouter') body.openrouter_model = el('openrouterModelSelect').value;
    if (provider === 'google' && el('googleModelSelect').value) body.google_model = el('googleModelSelect').value;

    if (provider === 'local' && !body.local_model) return setStatus('Choose an installed local model.', 'error');
    if (provider === 'openrouter' && !body.openrouter_model) return setStatus('Choose an OpenRouter model.', 'error');
    if (provider === 'openrouter' && !openrouterKey && !view.settings.openrouter.configured) {
      return setStatus('Enter your OpenRouter API key.', 'error');
    }
    if (provider === 'google' && !googleKey && !view.settings.google.configured) {
      return setStatus('Enter your Gemini API key.', 'error');
    }

    const button = el('saveSettingsBtn');
    view.saving = true;
    button.disabled = true;
    setStatus((openrouterKey || googleKey) ? 'Checking the key and available models…' : 'Saving…');
    try {
      view.settings = await api('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      applyToComposer();
      renderSettings();
      closeModal(el('settingsModal'));
      showToast(`Using ${provider === 'google' ? 'Google AI Studio' : provider === 'openrouter' ? 'OpenRouter' : 'the local model'}`);
      if (typeof loadConfig === 'function') loadConfig();
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      view.saving = false;
      button.disabled = false;
    }
  }

  async function removeKey(provider) {
    const providerName = provider === 'google' ? 'Gemini' : 'OpenRouter';
    if (!window.confirm(`Remove the saved ${providerName} key? Data Mind will switch to the local model if it is active.`)) return;
    const body = { [`${provider}_api_key`]: '' };
    if (view.settings.provider === provider) body.provider = 'local';
    try {
      view.settings = await api('/api/settings', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      document.querySelector(`input[name="provider"][value="${view.settings.provider}"]`).checked = true;
      applyToComposer();
      renderSettings();
      syncPanels();
      if (typeof loadConfig === 'function') loadConfig();
      setStatus('Key removed.', 'ok');
    } catch (error) {
      setStatus(error.message, 'error');
    }
  }

  async function test() {
    const button = el('testBtn');
    button.disabled = true;
    setStatus('Calling the active model…');
    try {
      const result = await api('/api/settings/test', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      });
      setStatus(`The model replied: “${result.response || '(empty)'}”`, 'ok');
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      updateTestButton();
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    el('settingsBtn').addEventListener('click', open);
    el('removeOpenrouterKeyBtn').addEventListener('click', () => removeKey('openrouter'));
    el('removeGoogleKeyBtn').addEventListener('click', () => removeKey('google'));
    el('testBtn').addEventListener('click', test);
    el('refreshLocalModelsBtn').addEventListener('click', () => loadLocalModels(true));
    el('refreshOpenrouterModelsBtn').addEventListener('click', () => loadOpenrouterModels(true));
    el('loadGoogleModelsBtn').addEventListener('click', () => loadGoogleModels(true));
    document.querySelectorAll('input[name="provider"]').forEach((radio) => radio.addEventListener('change', syncPanels));
    el('settingsForm').addEventListener('submit', (event) => { event.preventDefault(); save(); });
    refresh().catch(() => {});
  });
})();
