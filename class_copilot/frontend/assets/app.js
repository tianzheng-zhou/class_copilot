/**
 * 听课助手 - 前端主应用
 */

// ──────────── 状态管理 ────────────
const state = {
    ws: null,
    isListening: false,
    sessionId: null,
    courseName: '',
    filterMode: 'all',
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
        case 'notification':
            if (data.type === 'error') {
                showToast(data.message, 'error');
            } else {
                showToast(data.message);
            }
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

    const { text, is_final, speaker_label, is_teacher, sentence_id, start_time, end_time } = data;

    if (!is_final) {
        // 中间结果：更新或创建临时元素
        let el = state.interimSegments[sentence_id];
        if (!el) {
            el = createTransSegment(speaker_label, is_teacher, text, true, start_time, end_time);
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
            // 更新时间戳
            const tsEl = el.querySelector('.speaker-timestamp');
            if (tsEl) tsEl.textContent = formatTimestamp(start_time, end_time);
            delete state.interimSegments[sentence_id];
        } else {
            el = createTransSegment(speaker_label, is_teacher, text, false, start_time, end_time);
            area.appendChild(el);
        }
    }

    // 自动滚动到底部
    area.scrollTop = area.scrollHeight;
}

function createTransSegment(speakerLabel, isTeacher, text, isInterim, startTime, endTime) {
    const el = document.createElement('div');
    el.className = 'trans-segment';

    // 无说话人信息时不显示标签
    const hasSpeaker = speakerLabel && speakerLabel !== 'UNKNOWN';
    const timeStr = formatTimestamp(startTime, endTime);

    let labelHtml = '';
    if (isTeacher) {
        labelHtml = `<div class="speaker-label speaker-teacher">${escapeHtml('👨‍🏫 教师')}<span class="speaker-timestamp">${timeStr}</span></div>`;
    } else if (hasSpeaker) {
        labelHtml = `<div class="speaker-label speaker-other">${escapeHtml('🗣️ ' + speakerLabel)}<span class="speaker-timestamp">${timeStr}</span></div>`;
    } else if (timeStr) {
        labelHtml = `<div class="speaker-label"><span class="speaker-timestamp">${timeStr}</span></div>`;
    }

    el.innerHTML = `
        ${labelHtml}
        <div class="trans-text ${isInterim ? 'interim' : ''}">${escapeHtml(text)}</div>
    `;

    return el;
}

function formatTimestamp(startTime, endTime) {
    if (startTime == null && endTime == null) return '';
    const fmt = (t) => {
        if (t == null || t <= 0) return '--:--';
        const totalSec = Math.floor(t);
        const min = String(Math.floor(totalSec / 60)).padStart(2, '0');
        const sec = String(totalSec % 60).padStart(2, '0');
        return `${min}:${sec}`;
    };
    return `${fmt(startTime)} - ${fmt(endTime)}`;
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
        if (data.model) q.model = data.model;
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
        const modelTag = q.model ? `<span class="answer-model-tag">${escapeHtml(q.model)}</span>` : '';

        return `
            <div class="answer-card" data-qid="${q.id}">
                <div class="answer-card-header">
                    <div class="answer-card-question">${escapeHtml(q.text)}</div>
                    <div class="answer-card-source">${q.sourceIcon} ${modelTag}</div>
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
        const modelLabel = state._chatModelLabel || '';
        lastAI = document.createElement('div');
        lastAI.className = 'chat-message chat-message-ai';
        lastAI.innerHTML = `
            <div class="chat-bubble">
                <div class="chat-role">🤖 AI <span class="answer-model-tag">${escapeHtml(modelLabel)}</span></div>
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

    const modelValue = document.getElementById('chatModel').value || 'quality';
    const modelLabel = document.getElementById('chatModel').selectedOptions[0]?.text || modelValue;
    const thinkMode = document.getElementById('chatThinkMode').checked;

    // 记录当前聊天使用的模型名
    state._chatModelLabel = modelLabel;

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
    sendMessage('chat', { question, model: modelValue, think_mode: thinkMode });
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
        // 精修进行中时更新精修面板
        const refinedArea = document.getElementById('refinedTranscriptionArea');
        if (refinedArea && refinedArea.querySelector('.empty-hint')) {
            refinedArea.innerHTML = `<div class="refined-loading">⏳ 精修中 (${Math.round(data.progress * 100)}%)...</div>`;
        }
    } else if (data.status === 'completed') {
        el.style.display = 'inline';
        el.textContent = '精修完成 ✓';
        setTimeout(() => { el.style.display = 'none'; }, 5000);
        // 精修完成 → 加载精修结果
        if (data.session_id || state.sessionId) {
            loadRefinedTranscriptions(data.session_id || state.sessionId);
        }
    } else {
        el.style.display = 'none';
    }
}

