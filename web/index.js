// plugins/qwen3-tts/web/index.js — Voice Lab settings panel
// 4-tab UI: Voice Design, Voice Clone, Custom Voice, Voice Library
// With preset dropdowns, How to Use guide, and folder access

import { registerPluginSettings } from '/static/shared/plugin-registry.js';

const PLUGIN = 'qwen3-tts';
const API = `/api/plugin/${PLUGIN}`;
const CSRF = () => document.querySelector('meta[name="csrf-token"]')?.content || '';

// ── Preset data ──
const SPEAKERS = ['Aiden','Dylan','Eric','Ono_anna','Ryan','Serena','Sohee','Uncle_fu','Vivian'];
const LANGUAGES = ['Auto','Chinese','English','Japanese','Korean','French','German','Spanish','Portuguese','Russian','Italian'];

// ── Preset voice descriptions (for Voice Design dropdown) ──
const VOICE_DESCRIPTIONS = [
    { label: '-- Select a preset or write your own --', value: '' },
    { label: 'Warm Storyteller (Male)', value: 'A warm, deep male voice with a calm and reassuring tone, like a grandfather telling a bedtime story' },
    { label: 'Energetic News Anchor (Female)', value: 'A bright, confident female voice with clear enunciation and professional energy' },
    { label: 'Gravelly Old Cowboy', value: 'A gravelly, weathered male voice with a slow Southern drawl and dry humor' },
    { label: 'Gentle & Soothing (Female)', value: 'A soft, gentle female voice that is soothing and peaceful, like a meditation guide' },
    { label: 'Excited Gamer (Male)', value: 'A young, energetic male voice full of excitement and enthusiasm, slightly fast-paced' },
    { label: 'Mysterious Narrator', value: 'A low, mysterious voice with dramatic pauses and an air of intrigue, like a thriller audiobook' },
    { label: 'Cheerful Assistant (Female)', value: 'A friendly, upbeat female voice that sounds helpful and approachable with a warm smile' },
    { label: 'Stern Professor (Male)', value: 'A mature, authoritative male voice that speaks precisely and deliberately, like a university lecturer' },
    { label: 'Playful & Whimsical (Female)', value: 'A light, playful female voice with a sing-song quality, perfect for reading fairy tales' },
    { label: 'Tired Night Owl', value: 'A slightly raspy, tired voice like someone who just woke up at 3am, relaxed and mellow' },
    { label: 'Custom (write your own)', value: '__custom__' },
];

// ── Preset style instructions (for Custom Voice dropdown) ──
// ── Preset reference texts (for Voice Clone — what to read aloud) ──
const CLONE_REF_TEXTS = [
    { label: '-- Select a sample or write your own --', value: '' },
    { label: 'Pangram — The Quick Brown Fox', value: 'The quick brown fox jumps over the lazy dog near the river bank.' },
    { label: 'Pangram — Pack My Box', value: 'Pack my box with five dozen liquor jugs.' },
    { label: 'Introduction', value: 'Hello, my name is Sarah and I love spending time outdoors on sunny days.' },
    { label: 'Weather Report', value: 'Today will be mostly sunny with a high of seventy-five degrees and light winds from the west.' },
    { label: 'Storytelling', value: 'Once upon a time, in a village nestled between the mountains and the sea, there lived a curious young explorer.' },
    { label: 'Technical', value: 'The system processes approximately two thousand requests per second using a distributed architecture.' },
    { label: 'Enthusiastic', value: 'Oh wow, this is absolutely incredible! I cannot believe how amazing this turned out!' },
    { label: 'Calm & Measured', value: 'Take a deep breath. Relax your shoulders. Let go of any tension you might be holding.' },
    { label: 'Conversational', value: 'So anyway, I was telling them about the trip we took last summer and they could not stop laughing.' },
    { label: 'Custom (write your own)', value: '__custom__' },
];

const STYLE_INSTRUCTIONS = [
    { label: '-- No style instruction --', value: '' },
    { label: 'Calm & Relaxed', value: 'Speak in a calm, relaxed manner with a steady pace' },
    { label: 'Excited & Energetic', value: 'Speak with excited energy and enthusiasm, slightly faster' },
    { label: 'Serious & Professional', value: 'Speak in a serious, professional tone with clear enunciation' },
    { label: 'Warm & Friendly', value: 'Speak warmly and in a friendly way, like talking to a good friend' },
    { label: 'Whispering', value: 'Speak in a soft whisper, quiet and intimate' },
    { label: 'Dramatic & Theatrical', value: 'Speak with dramatic flair, emphasizing key words with theatrical delivery' },
    { label: 'Sad & Melancholic', value: 'Speak slowly with a sad, melancholic tone and gentle pauses' },
    { label: 'Angry & Intense', value: 'Speak with intensity and sharp, forceful delivery' },
    { label: 'Sarcastic & Dry', value: 'Speak with dry sarcasm and a slightly bored, incredulous tone' },
    { label: 'Custom (write your own)', value: '__custom__' },
];

