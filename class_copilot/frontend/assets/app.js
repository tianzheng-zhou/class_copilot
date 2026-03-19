/**
 * 听课助手 - 前端主应用
 */

// ──────────── 状态管理 ────────────
const state = {
    ws: null,
    isListening: false,
    sessionId: null,
    courseName: '',
    filterMode: 'teacher_only',
    questions: [],  // {id, question, source, answers: {brief: '', detailed: ''}, showDetailed: false}
    currentAnswerType: 'brief',
    recordingStartTime: null,
    recordingTimer: null,
    interimSegments: {},  // sentence_id -> element
};

// ──────────── Markdown 渲染 ────────────
const renderer = {
    render(text) {
        if (typeof marked !== 'undefined') {
            const html = marked.parse(text);
            if (typeof DOMPurify !== 'undefined') {
                return DOMPurify.sanitize(html);
            }
            return html;
        }
        return escapeHtml(text);
    }
};

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function highlightCode() {
    if (typeof hljs !== 'undefined') {
        document.querySelectorAll('.chat-bubble pre code').forEach(el => {
            hljs.highlightElement(el);
        });
    }
}

// ──────────── WebSocket ────────────
let reconnectAttempts = 0;
const MAX_RECONNECT = 10;

function connectWS() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws`;

    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
        console.log('WebSocket connected');
        reconnectAttempts = 0;
        updateConnectionStatus(true);
    };

    state.ws.onclose = () => {
        console.log('WebSocket disconnected');
        updateConnectionStatus(false);
        scheduleReconnect();
    };

    state.ws.onerror = (e) => {
        console.error('WebSocket error:', e);
    };

    state.ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        handleServerMessage(message);
    };
}

function scheduleReconnect() {
    if (reconnectAttempts >= MAX_RECONNECT) return;
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
    reconnectAttempts++;
    setTimeout(connectWS, delay);
}

function sendMessage(type, data = {}) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({ type, data }));
    }
}

function updateConnectionStatus(connected) {
    const indicator = document.getElementById('statusIndicator');
    if (connected) {
        indicator.className = 'status-indicator status-ready';
        indicator.textContent = '● 已连接';
    } else {
        indicator.className = 'status-indicator status-error';
        indicator.textContent = '● 断开连接';
    }
}

// ──────────── 消息处理 ────────────
function handleServerMessage(msg) {
    const { type, data } = msg;

    switch (type) {
        case 'status':
            handleStatus(data);
            break;
        case 'transcription':
            handleTranscription(data);
            break;
        case 'question_detected':
            handleQuestionDetected(data);
            break;
        case 'answer_generating':
            handleAnswerGenerating(data);
            break;
        case 'answer_chunk':
            handleAnswerChunk(data);
            break;
        case 'answer_complete':
            handleAnswerComplete(data);
            break;
        case 'chat_chunk':
            handleChatChunk(data);
            break;
        case 'chat_complete':
            handleChatComplete(data);
            break;
        case 'filter_mode':
            handleFilterMode(data);
            break;
        case 'refinement_status':
            handleRefinementStatus(data);
            break;
        case 'info':
            showToast(data.message);
            break;
        case 'error':
            showToast(data.message, 'error');
            break;
    }
}

// ──────────── 状态处理 ────────────
function handleStatus(data) {
    state.isListening = data.status === 'listening';
    state.sessionId = data.session_id;
    state.filterMode = data.filter_mode || 'teacher_only';

    updateListenButton();
    updateStatusText(data.status);
    updateFilterBadge();
}

function updateListenButton() {
    const btn = document.getElementById('btnToggleListen');
    if (state.isListening) {
        btn.classList.add('recording');
        btn.querySelector('.btn-text').textContent = '停止监听';
        btn.querySelector('.btn-icon').textContent = '⏹️';
        startRecordingTimer();
    } else {
        btn.classList.remove('recording');
        btn.querySelector('.btn-text').textContent = '开始监听';
        btn.querySelector('.btn-icon').textContent = '🎤';
        stopRecordingTimer();
    }
}

function updateStatusText(status) {
    const map = {
        ready: '就绪',
        listening: '正在监听',
        stopped: '已停止',
        reconnecting: '正在重连...',
    };
    document.getElementById('statusText').textContent = map[status] || status;

    const indicator = document.getElementById('statusIndicator');
    if (status === 'listening') {
        indicator.className = 'status-indicator status-listening';
        indicator.textContent = '● 监听中';
    } else {
        indicator.className = 'status-indicator status-ready';
        indicator.textContent = '● ' + (map[status] || status);
    }
}

// ──────────── 录音计时器 ────────────
function startRecordingTimer() {
    state.recordingStartTime = Date.now();
    const el = document.getElementById('recordingTime');
    el.style.display = 'inline';

    state.recordingTimer = setInterval(() => {
        const elapsed = Math.floor((Date.now() - state.recordingStartTime) / 1000);
        const min = String(Math.floor(elapsed / 60)).padStart(2, '0');
        const sec = String(elapsed % 60).padStart(2, '0');
        el.textContent = `${min}:${sec}`;
    }, 1000);
}

function stopRecordingTimer() {
    if (state.recordingTimer) {
        clearInterval(state.recordingTimer);
        state.recordingTimer = null;
    }
    document.getElementById('recordingTime').style.display = 'none';
}

// ──────────── 转写处理 ────────────
function handleTranscription(data) {
    const area = document.getElementById('transcriptionArea');

    // 移除空提示
    const hint = area.querySelector('.empty-hint');
    if (hint) hint.remove();

    const { text, is_final, speaker_label, is_teacher, sentence_id } = data;

    if (!is_final) {
        // 中间结果：更新或创建临时元素
        let el = state.interimSegments[sentence_id];
        if (!el) {
            el = createTransSegment(speaker_label, is_teacher, text, true);
            area.appendChild(el);
            state.interimSegments[sentence_id] = el;
        } else {
            el.querySelector('.trans-text').textContent = text;
        }
    } else {
        // 最终结果：替换中间结果或新建
        let el = state.interimSegments[sentence_id];
        if (el) {
            el.querySelector('.trans-text').textContent = text;
            el.querySelector('.trans-text').classList.remove('interim');
            delete state.interimSegments[sentence_id];
        } else {
            el = createTransSegment(speaker_label, is_teacher, text, false);
            area.appendChild(el);
        }
    }

    // 自动滚动到底部
    area.scrollTop = area.scrollHeight;
}

function createTransSegment(speakerLabel, isTeacher, text, isInterim) {
    const el = document.createElement('div');
    el.className = 'trans-segment';

    const labelClass = isTeacher ? 'speaker-teacher' : 'speaker-other';
    const displayLabel = isTeacher ? '👨‍🏫 教师' : `🗣️ ${speakerLabel}`;

    el.innerHTML = `
        <div class="speaker-label ${labelClass}">${escapeHtml(displayLabel)}</div>
        <div class="trans-text ${isInterim ? 'interim' : ''}">${escapeHtml(text)}</div>
    `;

    return el;
}

// ──────────── 问题/答案处理 ────────────
function handleQuestionDetected(data) {
    const sourceIcons = { auto: '🔍', manual: '✋', forced: '💬', refined: '🔄' };

    const question = {
        id: data.question_id,
        text: data.question,
        source: data.source,
        sourceIcon: sourceIcons[data.source] || '🔍',
        confidence: data.confidence,
        answers: { brief: '', detailed: '' },
        generating: { brief: false, detailed: false },
        showDetailed: false,
    };

    state.questions.unshift(question);
    renderAnswers();

    // 切换到回答标签
    switchTab('answers');
    showToast(`检测到问题: ${data.question.substring(0, 50)}...`, 'success');
}

function handleAnswerGenerating(data) {
    const q = state.questions.find(q => q.id === data.question_id);
    if (q) {
        q.generating[data.answer_type] = true;
        renderAnswers();
    }
}

function handleAnswerChunk(data) {
    const q = state.questions.find(q => q.id === data.question_id);
    if (q) {
        q.answers[data.answer_type] = data.full_text;
        renderAnswers();
    }
}

function handleAnswerComplete(data) {
    const q = state.questions.find(q => q.id === data.question_id);
    if (q) {
        q.answers[data.answer_type] = data.content;
        q.generating[data.answer_type] = false;
        renderAnswers();
    }
}

function renderAnswers() {
    const area = document.getElementById('answersArea');

    if (state.questions.length === 0) {
        area.innerHTML = '<div class="empty-hint">等待检测到课堂问题...</div>';
        return;
    }

    area.innerHTML = state.questions.map(q => {
        const showType = q.showDetailed ? 'detailed' : 'brief';
        const answerText = q.answers[showType] || '';
        const isGenerating = q.generating[showType];

        return `
            <div class="answer-card" data-qid="${q.id}">
                <div class="answer-card-header">
                    <div class="answer-card-question">${escapeHtml(q.text)}</div>
                    <div class="answer-card-source">${q.sourceIcon}</div>
                </div>
                <div class="answer-card-body">
                    <div class="answer-toggle">
                        <button class="${!q.showDetailed ? 'active' : ''}" onclick="toggleAnswerType('${q.id}', false)">简洁版</button>
                        <button class="${q.showDetailed ? 'active' : ''}" onclick="toggleAnswerType('${q.id}', true)">展开版</button>
                    </div>
                    <div class="answer-text ${isGenerating ? 'answer-generating' : ''}">
                        ${isGenerating && !answerText ? '正在生成答案...' : escapeHtml(answerText)}
                    </div>
                    <div class="answer-actions">
                        <button class="btn btn-small" onclick="copyText('${q.id}')">📋 复制</button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function toggleAnswerType(qid, showDetailed) {
    const q = state.questions.find(q => q.id === qid);
    if (q) {
        q.showDetailed = showDetailed;
        renderAnswers();
    }
}

