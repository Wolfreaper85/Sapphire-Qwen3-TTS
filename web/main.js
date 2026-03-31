// plugins/qwen3-tts/web/main.js — Injects Voice Lab CSS
(function() {
    'use strict';

    const PLUGIN = 'qwen3-tts';
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = `/plugin-web/${PLUGIN}/voice-lab.css`;
    document.head.appendChild(link);
})();

export default { init() {} };