registerPluginSettings({
    id: PLUGIN,
    name: 'Qwen3-TTS Voice Lab',
    icon: '\uD83C\uDFB5',
    helpText: 'Create, clone, and manage voices for Qwen3-TTS. Build custom voices and assign them to personas.',

    async render(container, settings) {
        container.innerHTML = `
            <div class="qwen3-voice-lab">
                <div class="qwen3-top-bar">
                    <div class="qwen3-status" id="qwen3-status" style="flex:1;margin:0 12px 0 0"></div>
                    <button class="qwen3-help-btn" id="qwen3-help-btn">? How to Use</button>
                </div>

                <div class="qwen3-tabs">
                    <button class="qwen3-tab active" data-tab="design">\uD83C\uDFA8 Voice Design</button>
                    <button class="qwen3-tab" data-tab="clone">\uD83D\uDCCB Voice Clone</button>
                    <button class="qwen3-tab" data-tab="custom">\uD83C\uDF99\uFE0F Custom Voice</button>
                    <button class="qwen3-tab" data-tab="library">\uD83D\uDCDA Voice Library</button>
                </div>

                <!-- ═══ Voice Design Tab ═══ -->
                <div class="qwen3-panel active" id="qwen3-panel-design">
                    <p class="qwen3-desc">Describe a voice in plain English and the AI will create it. Pick a preset or write your own description. <em>Requires 1.7B model.</em></p>

                    <div class="qwen3-section-label">Voice Description</div>
                    <div class="qwen3-preset-group">
                        <select id="qwen3-design-preset">${VOICE_DESCRIPTIONS.map(d => `<option value="${_esc(d.value)}">${_esc(d.label)}</option>`).join('')}</select>
                        <textarea id="qwen3-design-instruct" rows="3" placeholder="Describe the voice you want... e.g. A warm, gravelly male voice with a slight Southern drawl, speaking calmly">${_esc(settings?.design_instruct || '')}</textarea>
                    </div>

                    <div class="qwen3-section-label">Preview</div>
                    <label>Test Text</label>
                    <textarea id="qwen3-design-text" rows="2" placeholder="Enter text to hear the voice say...">${_esc(settings?.design_text || "It's fascinating how technology can give a unique voice to every character.")}</textarea>

                    <div class="qwen3-row">
                        <div class="qwen3-field">
                            <label>Language</label>
                            <select id="qwen3-design-lang">${_langOptions('Auto')}</select>
                        </div>
                    </div>

                    <div class="qwen3-actions">
                        <button class="btn" id="qwen3-design-generate">\u25B6 Generate Preview</button>
                        <button class="btn btn-primary" id="qwen3-design-save" disabled>\uD83D\uDCBE Save Voice</button>
                    </div>
                    <p class="qwen3-save-note">Previews are temporary. Click "Save Voice" to keep it in your library and use it with personas.</p>
                    <div class="qwen3-audio-box" id="qwen3-design-audio"></div>
                </div>

                <!-- ═══ Voice Clone Tab ═══ -->
                <div class="qwen3-panel" id="qwen3-panel-clone">
                    <p class="qwen3-desc">Upload or record a 3+ second audio clip and the AI will clone that voice. The cloned voice can then say anything you want.</p>

                    <div class="qwen3-section-label">Reference Audio</div>
                    <div class="qwen3-upload-row">
                        <input type="file" id="qwen3-clone-file" accept="audio/*" />
                        <button class="btn btn-sm" id="qwen3-clone-record">\uD83C\uDF99 Record</button>
                        <button class="qwen3-folder-btn" id="qwen3-clone-folder" title="Open voices folder">\uD83D\uDCC2 Folder</button>
                        <span id="qwen3-clone-file-info" class="text-muted"></span>
                    </div>

                    <div class="qwen3-section-label">Reference Text <span class="text-muted">(read this aloud for your recording)</span></div>
                    <div class="qwen3-preset-group">
                        <select id="qwen3-clone-ref-preset">${CLONE_REF_TEXTS.map(d => `<option value="${_esc(d.value)}">${_esc(d.label)}</option>`).join('')}</select>
                        <textarea id="qwen3-clone-ref-text" rows="2" placeholder="Type the exact words you are saying in the reference audio..."></textarea>
                    </div>

                    <label class="qwen3-checkbox-label">
                        <input type="checkbox" id="qwen3-clone-xvector" />
                        X-vector only mode (skip transcript — just match the sound of the voice)
                    </label>

                    <div class="qwen3-section-label">Generate</div>
                    <label>Target Text</label>
                    <textarea id="qwen3-clone-target" rows="2" placeholder="What should the cloned voice say?">Hello! This is a test of the cloned voice.</textarea>

                    <div class="qwen3-row">
                        <div class="qwen3-field">
                            <label>Language</label>
                            <select id="qwen3-clone-lang">${_langOptions('Auto')}</select>
                        </div>
                        <div class="qwen3-field">
                            <label>Model Size</label>
                            <select id="qwen3-clone-model-size">
                                <option value="0.6B">0.6B (Lightweight)</option>
                                <option value="1.7B" selected>1.7B (Full quality)</option>
                            </select>
                        </div>
                    </div>

                    <div class="qwen3-actions">
                        <button class="btn" id="qwen3-clone-generate">\u25B6 Clone & Preview</button>
                        <button class="btn btn-primary" id="qwen3-clone-save" disabled>\uD83D\uDCBE Save Voice</button>
                    </div>
                    <p class="qwen3-save-note">Previews are temporary. Click "Save Voice" to keep it in your library and use it with personas.</p>
                    <div class="qwen3-audio-box" id="qwen3-clone-audio"></div>
                </div>

                <!-- ═══ Custom Voice Tab ═══ -->
                <div class="qwen3-panel" id="qwen3-panel-custom">
                    <p class="qwen3-desc">Pick one of the 9 built-in Qwen3-TTS voices and optionally add a style instruction to change how they speak.</p>

                    <div class="qwen3-section-label">Voice Selection</div>
                    <div class="qwen3-row">
                        <div class="qwen3-field">
                            <label>Speaker</label>
                            <select id="qwen3-custom-speaker">${SPEAKERS.map(s => `<option value="${s.toLowerCase()}">${s}</option>`).join('')}</select>
                        </div>
                        <div class="qwen3-field">
                            <label>Language</label>
                            <select id="qwen3-custom-lang">${_langOptions('English')}</select>
                        </div>
                        <div class="qwen3-field">
                            <label>Model Size</label>
                            <select id="qwen3-custom-model-size">
                                <option value="0.6B">0.6B</option>
                                <option value="1.7B" selected>1.7B</option>
                            </select>
                        </div>
                    </div>

                    <div class="qwen3-section-label">Style Instruction (Optional)</div>
                    <div class="qwen3-preset-group">
                        <select id="qwen3-custom-style-preset">${STYLE_INSTRUCTIONS.map(d => `<option value="${_esc(d.value)}">${_esc(d.label)}</option>`).join('')}</select>
                        <textarea id="qwen3-custom-instruct" rows="2" class="qwen3-hidden" placeholder="Write your own style instruction..."></textarea>
                    </div>

                    <div class="qwen3-section-label">Preview</div>
                    <label>Test Text</label>
                    <textarea id="qwen3-custom-text" rows="2">Hello! Welcome to Qwen3 text-to-speech. This is a preview of the selected voice.</textarea>

                    <div class="qwen3-actions">
                        <button class="btn" id="qwen3-custom-generate">\u25B6 Generate Preview</button>
                        <button class="btn btn-primary" id="qwen3-custom-save" disabled>\uD83D\uDCBE Save Voice</button>
                    </div>
                    <p class="qwen3-save-note">Previews are temporary. Click "Save Voice" to keep it in your library and use it with personas.</p>
                    <div class="qwen3-audio-box" id="qwen3-custom-audio"></div>
                </div>

                <!-- ═══ Voice Library Tab ═══ -->
                <div class="qwen3-panel" id="qwen3-panel-library">
                    <p class="qwen3-desc">Your saved voices. To use one with a persona: go to <strong>Personas</strong>, set the TTS provider to <strong>Qwen3-TTS</strong>, then select your voice from the dropdown.</p>
                    <div id="qwen3-library-list"></div>
                </div>
            </div>
        `;

        _attachListeners(container);
        _checkStatus(container);
        _loadLibrary(container);
    },

    load: async () => ({}),
    save: async () => ({ success: true }),
    getSettings: () => ({}),
});