function copyText(qid) {
    const q = state.questions.find(q => q.id === qid);
    if (q) {
        const type = q.showDetailed ? 'detailed' : 'brief';
        navigator.clipboard.writeText(q.answers[type] || '').then(() => {
            showToast('已复制到剪贴板', 'success');
        });
    }
}

// ──────────── 主动提问 ────────────
let chatStreamBuffer = '';

function handleChatChunk(data) {
    chatStreamBuffer = data.full_text;
    updateLastAIMessage(chatStreamBuffer, false);
}

function handleChatComplete(data) {
    chatStreamBuffer = '';
    updateLastAIMessage(data.content, true);
}

function updateLastAIMessage(content, isFinal) {
    const area = document.getElementById('chatArea');
    let lastAI = area.querySelector('.chat-message-ai:last-child');

    if (!lastAI) {
        lastAI = document.createElement('div');
        lastAI.className = 'chat-message chat-message-ai';
        lastAI.innerHTML = `
            <div class="chat-bubble">
                <div class="chat-role">🤖 AI</div>
                <div class="chat-content"></div>
            </div>
        `;
        area.appendChild(lastAI);
    }

    const contentEl = lastAI.querySelector('.chat-content');
    if (isFinal) {
        contentEl.innerHTML = renderer.render(content);
        highlightCode();
    } else {
        contentEl.innerHTML = renderer.render(content) + '<span class="typing-cursor">|</span>';
    }

    area.scrollTop = area.scrollHeight;
}

