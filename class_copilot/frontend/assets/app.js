/**
 * 听课助手 - 前端主应用
 */

// ──────────── 状态管理 ────────────
const state = {
    ws: null,
    isListening: false,
    sessionId: null,
    sessionIds: [],  // 所有会话ID（用于精修结果累积显示）
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
        case 'auto_stop_tick':
            handleAutoStopTick(data);
            break;
        case 'recall_data':
            handleRecallData(data);
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

    // 跟踪所有会话ID，用于精修结果累积显示
    if (data.session_id && !state.sessionIds.includes(data.session_id)) {
        state.sessionIds.push(data.session_id);
    }

    // 更新课程名
    if (data.course_name) {
        state.courseName = data.course_name;
        document.getElementById('courseInput').value = data.course_name;
    }

    // 更新自动停止倒计时
    if (data.auto_stop_remaining > 0) {
        handleAutoStopTick({ remaining: data.auto_stop_remaining });
    } else {
        document.getElementById('autoStopCountdown').style.display = 'none';
    }

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
    document.getElementById('autoStopCountdown').style.display = 'none';
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
        if (t == null || t <= 0) return '--:--:--';
        // epoch 秒（绝对时间）：值大于 1e9 (约 2001 年)
        if (t > 1e9) {
            const d = new Date(t * 1000);
            return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`;
        }
        // 回退：相对时间 MM:SS
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
        // 精修完成 → 加载所有会话的精修结果（避免覆盖之前的精修记录）
        loadAllRefinedTranscriptions();
    } else {
        el.style.display = 'none';
    }
}

async function loadAllRefinedTranscriptions() {
    const area = document.getElementById('refinedTranscriptionArea');
    if (!area) return;

    const allSessionIds = state.sessionIds.length > 0
        ? state.sessionIds
        : (state.sessionId ? [state.sessionId] : []);
    if (allSessionIds.length === 0) return;

    area.innerHTML = '<div class="refined-loading">加载精修结果...</div>';

    try {
        let hasAnyRefined = false;
        area.innerHTML = '';

        for (const sid of allSessionIds) {
            const resp = await fetch(`/api/sessions/${sid}`);
            const detail = await resp.json();
            const transcriptions = detail.transcriptions || [];
            const refined = transcriptions.filter(t => t.refined_text);

            if (refined.length > 0) {
                hasAnyRefined = true;
                refined.forEach(t => {
                    const el = createTransSegment(
                        t.speaker_label, t.is_teacher, t.refined_text, false,
                        t.start_time, t.end_time
                    );
                    area.appendChild(el);
                });
            }
        }

        if (!hasAnyRefined) {
            area.innerHTML = '<div class="empty-hint">暂无精修结果</div>';
        }
    } catch (e) {
        console.error('加载精修结果失败:', e);
        area.innerHTML = '<div class="empty-hint">加载精修结果失败</div>';
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

// ──────────── 定时停止 ────────────
function getAutoStopInfo(showWarning = false) {
    const timeInput = document.getElementById('autoStopTime');
    const val = timeInput.value; // "HH:MM" or ""
    if (!val) return { seconds: 0, label: '' };

    const parts = val.split(':').map(Number);
    const h = parts[0], m = parts[1] || 0;
    const now = new Date();
    const target = new Date(now.getFullYear(), now.getMonth(), now.getDate(), h, m, 0, 0);

    // 如果目标时间已过（今天内），视为无效
    let diffMs = target.getTime() - now.getTime();
    if (diffMs <= 0) {
        if (showWarning) {
            showToast(`定时停止时间 ${val} 已过，未设置定时`, 'error');
        }
        return { seconds: 0, label: '' };
    }

    return { seconds: Math.ceil(diffMs / 1000), label: val };
}

function formatCountdown(remaining) {
    const hours = Math.floor(remaining / 3600);
    const min = String(Math.floor((remaining % 3600) / 60)).padStart(2, '0');
    const sec = String(remaining % 60).padStart(2, '0');
    return hours > 0 ? `${hours}:${min}:${sec}` : `${min}:${sec}`;
}

function handleAutoStopTick(data) {
    const remaining = data.remaining;
    const el = document.getElementById('autoStopCountdown');
    if (remaining > 0) {
        el.style.display = 'inline';
        el.textContent = `⏱️ ${formatCountdown(remaining)}`;
        // 最后60秒变红色警告
        el.style.color = remaining <= 60 ? '#f87171' : '';
    } else {
        el.style.display = 'none';
    }
}

// ──────────── 会话恢复 (Recall) ────────────
function handleRecallData(data) {
    // 清空当前面板
    const transArea = document.getElementById('transcriptionArea');
    transArea.innerHTML = '';

    const answersArea = document.getElementById('answersArea');
    state.questions = [];

    const chatArea = document.getElementById('chatArea');
    chatArea.innerHTML = '';

    // 设置当前会话信息
    state.sessionId = data.session_id;
    state.courseName = data.course_name;
    if (data.session_id && !state.sessionIds.includes(data.session_id)) {
        state.sessionIds.push(data.session_id);
    }

    document.getElementById('courseInput').value = data.course_name || '';

    // 恢复转写记录
    if (data.transcriptions && data.transcriptions.length > 0) {
        data.transcriptions.forEach(t => {
            const el = createTransSegment(
                t.speaker_label, t.is_teacher, t.text, false,
                t.start_time, t.end_time
            );
            el.classList.add('recalled');
            transArea.appendChild(el);
        });
    }

    // 恢复问题和答案
    if (data.questions && data.questions.length > 0) {
        const sourceIcons = { auto: '🔍', manual: '✋', forced: '💬', refined: '🔄' };
        data.questions.forEach(q => {
            state.questions.push({
                id: q.question_id,
                text: q.question,
                source: q.source,
                sourceIcon: sourceIcons[q.source] || '🔍',
                confidence: q.confidence,
                answers: q.answers || { brief: '', detailed: '' },
                generating: { brief: false, detailed: false },
                showDetailed: false,
            });
        });
        renderAnswers();
    }

    // 恢复聊天记录
    if (data.chat_messages && data.chat_messages.length > 0) {
        data.chat_messages.forEach(m => {
            const msgEl = document.createElement('div');
            if (m.role === 'user') {
                msgEl.className = 'chat-message chat-message-user';
                msgEl.innerHTML = `
                    <div class="chat-bubble">
                        <div class="chat-role">🙋 你</div>
                        <div class="chat-content">${escapeHtml(m.content)}</div>
                    </div>
                `;
            } else {
                msgEl.className = 'chat-message chat-message-ai';
                msgEl.innerHTML = `
                    <div class="chat-bubble">
                        <div class="chat-role">🤖 AI ${m.model_used ? '<span class="answer-model-tag">' + escapeHtml(m.model_used) + '</span>' : ''}</div>
                        <div class="chat-content">${renderer.render(m.content)}</div>
                    </div>
                `;
            }
            chatArea.appendChild(msgEl);
        });
        highlightCode();
    }

    // 切换到转写标签页
    switchTab('transcription');
    showToast(`已恢复会话: ${data.course_name}`, 'success');

    // 关闭历史详情视图（如果打开了的话）
    document.getElementById('historyList').style.display = 'block';
    document.getElementById('historyDetail').style.display = 'none';
}

function recallSession(sessionId) {
    if (state.isListening) {
        showToast('请先停止当前监听', 'error');
        return;
    }
    const { seconds, label } = getAutoStopInfo(true);
    sendMessage('recall_session', { session_id: sessionId, auto_stop_seconds: seconds, auto_stop_label: label });
}

function newRecording() {
    if (state.isListening) {
        // 先停止当前会话
        sendMessage('stop_listening');
        // 等待状态更新后再清空（通过 ws onmessage 触发 handleStatus）
        // 利用一次性监听：等到 status 变为 stopped 后清空 UI
        const onStopped = (event) => {
            const msg = JSON.parse(event.data);
            if (msg.type === 'status' && msg.data.status !== 'listening') {
                state.ws.removeEventListener('message', onStopped);
                resetUIForNewRecording();
            }
        };
        state.ws.addEventListener('message', onStopped);
    } else {
        resetUIForNewRecording();
    }
}

function resetUIForNewRecording() {
    // 清空转写区
    document.getElementById('transcriptionArea').innerHTML =
        '<div class="empty-hint">点击"开始监听"开始课堂转写...</div>';
    document.getElementById('refinedTranscriptionArea').innerHTML =
        '<div class="empty-hint">暂无精修内容</div>';

    // 清空回答区
    state.questions = [];
    renderAnswers();

    // 清空聊天区
    document.getElementById('chatArea').innerHTML = '';

    // 重置状态
    state.sessionId = null;
    state.sessionIds = [];
    state.interimSegments = {};

    // 清空课程输入
    document.getElementById('courseInput').value = '';

    // 切换到转写标签页
    switchTab('transcription');

    showToast('已准备好新录音', 'success');
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
        const params = new URLSearchParams();
        const dateFrom = document.getElementById('historyDateFrom')?.value;
        const dateTo = document.getElementById('historyDateTo')?.value;
        if (dateFrom) params.set('date_from', dateFrom);
        if (dateTo) params.set('date_to', dateTo);
        const qs = params.toString();
        const resp = await fetch('/api/sessions' + (qs ? '?' + qs : ''));
        const sessions = await resp.json();
        renderHistoryList(sessions);
    } catch (e) {
        console.error('加载历史失败:', e);
    }
}

function applyHistoryFilter() {
    loadHistory();
}

function clearHistoryFilter() {
    document.getElementById('historyDateFrom').value = '';
    document.getElementById('historyDateTo').value = '';
    loadHistory();
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

        // 仅对已停止或中断的会话显示恢复按钮
        const recallBtn = (s.status === 'stopped' || s.status === 'interrupted')
            ? `<button class="btn btn-small btn-recall" onclick="event.stopPropagation();recallSession('${s.id}')" title="恢复此会话继续转录">🔄 恢复</button>`
            : '';

        const startTime = s.started_at ? new Date(s.started_at).toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'}) : '';
        const displayName = s.custom_name || s.course_name;

        return `
            <div class="history-item" onclick="viewSession('${s.id}')">
                <div class="history-item-info">
                    <div class="history-item-date">${escapeHtml(s.date)}${startTime ? ' ' + startTime : ''}</div>
                    <div class="history-item-course">${escapeHtml(displayName)}${s.custom_name ? ` <span style="color:var(--text-muted);font-size:11px;">(${escapeHtml(s.course_name)})</span>` : ''}</div>
                </div>
                <div style="display:flex;align-items:center;gap:8px;">
                    <span class="history-item-status">${statusBadge}</span>
                    ${refineBadge}
                    <div class="history-item-actions">
                        ${recallBtn}
                        <button class="btn btn-small" onclick="event.stopPropagation();renameSession('${s.id}','${escapeHtml(displayName).replace(/'/g, "\\'")}')" title="重命名">✏️</button>
                        <div class="export-dropdown" style="position:relative;display:inline-block;">
                            <button class="btn btn-small" onclick="event.stopPropagation();toggleExportMenu(this)">📥 导出 ▾</button>
                            <div class="export-menu" style="display:none;">
                                <div class="export-menu-item" onclick="event.stopPropagation();exportSession('${s.id}')">📝 Markdown</div>
                                <div class="export-menu-item" onclick="event.stopPropagation();exportSessionAudio('${s.id}')">🎵 音频 MP3</div>
                            </div>
                        </div>
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
    closeAllExportMenus();
    window.open(`/api/sessions/${sessionId}/export`, '_blank');
}