// ── Helpers ──

function _esc(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
}

function _langOptions(selected) {
    return LANGUAGES.map(l => `<option value="${l}"${l === selected ? ' selected' : ''}>${l}</option>`).join('');
}


// ── How to Use Modal ──

function _showHelpModal() {
    const overlay = document.createElement('div');
    overlay.className = 'qwen3-modal-overlay';
    overlay.innerHTML = `
        <div class="qwen3-modal">
            <button class="qwen3-modal-close">&times;</button>
            <h3>\uD83C\uDFB5 How to Use the Voice Lab</h3>

            <h4>Getting Started</h4>
            <ol>
                <li><strong>Pick a tab</strong> at the top to choose how you want to create a voice:
                    <br>&bull; <strong>Voice Design</strong> \u2014 Describe a voice in words (e.g. "a warm old man voice"). <em>Requires 1.7B model.</em>
                    <br>&bull; <strong>Voice Clone</strong> \u2014 Upload or record a short audio clip to copy that voice
                    <br>&bull; <strong>Custom Voice</strong> \u2014 Pick a built-in speaker and optionally add a style</li>
                <li><strong>Generate a preview</strong> \u2014 Type some text and click the Generate button to hear how it sounds</li>
                <li><strong>Save the voice</strong> \u2014 If you like it, click "Save Voice" and give it a name. This stores it permanently.</li>
                <li><strong>Check your Voice Library</strong> \u2014 The Library tab shows all your saved voices, grouped by type</li>
                <li><strong>Assign to a persona</strong> \u2014 Go to the <strong>Personas</strong> page, and in the voice dropdown you'll see your saved Qwen3 voices. Select one for any persona.</li>
                <li><strong>That's it!</strong> \u2014 When that persona responds in chat, it will speak with the voice you created</li>
            </ol>

            <h4>Model Sizes: 0.6B vs 1.7B</h4>
            <p>Qwen3-TTS comes in two sizes. You can change this in plugin settings.</p>
            <table class="qwen3-help-table">
                <tr><th></th><th>0.6B (Light)</th><th>1.7B (Full)</th></tr>
                <tr><td>VRAM</td><td>~2-3 GB</td><td>~6-8 GB</td></tr>
                <tr><td>Custom Voice</td><td>\u2713</td><td>\u2713</td></tr>
                <tr><td>Voice Clone</td><td>\u2713</td><td>\u2713</td></tr>
                <tr><td>Voice Design</td><td>\u2717</td><td>\u2713</td></tr>
                <tr><td>Best for</td><td>Daily use alongside LLMs</td><td>Higher quality, voice design</td></tr>
            </table>

            <h4>Voice Types & Storage</h4>
            <ul>
                <li><strong>Custom Voices</strong> (speaker + style) \u2014 Work on <em>any</em> model size. Stored in <code>voices/custom/</code></li>
                <li><strong>Clone Voices</strong> \u2014 Tied to the model size they were created on. A 0.6B clone won't work on 1.7B and vice versa. Stored in <code>voices/0.6B/</code> or <code>voices/1.7B/</code></li>
                <li><strong>Designed Voices</strong> \u2014 1.7B only. Stored in <code>voices/1.7B/</code></li>
                <li><strong>Built-in Presets</strong> (Ryan, Serena, etc.) \u2014 Work on any model size, no files needed.</li>
            </ul>

            <h4>Pro Tip: Design on 1.7B, Clone to 0.6B</h4>
            <p>If you have the VRAM for it, you can use Voice Design to create the perfect voice on 1.7B, then port it to 0.6B for daily use:</p>
            <ol>
                <li>Temporarily close other GPU apps (LM Studio, etc.) to free VRAM</li>
                <li>Switch to <strong>1.7B</strong> in plugin settings (server will restart)</li>
                <li>Use the <strong>Voice Design</strong> tab to describe and generate your ideal voice</li>
                <li>Save the generated audio preview (or note the audio)</li>
                <li>Switch back to <strong>0.6B</strong> in plugin settings</li>
                <li>Use the <strong>Voice Clone</strong> tab with the designed audio as your reference clip</li>
                <li>Save the clone \u2014 now you have a portable 0.6B version of your designed voice</li>
            </ol>
            <p class="text-muted" style="font-size:0.85em">The 0.6B clone won't be identical to the 1.7B design, but it will capture the core vocal characteristics.</p>

            <h4>Tips</h4>
            <div class="qwen3-tip">
                <strong>Previews:</strong> Temporary and won't be saved unless you click "Save Voice". Generate as many as you want before saving.
            </div>
            <div class="qwen3-tip" style="margin-top:8px">
                <strong>Cloning:</strong> A clean 3-10 second recording with no background noise works best. Speak clearly and naturally. 8-10 seconds is ideal.
            </div>
            <div class="qwen3-tip" style="margin-top:8px">
                <strong>Pitch:</strong> Set persona pitch to <strong>1.0</strong> for cloned voices. The clone already captured your exact pitch \u2014 any shift will distort it.
            </div>
            <div class="qwen3-tip" style="margin-top:8px">
                <strong>VRAM:</strong> Idle models auto-offload from GPU to CPU after 60 seconds. They reload automatically when needed (~2-3s). You don\u2019t need to manage this manually.
            </div>
        </div>
    `;
    document.body.appendChild(overlay);

    const close = () => overlay.remove();
    overlay.querySelector('.qwen3-modal-close').addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
}