function sendChat() {
    const input = document.getElementById('chatInput');
    const question = input.value.trim();
    if (!question) return;

    const model = document.getElementById('chatModel').value || undefined;
    const thinkMode = document.getElementById('chatThinkMode').checked;

    // 添加用户消息
    const area = document.getElementById('chatArea');
    const hint = area.querySelector('.empty-hint');
    if (hint) hint.remove();

    const userMsg = document.createElement('div');
    userMsg.className = 'chat-message chat-message-user';
    userMsg.innerHTML = `
        <div class="chat-bubble">
            <div class="chat-role">🙋 你</div>
            <div class="chat-content">${escapeHtml(question)}</div>
        </div>
    `;
    area.appendChild(userMsg);
    area.scrollTop = area.scrollHeight;

    // 发送
    sendMessage('chat', { question, model, think_mode: thinkMode });
    input.value = '';
}

// ──────────── 过滤模式 ────────────
function handleFilterMode(data) {
    state.filterMode = data.mode;
    updateFilterBadge();
}

function updateFilterBadge() {
    const badge = document.getElementById('filterMode');
    badge.textContent = state.filterMode === 'teacher_only' ? '仅教师' : '所有人';
}

// ──────────── 精修状态 ────────────
function handleRefinementStatus(data) {
    const el = document.getElementById('refinementStatus');
    if (data.status === 'in_progress') {
        el.style.display = 'inline';
        el.textContent = `精修中 (${Math.round(data.progress * 100)}%)`;
    } else if (data.status === 'completed') {
        el.style.display = 'inline';
        el.textContent = '精修完成 ✓';
        setTimeout(() => { el.style.display = 'none'; }, 5000);
    } else {
        el.style.display = 'none';
    }
}