async function exportSessionAudio(sessionId) {
    closeAllExportMenus();
    window.open(`/api/sessions/${sessionId}/export/audio`, '_blank');
}

function toggleExportMenu(btn) {
    const menu = btn.nextElementSibling;
    const isOpen = menu.style.display !== 'none';
    closeAllExportMenus();
    if (!isOpen) menu.style.display = 'block';
}

function closeAllExportMenus() {
    document.querySelectorAll('.export-menu').forEach(m => m.style.display = 'none');
}

// 全局点击关闭导出菜单
document.addEventListener('click', () => closeAllExportMenus());

async function renameSession(sessionId, currentName) {
    const newName = prompt('请输入新名称：', currentName);
    if (newName === null || newName.trim() === '') return;
    try {
        const resp = await fetch(`/api/sessions/${sessionId}/rename`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: newName.trim() }),
        });
        if (!resp.ok) {
            const err = await resp.json();
            showToast(err.detail || '重命名失败', 'error');
            return;
        }
        showToast('已重命名', 'success');
        loadHistory();
    } catch (e) {
        showToast('重命名失败', 'error');
    }
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
        document.getElementById('settingAutoAnswerModel').value = data.auto_answer_model || 'qwen3.5-flash';

        // 更新自动回答模型选择器的选项
        const autoAnswerSelect = document.getElementById('settingAutoAnswerModel');
        const fastModel = data.llm_model_fast || 'qwen3.5-flash';
        const qualityModel = data.llm_model_quality || 'qwen3.5-plus';
        autoAnswerSelect.innerHTML = `
            <option value="${escapeHtml(fastModel)}">${escapeHtml(fastModel)}（快速）</option>
            <option value="${escapeHtml(qualityModel)}">${escapeHtml(qualityModel)}（高质量）</option>
        `;
        document.getElementById('settingAutoAnswerModel').value = data.auto_answer_model || fastModel;

        // OSS 设置
        document.getElementById('settingOssBucket').value = data.oss_bucket_name || '';
        document.getElementById('settingOssEndpoint').value = data.oss_endpoint || '';
        document.getElementById('settingOssPrefix').value = data.oss_upload_prefix || 'class_copilot';
        document.getElementById('settingOssExpiry').value = data.oss_url_expiry_seconds || 3600;

        // 更新 Chat 模型选择器显示实际模型名
        const chatModelSelect = document.getElementById('chatModel');
        chatModelSelect.innerHTML = `
            <option value="fast">${escapeHtml(data.llm_model_fast || 'qwen3.5-flash')}</option>
            <option value="quality">${escapeHtml(data.llm_model_quality || 'qwen3.5-plus')}</option>
        `;

        toggleRefinementSettings();

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

            // OSS 密钥状态
            const ossKeyId = keysData.oss_access_key_id;
            const ossKeySecret = keysData.oss_access_key_secret;
            document.getElementById('settingOssKeyId').placeholder = ossKeyId ? `✅ 已配置 (${ossKeyId}) — 留空保持不变` : '未配置';
            document.getElementById('settingOssKeySecret').placeholder = ossKeySecret ? `✅ 已配置 (${ossKeySecret}) — 留空保持不变` : '未配置';
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

        // 保存 OSS 密钥
        const ossKeyId = document.getElementById('settingOssKeyId').value;
        if (ossKeyId) {
            await fetch('/api/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: 'oss_access_key_id', value: ossKeyId, is_encrypted: true }),
            });
        }
        const ossKeySecret = document.getElementById('settingOssKeySecret').value;
        if (ossKeySecret) {
            await fetch('/api/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: 'oss_access_key_secret', value: ossKeySecret, is_encrypted: true }),
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
                auto_answer_model: document.getElementById('settingAutoAnswerModel').value,
                oss_bucket_name: document.getElementById('settingOssBucket').value,
                oss_endpoint: document.getElementById('settingOssEndpoint').value,
                oss_upload_prefix: document.getElementById('settingOssPrefix').value,
                oss_url_expiry_seconds: parseInt(document.getElementById('settingOssExpiry').value) || 3600,
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
        document.getElementById('settingOssKeyId').value = '';
        document.getElementById('settingOssKeySecret').value = '';

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
            const { seconds, label } = getAutoStopInfo(true);
            sendMessage('start_listening', { course_name: courseName, auto_stop_seconds: seconds, auto_stop_label: label });
            if (seconds > 0) {
                showToast(`已设置定时停止：${label}（${formatCountdown(seconds)}后）`, 'success');
            }
        }
    });

    // 新建录音按钮
    document.getElementById('btnNewRecording').addEventListener('click', () => {
        newRecording();
    });

    // 清除定时停止
    document.getElementById('btnClearAutoStop').addEventListener('click', () => {
        document.getElementById('autoStopTime').value = '';
        // 如果正在监听，通知后端取消定时
        if (state.isListening) {
            sendMessage('update_auto_stop', { seconds: 0 });
            showToast('已取消定时停止');
        }
    });

    // 定时停止时间变更 - 即时反馈 + 监听中可实时更新
    document.getElementById('autoStopTime').addEventListener('change', () => {
        const { seconds, label } = getAutoStopInfo(true);
        if (seconds > 0 && state.isListening) {
            // 监听中更改时间：实时更新后端定时器
            sendMessage('update_auto_stop', { seconds, label });
            showToast(`定时停止已更新为 ${label}（${formatCountdown(seconds)}后）`, 'success');
        } else if (seconds > 0) {
            showToast(`开始监听后将在 ${label} 自动停止（${formatCountdown(seconds)}后）`);
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


    // OSS 测试连接
    document.getElementById('btnTestOss').addEventListener('click', async () => {
        const resultEl = document.getElementById('ossTestResult');
        resultEl.textContent = '测试中...';
        resultEl.style.color = '#aaa';
        try {
            // 先保存当前填写的OSS配置
            const ossKeyId = document.getElementById('settingOssKeyId').value;
            const ossKeySecret = document.getElementById('settingOssKeySecret').value;
            if (ossKeyId) {
                await fetch('/api/settings', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key: 'oss_access_key_id', value: ossKeyId, is_encrypted: true }),
                });
            }
            if (ossKeySecret) {
                await fetch('/api/settings', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key: 'oss_access_key_secret', value: ossKeySecret, is_encrypted: true }),
                });
            }
            // 保存运行时 OSS 配置
            await fetch('/api/settings/runtime', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    oss_bucket_name: document.getElementById('settingOssBucket').value,
                    oss_endpoint: document.getElementById('settingOssEndpoint').value,
                    oss_upload_prefix: document.getElementById('settingOssPrefix').value,
                    oss_url_expiry_seconds: parseInt(document.getElementById('settingOssExpiry').value) || 3600,
                }),
            });
            const resp = await fetch('/api/oss/test', { method: 'POST' });
            if (resp.ok) {
                const data = await resp.json();
                resultEl.textContent = `✅ 连接成功！Bucket: ${data.info.bucket}, 区域: ${data.info.location}`;
                resultEl.style.color = '#4ade80';
            } else {
                const err = await resp.json();
                resultEl.textContent = `❌ ${err.detail || '连接失败'}`;
                resultEl.style.color = '#f87171';
            }
        } catch (e) {
            resultEl.textContent = `❌ 请求失败: ${e.message}`;
            resultEl.style.color = '#f87171';
        }
    });

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