// ── Audio playback ──

let _currentAudio = null;

function _playAudio(audioBox, base64Audio) {
    if (_currentAudio) {
        _currentAudio.pause();
        _currentAudio = null;
    }
    const blob = _b64toBlob(base64Audio, 'audio/ogg');
    const url = URL.createObjectURL(blob);
    audioBox.innerHTML = `<audio controls autoplay src="${url}" style="width:100%;margin-top:8px"></audio>`;
    _currentAudio = audioBox.querySelector('audio');
    _currentAudio.addEventListener('ended', () => URL.revokeObjectURL(url));
}

function _b64toBlob(b64, type) {
    const bin = atob(b64);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    return new Blob([arr], { type });
}


// ── Mic Recording ──

let _mediaRecorder = null;
let _recordedChunks = [];

function _setupRecordButton(container) {
    const btn = container.querySelector('#qwen3-clone-record');
    const info = container.querySelector('#qwen3-clone-file-info');
    if (!btn) return;

    btn.addEventListener('click', async () => {
        if (_mediaRecorder && _mediaRecorder.state === 'recording') {
            _mediaRecorder.stop();
            btn.textContent = '\uD83C\uDF99 Record';
            return;
        }

        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            _recordedChunks = [];
            _mediaRecorder = new MediaRecorder(stream);
            _mediaRecorder.ondataavailable = e => { if (e.data.size > 0) _recordedChunks.push(e.data); };
            _mediaRecorder.onstop = () => {
                stream.getTracks().forEach(t => t.stop());
                const blob = new Blob(_recordedChunks, { type: 'audio/webm' });
                const file = new File([blob], 'recording.webm', { type: 'audio/webm' });
                const dt = new DataTransfer();
                dt.items.add(file);
                container.querySelector('#qwen3-clone-file').files = dt.files;
                info.textContent = `Recorded ${(blob.size / 1024).toFixed(1)} KB`;
            };
            _mediaRecorder.start();
            btn.textContent = '\u23F9 Stop';
            info.textContent = 'Recording...';
        } catch (e) {
            info.textContent = 'Mic access denied';
        }
    });
}


