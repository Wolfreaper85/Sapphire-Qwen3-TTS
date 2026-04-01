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
})();

export default { init() {} };