// ──────────── 历史记录 ────────────
async function loadHistory() {
    try {
        const resp = await fetch('/api/sessions');
        const sessions = await resp.json();
        renderHistoryList(sessions);
    } catch (e) {
        console.error('加载历史失败:', e);
    }
}

function renderHistoryList(sessions) {
    const list = document.getElementById('historyList');

    if (!sessions.length) {
        list.innerHTML = '<div class="empty-hint">暂无历史记录</div>';
        return;
    }

    list.innerHTML = sessions.map(s => {
        const statusBadge = {
            active: '🟢 进行中',
            stopped: '⏹️ 已结束',
            interrupted: '⚠️ 中断',
        }[s.status] || s.status;

        const refineBadge = s.refinement_status !== 'none'
            ? `<span class="refinement-status">${s.refinement_status === 'completed' ? '✓ 已精修' : '🔄 精修中'}</span>`
            : '';

        return `
            <div class="history-item" onclick="viewSession('${s.id}')">
                <div class="history-item-info">
                    <div class="history-item-date">${escapeHtml(s.date)}</div>
                    <div class="history-item-course">${escapeHtml(s.course_name)}</div>
                </div>
                <div style="display:flex;align-items:center;gap:8px;">
                    <span class="history-item-status">${statusBadge}</span>
                    ${refineBadge}
                    <div class="history-item-actions">
                        <button class="btn btn-small" onclick="event.stopPropagation();exportSession('${s.id}')">📥 导出</button>
                        <button class="btn btn-small" onclick="event.stopPropagation();deleteSession('${s.id}')">🗑️</button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

async function viewSession(sessionId) {
    try {
        const resp = await fetch(`/api/sessions/${sessionId}`);
        const detail = await resp.json();

        document.getElementById('historyList').style.display = 'none';
        const detailEl = document.getElementById('historyDetail');
        detailEl.style.display = 'block';

        let html = `<h3>${escapeHtml(detail.session.course_name)} - ${escapeHtml(detail.session.date)}</h3>`;

        // 转写
        html += '<h4 style="margin-top:16px;">📝 转写记录</h4>';
        detail.transcriptions.forEach(t => {
            const role = t.is_teacher ? '👨‍🏫 教师' : `🗣️ ${t.speaker_label}`;
            html += `<p><strong style="color:${t.is_teacher ? 'var(--teacher-color)' : 'var(--student-color)'}">${escapeHtml(role)}</strong>: ${escapeHtml(t.text)}</p>`;
        });

        // 问题和答案
        if (detail.questions.length) {
            html += '<h4 style="margin-top:16px;">💡 检测到的问题</h4>';
            detail.questions.forEach(q => {
                const sourceIcons = { auto: '🔍', manual: '✋', forced: '💬', refined: '🔄' };
                html += `<div class="answer-card" style="margin-top:8px;">
                    <div class="answer-card-header">
                        <div class="answer-card-question">${escapeHtml(q.question_text)}</div>
                        <div>${sourceIcons[q.source] || ''}</div>
                    </div>
                    <div class="answer-card-body">
                        ${q.answers.map(a => `
                            <div style="margin-bottom:8px;">
                                <strong>${a.answer_type === 'brief' ? '简洁版' : '展开版'}:</strong>
                                <div>${escapeHtml(a.content)}</div>
                            </div>
                        `).join('')}
                    </div>
                </div>`;
            });
        }

        // 主动提问
        if (detail.chat_messages.length) {
            html += '<h4 style="margin-top:16px;">💬 主动提问</h4>';
            detail.chat_messages.forEach(m => {
                if (m.role === 'user') {
                    html += `<p>🙋 <strong>你:</strong> ${escapeHtml(m.content)}</p>`;
                } else {
                    html += `<div style="margin:8px 0;">${renderer.render(m.content)}</div>`;
                }
            });
        }

        document.getElementById('historyContent').innerHTML = html;
        highlightCode();

    } catch (e) {
        showToast('加载失败', 'error');
    }
}

async function exportSession(sessionId) {
    window.open(`/api/sessions/${sessionId}/export`, '_blank');
}

async function deleteSession(sessionId) {
    if (!confirm('确认删除此会话？录音和所有记录将被永久删除。')) return;
    try {
        await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
        showToast('已删除', 'success');
        loadHistory();
    } catch (e) {
        showToast('删除失败', 'error');
    }
}

// ──────────── 设置 ────────────
async function loadSettings() {
    try {
        // 加载运行时设置
        const resp = await fetch('/api/settings/runtime');
        const data = await resp.json();

        document.getElementById('settingLanguage').value = data.language || 'zh';
        document.getElementById('settingBrief').checked = data.enable_brief_answer;
        document.getElementById('settingDetailed').checked = data.enable_detailed_answer;
        document.getElementById('settingTranslation').checked = data.enable_translation;
        document.getElementById('settingBilingual').checked = data.enable_bilingual;
        document.getElementById('settingRefinement').checked = data.enable_refinement;
        document.getElementById('settingRefinementStrategy').value = data.refinement_strategy;
        document.getElementById('settingRefinementInterval').value = data.refinement_interval_minutes;

        toggleRefinementSettings();

        // 加载音频设备
        const devResp = await fetch('/api/audio/devices');
        const devices = await devResp.json();
        const micSelect = document.getElementById('settingMicrophone');
        micSelect.innerHTML = '<option value="">系统默认</option>' +
            devices.map(d => `<option value="${d.index}" ${d.is_default ? 'selected' : ''}>${escapeHtml(d.name)}</option>`).join('');

        // 加载课程列表
        const courseResp = await fetch('/api/courses');
        const courses = await courseResp.json();
        const courseList = document.getElementById('courseList');
        courseList.innerHTML = courses.map(c => `<option value="${escapeHtml(c.name)}">`).join('');

    } catch (e) {
        console.error('加载设置失败:', e);
    }
}

async function saveSettings() {
    try {
        // 保存 API Key
        const apiKey = document.getElementById('settingApiKey').value;
        if (apiKey) {
            await fetch('/api/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: 'dashscope_api_key', value: apiKey, is_encrypted: true }),
            });
        }

        // 保存运行时设置
        await fetch('/api/settings/runtime', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                language: document.getElementById('settingLanguage').value,
                enable_brief_answer: document.getElementById('settingBrief').checked,
                enable_detailed_answer: document.getElementById('settingDetailed').checked,
                enable_translation: document.getElementById('settingTranslation').checked,
                enable_bilingual: document.getElementById('settingBilingual').checked,
                enable_refinement: document.getElementById('settingRefinement').checked,
                refinement_strategy: document.getElementById('settingRefinementStrategy').value,
                refinement_interval_minutes: parseInt(document.getElementById('settingRefinementInterval').value),
            }),
        });

        // 保存麦克风
        const mic = document.getElementById('settingMicrophone').value;
        await fetch('/api/audio/device', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device_index: mic ? parseInt(mic) : null }),
        });

        showToast('设置已保存', 'success');
        closeSettings();

    } catch (e) {
        showToast('保存失败', 'error');
    }
}

function toggleRefinementSettings() {
    const enabled = document.getElementById('settingRefinement').checked;
    document.getElementById('refinementSettings').style.display = enabled ? 'block' : 'none';
    document.getElementById('btnManualRefine').style.display = enabled ? 'inline-flex' : 'none';
}

function openSettings() {
    document.getElementById('settingsModal').style.display = 'flex';
    loadSettings();
}

function closeSettings() {
    document.getElementById('settingsModal').style.display = 'none';
}

// ──────────── 选项卡切换 ────────────
function switchTab(tabName) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));

    document.querySelector(`.tab[data-tab="${tabName}"]`).classList.add('active');
    document.getElementById(`tab-${tabName}`).classList.add('active');

    if (tabName === 'history') {
        loadHistory();
        document.getElementById('historyList').style.display = 'block';
        document.getElementById('historyDetail').style.display = 'none';
    }
}

// ──────────── Toast 通知 ────────────
function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ──────────── 事件绑定 ────────────
document.addEventListener('DOMContentLoaded', () => {
    // WebSocket 连接
    connectWS();

    // 选项卡
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    });

    // 监听按钮
    document.getElementById('btnToggleListen').addEventListener('click', () => {
        if (state.isListening) {
            sendMessage('stop_listening');
        } else {
            const courseName = document.getElementById('courseInput').value.trim();
            sendMessage('start_listening', { course_name: courseName });
        }
    });

    // 手动检测
    document.getElementById('btnManualDetect').addEventListener('click', () => {
        sendMessage('manual_detect');
    });

    // 复制最新答案
    document.getElementById('btnCopyAnswer').addEventListener('click', () => {
        if (state.questions.length > 0) {
            const q = state.questions[0];
            const type = q.showDetailed ? 'detailed' : 'brief';
            navigator.clipboard.writeText(q.answers[type] || '').then(() => {
                showToast('已复制最新答案', 'success');
            });
        }
    });

    // 手动精修
    document.getElementById('btnManualRefine').addEventListener('click', () => {
        sendMessage('manual_refine');
        showToast('已触发精修');
    });

    // 复制转写
    document.getElementById('btnCopyTranscription').addEventListener('click', () => {
        const area = document.getElementById('transcriptionArea');
        const segments = area.querySelectorAll('.trans-segment');
        const text = Array.from(segments).map(s => {
            const label = s.querySelector('.speaker-label')?.textContent || '';
            const content = s.querySelector('.trans-text')?.textContent || '';
            return `${label}: ${content}`;
        }).join('\n');
        navigator.clipboard.writeText(text).then(() => {
            showToast('已复制转写文本', 'success');
        });
    });

    // 发送提问
    document.getElementById('btnSendChat').addEventListener('click', sendChat);
    document.getElementById('chatInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendChat();
        }
    });

    // 过滤模式切换
    document.getElementById('filterMode').addEventListener('click', () => {
        sendMessage('toggle_filter_mode');
    });

    // 设置
    document.getElementById('btnSettings').addEventListener('click', openSettings);
    document.getElementById('btnCloseSettings').addEventListener('click', closeSettings);
    document.getElementById('btnSaveSettings').addEventListener('click', saveSettings);
    document.getElementById('settingRefinement').addEventListener('change', toggleRefinementSettings);

    // 历史返回
    document.getElementById('btnBackToList').addEventListener('click', () => {
        document.getElementById('historyList').style.display = 'block';
        document.getElementById('historyDetail').style.display = 'none';
    });

    // 设置面板外点击关闭
    document.getElementById('settingsModal').addEventListener('click', (e) => {
        if (e.target === document.getElementById('settingsModal')) {
            closeSettings();
        }
    });

    // 初始加载设置
    loadSettings();
});