// ── File to Base64 ──

function _fileToBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result.split(',')[1]);
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });
}


// ── Status Check ──

async function _checkStatus(container) {
    const el = container.querySelector('#qwen3-status');
    if (!el) return;
    try {
        const r = await fetch(`${API}/status`);
        const d = await r.json();
        if (d.running) {
            const ms = d.model_status || {};
            const parts = Object.entries(ms).map(([k, state]) => {
                const icon = state === 'gpu' ? '\u2705' : state === 'cpu' ? '\uD83D\uDCA4' : '\u274C';
                return `${icon} ${k}`;
            });
            const memInfo = d.memory_gb > 0 ? ` \u2014 ${d.memory_gb} GB RAM` : '';
            container._serverModelSize = d.model_size || '0.6B';
            el.innerHTML = `<span class="qwen3-status-ok">\u2713 Server running</span> \u2014 ${d.model_size || '?'} on ${d.device || '?'}${memInfo}<br><span class="text-muted" style="font-size:0.85em">${parts.join(' &nbsp;\u2022&nbsp; ')}</span>`;
        } else {
            el.innerHTML = `<span class="qwen3-status-err">\u2717 Server not running</span> \u2014 It should auto-start when you select Qwen3-TTS as your TTS provider.`;
        }
    } catch {
        el.innerHTML = `<span class="qwen3-status-err">\u2717 Cannot reach server</span>`;
    }
}


