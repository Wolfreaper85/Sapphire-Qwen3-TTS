// plugins/qwen3-tts/web/main.js — Injects Voice Lab CSS + persona dropdown enhancement
(function() {
    'use strict';

    const PLUGIN = 'qwen3-tts';
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = `/plugin-web/${PLUGIN}/voice-lab.css`;
    document.head.appendChild(link);

    // ── Persona Voice Dropdown Enhancement ──
    // Upgrades the flat voice <select> in the persona editor to use
    // <optgroup> sections grouped by category. This runs entirely from
    // the plugin — no core Sapphire files are modified.

    function upgradeVoiceDropdown(select) {
        if (!select || select.dataset.qwen3Grouped) return;

        const options = Array.from(select.options);
        if (options.length < 2) return;

        // Parse options — stock format: "Name (Category)"
        const voices = [];
        let currentValue = select.value;
        for (const opt of options) {
            const match = opt.textContent.match(/^(.+?)\s*\(([^)]+)\)$/);
            voices.push({
                value: opt.value,
                name: match ? match[1].trim() : opt.textContent,
                category: match ? match[2].trim() : '',
                selected: opt.value === currentValue,
            });
        }

        // Group by category
        const groups = {};
        for (const v of voices) {
            const group = v.category || 'Other';
            if (!groups[group]) groups[group] = [];
            groups[group].push(v);
        }

        // Only upgrade if there are multiple groups
        if (Object.keys(groups).length <= 1) return;

        // Rebuild the select with optgroups
        select.innerHTML = '';
        for (const [group, gVoices] of Object.entries(groups)) {
            const optgroup = document.createElement('optgroup');
            optgroup.label = group;
            for (const v of gVoices) {
                const opt = document.createElement('option');
                opt.value = v.value;
                opt.textContent = v.name;
                if (v.selected) opt.selected = true;
                optgroup.appendChild(opt);
            }
            select.appendChild(optgroup);
        }

        // Restore selection and mark as grouped so we don't re-process
        if (currentValue) select.value = currentValue;
        select.dataset.qwen3Grouped = '1';
    }

    // Watch for the persona voice dropdown to appear/update
    const observer = new MutationObserver(() => {
        const select = document.querySelector('#pa-s-voice');
        if (select && !select.dataset.qwen3Grouped) {
            // Small delay to let stock code finish populating options
            setTimeout(() => upgradeVoiceDropdown(select), 50);
        }
    });

    // Start observing once DOM is ready
    if (document.body) {
        observer.observe(document.body, { childList: true, subtree: true });
    } else {
        document.addEventListener('DOMContentLoaded', () => {
            observer.observe(document.body, { childList: true, subtree: true });
        });
    }

    // Also handle when the TTS provider changes (voices list refreshes)
    window.addEventListener('settings_changed', () => {
        const select = document.querySelector('#pa-s-voice');
        if (select) {
            delete select.dataset.qwen3Grouped;
            setTimeout(() => upgradeVoiceDropdown(select), 200);
        }
    });

    // ── Silent Mode Button — monkey-patched into TTS settings tab ──
    // Watches for the TTS settings tab's "Test TTS" button to appear,
    // then injects a Silent Mode toggle right next to it.

    const API = `/api/plugin/${PLUGIN}`;
    const CSRF = () => document.querySelector('meta[name="csrf-token"]')?.content || '';

    function injectSilentModeButton() {
        const testBtn = document.querySelector('#tts-test-btn');
        if (!testBtn || document.querySelector('#qwen3-silent-inject')) return;

        // Find the setting-row that contains the test button
        const row = testBtn.closest('.setting-row') || testBtn.parentElement;
        if (!row) return;

        // Create the silent mode container
        const wrapper = document.createElement('div');
        wrapper.id = 'qwen3-silent-inject';
        wrapper.className = 'setting-row full-width';
        wrapper.style.cssText = 'display:flex; align-items:center; gap:10px; margin-top:0.5rem;';
        wrapper.innerHTML = `
            <button id="qwen3-tts-silent-btn" class="btn btn-secondary"
                    style="width:auto; font-weight:600; border:none; color:#fff; background:var(--color-error,#f44336);">
                \uD83D\uDD07 Go Silent
            </button>
            <span id="qwen3-tts-silent-status" style="font-size:var(--font-sm,0.85em);"></span>
        `;

        // Insert after the test button row
        row.parentElement.insertBefore(wrapper, row.nextSibling);

        const btn = wrapper.querySelector('#qwen3-tts-silent-btn');
        const status = wrapper.querySelector('#qwen3-tts-silent-status');

        const updateUI = (active) => {
            if (active) {
                btn.textContent = '\uD83D\uDD0A Restore Voice';
                btn.style.background = 'var(--color-success, #4caf50)';
                status.textContent = 'Silent mode active \u2014 TTS servers stopped, VRAM freed.';
                status.style.color = 'var(--color-warning, #ff9800)';
            } else {
                btn.textContent = '\uD83D\uDD07 Go Silent';
                btn.style.background = 'var(--color-error, #f44336)';
                status.textContent = '';
            }
        };

        // Check initial state
        fetch(`${API}/silent-mode`).then(r => r.ok ? r.json() : null).then(data => {
            if (data) updateUI(data.active);
        }).catch(() => {});

        btn.addEventListener('click', async () => {
            btn.disabled = true;
            const isSilent = btn.textContent.includes('Restore');

            btn.textContent = isSilent ? 'Restoring...' : 'Shutting down...';
            status.textContent = isSilent ? 'Relaunching TTS servers...' : 'Killing TTS servers...';
            status.style.color = 'var(--color-text-muted, #888)';

            try {
                const endpoint = isSilent ? 'off' : 'on';
                const res = await fetch(`${API}/silent-mode/${endpoint}`, {
                    method: 'POST',
                    headers: { 'X-CSRF-Token': CSRF(), 'Content-Type': 'application/json' },
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const data = await res.json();

                if (data.status === 'silent' || data.status === 'already_silent') {
                    updateUI(true);
                } else if (data.status === 'voice_restored' || data.status === 'not_silent') {
                    updateUI(false);
                } else if (data.status === 'error') {
                    status.textContent = data.message || 'Error';
                    status.style.color = 'var(--color-error, #f44336)';
                }
            } catch (e) {
                status.textContent = `Error: ${e.message}`;
                status.style.color = 'var(--color-error, #f44336)';
            }
            btn.disabled = false;
        });
    }

    // The MutationObserver already watches document.body — extend it
    // to also inject the silent mode button when TTS settings tab appears
    const silentObserver = new MutationObserver(() => {
        if (document.querySelector('#tts-test-btn') && !document.querySelector('#qwen3-silent-inject')) {
            setTimeout(injectSilentModeButton, 100);
        }
    });

    if (document.body) {
        silentObserver.observe(document.body, { childList: true, subtree: true });
    } else {
        document.addEventListener('DOMContentLoaded', () => {
            silentObserver.observe(document.body, { childList: true, subtree: true });
        });
    }
})();

export default { init() {} };