async function loadRefinedTranscriptions(sessionId) {
    if (!sessionId) return;
    const area = document.getElementById('refinedTranscriptionArea');
    if (!area) return;

    area.innerHTML = '<div class="refined-loading">加载精修结果...</div>';

    try {
        const resp = await fetch(`/api/sessions/${sessionId}`);
        const detail = await resp.json();

        const transcriptions = detail.transcriptions || [];
        const hasRefined = transcriptions.some(t => t.refined_text);

        if (!hasRefined) {
            area.innerHTML = '<div class="empty-hint">暂无精修结果</div>';
            return;
        }

        area.innerHTML = '';
        transcriptions.forEach(t => {
            if (t.refined_text) {
                const el = createTransSegment(
                    t.speaker_label, t.is_teacher, t.refined_text, false,
                    t.start_time, t.end_time
                );
                area.appendChild(el);
            }
        });
    } catch (e) {
        console.error('加载精修结果失败:', e);
        area.innerHTML = '<div class="empty-hint">加载精修结果失败</div>';
    }
}

// ──────────── 转写子标签页 ────────────
function switchSubTab(subtabName) {
    const panel = document.getElementById('tab-transcription');
    panel.querySelectorAll('.sub-tab').forEach(t => t.classList.remove('active'));
    panel.querySelectorAll('.sub-panel').forEach(p => p.classList.remove('active'));

    panel.querySelector(`.sub-tab[data-subtab="${subtabName}"]`).classList.add('active');
    document.getElementById(subtabName === 'realtime' ? 'subtab-realtime' : 'subtab-refined').classList.add('active');

    // 如果切到精修标签且有 session，尝试加载
    if (subtabName === 'refined' && state.sessionId) {
        const refinedArea = document.getElementById('refinedTranscriptionArea');
        if (refinedArea && refinedArea.querySelector('.empty-hint')) {
            loadRefinedTranscriptions(state.sessionId);
        }
    }
}

function switchHistoryTransTab(btn, panelName) {
    // 切换按钮高亮
    btn.closest('.history-sub-tabs').querySelectorAll('.history-trans-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    // 切换面板
    const container = btn.closest('.history-sub-tabs').parentElement;
    container.querySelectorAll('.history-trans-panel').forEach(p => p.style.display = 'none');
    container.querySelector(`.history-trans-panel[data-panel="${panelName}"]`).style.display = 'block';
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

        // 转写 - 含原始/精修子标签
        const hasRefined = detail.transcriptions.some(t => t.refined_text);
        html += '<h4 style="margin-top:16px;">📝 转写记录</h4>';

        if (hasRefined) {
            html += `
                <div class="history-sub-tabs" style="display:flex;gap:4px;margin-bottom:8px;">
                    <button class="btn btn-small history-trans-tab active" onclick="switchHistoryTransTab(this,'original')">📡 原始转写</button>
                    <button class="btn btn-small history-trans-tab" onclick="switchHistoryTransTab(this,'refined')">✨ 精修转写</button>
                </div>
            `;
        }

        // 原始转写
        html += '<div class="history-trans-panel" data-panel="original">';
        detail.transcriptions.forEach(t => {
            const role = t.is_teacher ? '👨‍🏫 教师' : (t.speaker_label && t.speaker_label !== 'UNKNOWN' ? `🗣️ ${t.speaker_label}` : '');
            const ts = formatTimestamp(t.start_time, t.end_time);
            const labelColor = t.is_teacher ? 'var(--teacher-color)' : 'var(--student-color)';
            html += `<p><strong style="color:${labelColor}">${escapeHtml(role)}</strong>${role ? ' ' : ''}<span style="color:var(--text-muted);font-size:11px;">${ts}</span><br>${escapeHtml(t.realtime_text || t.text)}</p>`;
        });
        html += '</div>';

        // 精修转写
        if (hasRefined) {
            html += '<div class="history-trans-panel" data-panel="refined" style="display:none;">';
            detail.transcriptions.forEach(t => {
                if (!t.refined_text) return;
                const role = t.is_teacher ? '👨‍🏫 教师' : (t.speaker_label && t.speaker_label !== 'UNKNOWN' ? `🗣️ ${t.speaker_label}` : '');
                const ts = formatTimestamp(t.start_time, t.end_time);
                const labelColor = t.is_teacher ? 'var(--teacher-color)' : 'var(--student-color)';
                html += `<p><strong style="color:${labelColor}">${escapeHtml(role)}</strong>${role ? ' ' : ''}<span style="color:var(--text-muted);font-size:11px;">${ts}</span><br>${escapeHtml(t.refined_text)}</p>`;
            });
            html += '</div>';
        }

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

        // ASR 提供商
        document.getElementById('settingAsrProvider').value = data.asr_provider || 'dashscope';
        document.getElementById('settingRefinementProvider').value = data.refinement_provider || 'dashscope';
        document.getElementById('settingDoubaoAudioBaseUrl').value = data.doubao_audio_base_url || '';
        document.getElementById('settingAutoAnswerModel').value = data.auto_answer_model || 'qwen3.5-flash';

        // 更新自动回答模型选择器的选项
        const autoAnswerSelect = document.getElementById('settingAutoAnswerModel');
        const fastModel = data.llm_model_fast || 'qwen3.5-flash';
        const qualityModel = data.llm_model_quality || 'qwen3.5-plus';
        autoAnswerSelect.innerHTML = `
            <option value="${escapeHtml(fastModel)}">${escapeHtml(fastModel)}（快速）</option>
            <option value="${escapeHtml(qualityModel)}">${escapeHtml(qualityModel)}（高质量）</option>
        `;
        autoAnswerSelect.value = data.auto_answer_model || fastModel;

        // 更新 Chat 模型选择器显示实际模型名
        const chatModelSelect = document.getElementById('chatModel');
        chatModelSelect.innerHTML = `
            <option value="fast">${escapeHtml(data.llm_model_fast || 'qwen3.5-flash')}</option>
            <option value="quality">${escapeHtml(data.llm_model_quality || 'qwen3.5-plus')}</option>
        `;

        toggleRefinementSettings();
        toggleDoubaoSettings();

        // 加载密钥配置状态
        try {
            const keysResp = await fetch('/api/settings');
            const keysData = await keysResp.json();
            const apiKeyEl = document.getElementById('settingApiKey');
            const doubaoAppidEl = document.getElementById('settingDoubaoAppid');
            const doubaoTokenEl = document.getElementById('settingDoubaoToken');
            apiKeyEl.placeholder = keysData.dashscope_api_key ? `✅ 已配置 (${keysData.dashscope_api_key}) — 留空保持不变` : '未配置';
            if (keysData.doubao_appid) {
                doubaoAppidEl.value = keysData.doubao_appid;
            }
            doubaoAppidEl.placeholder = keysData.doubao_appid ? '✅ 已配置' : '未配置';
            const doubaoKey = keysData.doubao_access_token || keysData.doubao_api_key;
            doubaoTokenEl.placeholder = doubaoKey ? `✅ 已配置 (${doubaoKey}) — 留空保持不变` : '未配置';
        } catch (e) {
            console.warn('加载密钥状态失败:', e);
        }

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
        // 保存 DashScope API Key
        const apiKey = document.getElementById('settingApiKey').value;
        if (apiKey) {
            await fetch('/api/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: 'dashscope_api_key', value: apiKey, is_encrypted: true }),
            });
        }

        // 保存豆包凭据
        const doubaoAppid = document.getElementById('settingDoubaoAppid').value;
        if (doubaoAppid) {
            await fetch('/api/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: 'doubao_appid', value: doubaoAppid, is_encrypted: false }),
            });
        }
        const doubaoToken = document.getElementById('settingDoubaoToken').value;
        if (doubaoToken) {
            await fetch('/api/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: 'doubao_access_token', value: doubaoToken, is_encrypted: true }),
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
                asr_provider: document.getElementById('settingAsrProvider').value,
                refinement_provider: document.getElementById('settingRefinementProvider').value,
                doubao_audio_base_url: document.getElementById('settingDoubaoAudioBaseUrl').value,
                auto_answer_model: document.getElementById('settingAutoAnswerModel').value,
            }),
        });

        // 保存麦克风
        const mic = document.getElementById('settingMicrophone').value;
        await fetch('/api/audio/device', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device_index: mic ? parseInt(mic) : null }),
        });

        // 更新 placeholder 状态
        document.getElementById('settingApiKey').placeholder = document.getElementById('settingApiKey').value ? '✅ 已配置 — 留空保持不变' : document.getElementById('settingApiKey').placeholder;
        document.getElementById('settingDoubaoToken').placeholder = document.getElementById('settingDoubaoToken').value ? '✅ 已配置 — 留空保持不变' : document.getElementById('settingDoubaoToken').placeholder;
        // 清空密码字段（防止重复保存）
        document.getElementById('settingApiKey').value = '';
        document.getElementById('settingDoubaoToken').value = '';

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