// ── Preset Dropdown Logic ──

function _setupPresetDropdown(container, selectId, textareaId, opts = {}) {
    const select = container.querySelector(`#${selectId}`);
    const textarea = container.querySelector(`#${textareaId}`);
    if (!select || !textarea) return;

    // alwaysShowTextarea: keep textarea visible so user can see full text (good for long presets)
    const alwaysShow = opts.alwaysShowTextarea || false;

    select.addEventListener('change', () => {
        const val = select.value;
        if (val === '__custom__') {
            textarea.classList.remove('qwen3-hidden');
            textarea.readOnly = false;
            textarea.value = '';
            textarea.focus();
        } else if (val === '') {
            textarea.classList.remove('qwen3-hidden');
            textarea.readOnly = false;
            textarea.value = '';
        } else {
            if (alwaysShow) {
                textarea.classList.remove('qwen3-hidden');
                textarea.readOnly = true;
            } else {
                textarea.classList.add('qwen3-hidden');
            }
            textarea.value = val;
        }
    });
}

function _getPresetValue(container, selectId, textareaId) {
    const select = container.querySelector(`#${selectId}`);
    const textarea = container.querySelector(`#${textareaId}`);
    if (!select || !textarea) return '';
    const val = select.value;
    if (val === '__custom__' || val === '') return textarea.value;
    return val;
}


// ── Tab Switching & Event Wiring ──

function _attachListeners(container) {
    // Help button
    container.querySelector('#qwen3-help-btn')?.addEventListener('click', _showHelpModal);

    // Tabs
    container.querySelectorAll('.qwen3-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            container.querySelectorAll('.qwen3-tab').forEach(t => t.classList.remove('active'));
            container.querySelectorAll('.qwen3-panel').forEach(p => p.classList.remove('active'));
            tab.classList.add('active');
            const panel = container.querySelector(`#qwen3-panel-${tab.dataset.tab}`);
            if (panel) panel.classList.add('active');
        });
    });

    // Preset dropdowns
    _setupPresetDropdown(container, 'qwen3-design-preset', 'qwen3-design-instruct');
    _setupPresetDropdown(container, 'qwen3-clone-ref-preset', 'qwen3-clone-ref-text', { alwaysShowTextarea: true });
    _setupPresetDropdown(container, 'qwen3-custom-style-preset', 'qwen3-custom-instruct');

    // Open folder button
    container.querySelector('#qwen3-clone-folder')?.addEventListener('click', async () => {
        // This opens the voices/audio folder via the plugin API
        try {
            await _apiPost('open-folder', {});
        } catch {}
    });

    // Voice Design
    _attachGenerateBtn(container, 'design', async () => {
        const text = container.querySelector('#qwen3-design-text')?.value;
        const instruct = _getPresetValue(container, 'qwen3-design-preset', 'qwen3-design-instruct');
        const language = container.querySelector('#qwen3-design-lang')?.value;
        return await _apiPost('generate/design', { text, instruct, language });
    });
    _attachSaveBtn(container, 'design', () => ({
        type: 'voice_design',
        instruct: _getPresetValue(container, 'qwen3-design-preset', 'qwen3-design-instruct'),
        language: container.querySelector('#qwen3-design-lang')?.value || 'Auto',
    }));

    // Voice Clone
    _attachGenerateBtn(container, 'clone', async () => {
        const fileInput = container.querySelector('#qwen3-clone-file');
        if (!fileInput?.files?.length) return { error: 'Please upload or record reference audio first' };

        const refAudioB64 = await _fileToBase64(fileInput.files[0]);
        const text = container.querySelector('#qwen3-clone-target')?.value;
        const ref_text = _getPresetValue(container, 'qwen3-clone-ref-preset', 'qwen3-clone-ref-text');
        const x_vector_only = container.querySelector('#qwen3-clone-xvector')?.checked;
        const language = container.querySelector('#qwen3-clone-lang')?.value;

        // Upload ref audio first so it's saved for the profile
        const uploadRes = await _apiPost('upload-ref', { audio: refAudioB64, model_size: container._serverModelSize || '0.6B' });
        if (uploadRes.error) return uploadRes;
        container._cloneRefFilename = uploadRes.filename;

        return await _apiPost('generate/clone', {
            text, ref_audio: refAudioB64, ref_text, x_vector_only, language
        });
    });
    _attachSaveBtn(container, 'clone', () => ({
        type: 'voice_clone',
        ref_audio: container._cloneRefFilename || '',
        ref_text: _getPresetValue(container, 'qwen3-clone-ref-preset', 'qwen3-clone-ref-text'),
        x_vector_only: container.querySelector('#qwen3-clone-xvector')?.checked || false,
        language: container.querySelector('#qwen3-clone-lang')?.value || 'Auto',
    }));

    // Custom Voice
    _attachGenerateBtn(container, 'custom', async () => {
        const text = container.querySelector('#qwen3-custom-text')?.value;
        const speaker = container.querySelector('#qwen3-custom-speaker')?.value;
        const instruct = _getPresetValue(container, 'qwen3-custom-style-preset', 'qwen3-custom-instruct');
        const language = container.querySelector('#qwen3-custom-lang')?.value;
        return await _apiPost('generate/custom', { text, speaker, instruct, language });
    });
    _attachSaveBtn(container, 'custom', () => ({
        type: 'custom_voice',
        speaker: container.querySelector('#qwen3-custom-speaker')?.value || 'ryan',
        instruct: _getPresetValue(container, 'qwen3-custom-style-preset', 'qwen3-custom-instruct'),
        language: container.querySelector('#qwen3-custom-lang')?.value || 'English',
    }));

    // Mic recording
    _setupRecordButton(container);
}