function toggleDoubaoSettings() {
    const asrProvider = document.getElementById('settingAsrProvider').value;
    const refProvider = document.getElementById('settingRefinementProvider').value;
    const show = asrProvider === 'doubao' || refProvider === 'doubao';
    document.getElementById('doubaoSettings').style.display = show ? 'block' : 'none';
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

    // 转写子标签页
    document.querySelectorAll('.sub-tab').forEach(tab => {
        tab.addEventListener('click', () => switchSubTab(tab.dataset.subtab));
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
        // 从当前激活的子标签页复制
        const activeSubPanel = document.querySelector('#tab-transcription .sub-panel.active');
        const area = activeSubPanel ? activeSubPanel.querySelector('.transcription-area') : document.getElementById('transcriptionArea');
        const segments = area.querySelectorAll('.trans-segment');
        const text = Array.from(segments).map(s => {
            const label = s.querySelector('.speaker-label')?.textContent || '';
            const content = s.querySelector('.trans-text')?.textContent || '';
            return label ? `${label} ${content}` : content;
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
    document.getElementById('settingAsrProvider').addEventListener('change', toggleDoubaoSettings);
    document.getElementById('settingRefinementProvider').addEventListener('change', toggleDoubaoSettings);

    // 设置标签页切换
    document.querySelectorAll('.settings-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.settings-pane').forEach(p => p.classList.remove('active'));
            tab.classList.add('active');
            const pane = document.querySelector(`.settings-pane[data-settings-pane="${tab.dataset.settingsTab}"]`);
            if (pane) pane.classList.add('active');
        });
    });

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