// ── Generate Button Pattern ──

function _attachGenerateBtn(container, tab, generateFn) {
    const btn = container.querySelector(`#qwen3-${tab}-generate`);
    const saveBtn = container.querySelector(`#qwen3-${tab}-save`);
    const audioBox = container.querySelector(`#qwen3-${tab}-audio`);
    if (!btn) return;

    const originalText = btn.textContent;

    btn.addEventListener('click', async () => {
        btn.disabled = true;
        btn.textContent = '\u23F3 Generating...';
        audioBox.innerHTML = '<span class="text-muted">Generating audio \u2014 this can take 15-30 seconds...</span>';
        saveBtn.disabled = true;

        try {
            const result = await generateFn();
            if (result.error) {
                audioBox.innerHTML = `<span class="qwen3-error">\u2717 ${_esc(result.error)}</span>`;
            } else if (result.audio) {
                _playAudio(audioBox, result.audio);
                saveBtn.disabled = false;
                container._lastAudioB64 = result.audio;
            }
        } catch (e) {
            audioBox.innerHTML = `<span class="qwen3-error">\u2717 ${_esc(e.message)}</span>`;
        }
        btn.disabled = false;
        btn.textContent = originalText;
    });
}


// ── Save Button Pattern ──

function _attachSaveBtn(container, tab, getProfileData) {
    const btn = container.querySelector(`#qwen3-${tab}-save`);
    if (!btn) return;

    btn.addEventListener('click', async () => {
        const name = prompt('Give this voice a name:');
        if (!name) return;

        btn.disabled = true;
        btn.textContent = tab === 'clone' ? 'Saving & caching voice...' : 'Saving...';

        const data = getProfileData();
        data.name = name;

        // Tag with the current server's model size
        try {
            const statusRes = await fetch(`${API}/status`);
            const statusData = await statusRes.json();
            if (statusData.model_size) data.model_size = statusData.model_size;
        } catch { /* use server default */ }

        // Save preview audio if we have it
        if (container._lastAudioB64) {
            const uploadRes = await _apiPost('upload-ref', { audio: container._lastAudioB64, model_size: data.model_size || '0.6B' });
            if (uploadRes.filename) data.preview_audio = uploadRes.filename;
        }

        const result = await _apiPost('voices', data);
        if (result.error) {
            alert(`Save failed: ${result.error}`);
        } else {
            btn.textContent = '\u2713 Saved!';
            _loadLibrary(container);
            setTimeout(() => { btn.textContent = '\uD83D\uDCBE Save Voice'; btn.disabled = false; }, 2000);
            return;
        }
        btn.textContent = '\uD83D\uDCBE Save Voice';
        btn.disabled = false;
    });
}


// ── Voice Library ──

async function _loadLibrary(container) {
    const list = container.querySelector('#qwen3-library-list');
    if (!list) return;

    try {
        const r = await fetch(`${API}/voices`);
        const d = await r.json();
        const voices = d.voices || [];

        if (voices.length === 0) {
            list.innerHTML = `
                <div class="qwen3-library-empty">
                    <div class="qwen3-library-empty-icon">\uD83C\uDFB5</div>
                    <p>No saved voices yet.</p>
                    <p class="text-muted">Create one using the Voice Design, Voice Clone, or Custom Voice tabs above!</p>
                </div>
            `;
            return;
        }

        // Group voices: custom voices separate, clone/design by model size
        const customVoices = voices.filter(v => v.type === 'custom_voice');
        const modelVoices = {};
        for (const v of voices.filter(v => v.type !== 'custom_voice')) {
            const size = v.model_size || 'Unknown';
            if (!modelVoices[size]) modelVoices[size] = [];
            modelVoices[size].push(v);
        }

        const currentSize = container._serverModelSize || '0.6B';

        function _renderVoiceCard(v, dimmed) {
            const typeIcon = { voice_design: '\uD83C\uDFA8', voice_clone: '\uD83D\uDCCB', custom_voice: '\uD83C\uDF99\uFE0F' }[v.type] || '\uD83C\uDFB5';
            const typeLabel = { voice_design: 'Designed', voice_clone: 'Cloned', custom_voice: 'Custom' }[v.type] || v.type;
            const detail = v.instruct || v.speaker || '';
            return `
                <div class="qwen3-voice-card${dimmed ? ' qwen3-voice-card-inactive' : ''}" data-id="${_esc(v.id)}">
                    <div class="qwen3-voice-info">
                        <span class="qwen3-voice-icon">${typeIcon}</span>
                        <div>
                            <strong>${_esc(v.name)}</strong>
                            <span class="qwen3-voice-type">${typeLabel}</span>
                            ${detail ? `<div class="qwen3-voice-detail">${_esc(detail.substring(0, 100))}${detail.length > 100 ? '...' : ''}</div>` : ''}
                        </div>
                    </div>
                    <div class="qwen3-voice-actions">
                        <code class="qwen3-voice-id">qwen3:${_esc(v.id)}</code>
                        <button class="btn btn-sm btn-danger qwen3-delete-voice" data-id="${_esc(v.id)}">Delete</button>
                    </div>
                </div>
            `;
        }

        let html = '';

        // Custom Voices section (work on any model size)
        if (customVoices.length) {
            html += `
                <div class="qwen3-library-section">
                    <div class="qwen3-library-section-header">
                        <span class="qwen3-library-section-title">Custom Voices</span>
                        <span class="qwen3-library-section-count">${customVoices.length} voice${customVoices.length !== 1 ? 's' : ''}</span>
                        <span class="qwen3-library-section-active">All Sizes</span>
                    </div>
                    ${customVoices.map(v => _renderVoiceCard(v, false)).join('')}
                </div>
            `;
        }

        // Clone/Design voices by model size (current size first)
        const sortedSizes = Object.keys(modelVoices).sort((a, b) => {
            if (a === currentSize) return -1;
            if (b === currentSize) return 1;
            return a.localeCompare(b);
        });
        for (const size of sortedSizes) {
            const sizeVoices = modelVoices[size];
            const isActive = size === currentSize;
            html += `
                <div class="qwen3-library-section">
                    <div class="qwen3-library-section-header">
                        <span class="qwen3-library-section-title">${_esc(size)} Voices</span>
                        <span class="qwen3-library-section-count">${sizeVoices.length} voice${sizeVoices.length !== 1 ? 's' : ''}</span>
                        ${isActive ? '<span class="qwen3-library-section-active">Active</span>' : '<span class="qwen3-library-section-inactive">Inactive</span>'}
                    </div>
                    ${sizeVoices.map(v => _renderVoiceCard(v, !isActive)).join('')}
                </div>
            `;
        }
        list.innerHTML = html;

        // Wire delete buttons
        list.querySelectorAll('.qwen3-delete-voice').forEach(btn => {
            btn.addEventListener('click', async () => {
                if (!confirm('Delete this voice? This cannot be undone.')) return;
                btn.disabled = true;
                const id = btn.dataset.id;
                await fetch(`${API}/voices/${id}`, {
                    method: 'DELETE',
                    headers: { 'X-CSRF-Token': CSRF() }
                });
                _loadLibrary(container);
            });
        });
    } catch (e) {
        list.innerHTML = `<p class="qwen3-error">Failed to load voices: ${_esc(e.message)}</p>`;
    }
}


// ── API helper ──

async function _apiPost(path, body) {
    try {
        const r = await fetch(`${API}/${path}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF() },
            body: JSON.stringify(body),
        });
        return await r.json();
    } catch (e) {
        return { error: e.message };
    }
}

export default { init() {} };
