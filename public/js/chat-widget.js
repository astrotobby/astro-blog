(function() {
    // Configuration
    const CONFIG = {
        apiEndpoint: '/api/chat',
        primaryColor: '#10B981',
        botName: 'Tobby\'s Assistant',
        welcomeMessage: 'Hi there! I\'m Tobby\'s Assistant.! How can I help you today?',
        storageKey: 'chat_widget_history'
    };

    // Inject Styles
    const styles = `
        #chat-widget-container {
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 9999;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }
        #chat-widget-bubble {
            width: 56px;
            height: 56px;
            background-color: ${CONFIG.primaryColor};
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        }
        #chat-widget-bubble:hover {
            transform: scale(1.05);
        }
        #chat-widget-window {
            position: absolute;
            bottom: 72px;
            right: 0;
            width: 360px;
            height: 520px;
            background: white;
            border-radius: 16px;
            box-shadow: 0 12px 32px rgba(0,0,0,0.15);
            display: none;
            flex-direction: column;
            overflow: hidden;
            animation: chatSlideIn 0.3s ease-out;
            border: 1px solid rgba(0,0,0,0.05);
        }
        @keyframes chatSlideIn {
            from { opacity: 0; transform: translateY(20px) scale(0.95); }
            to { opacity: 1; transform: translateY(0) scale(1); }
        }
        #chat-widget-header {
            background-color: ${CONFIG.primaryColor};
            color: white;
            padding: 14px 20px;
            font-weight: 700;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 16px;
        }
        #chat-widget-messages {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 14px;
            background: #ffffff;
        }
        .chat-msg {
            max-width: 85%;
            padding: 10px 14px;
            border-radius: 14px;
            font-size: 14px;
            line-height: 1.5;
            word-wrap: break-word;
            white-space: pre-wrap;
        }
        .chat-msg.user {
            align-self: flex-end;
            background-color: ${CONFIG.primaryColor};
            color: white;
            border-bottom-right-radius: 2px;
        }
        .chat-msg.assistant {
            align-self: flex-start;
            background-color: #f3f4f6;
            color: #1f2937;
            border-bottom-left-radius: 2px;
        }
        .chat-msg.error {
            align-self: center;
            background-color: #fee2e2;
            color: #991b1b;
            font-size: 12px;
            border-radius: 8px;
            width: 90%;
            text-align: center;
            border: 1px solid #fecaca;
            padding: 8px;
        }
        #chat-widget-input-container {
            padding: 16px;
            border-top: 1px solid #f3f4f6;
            display: flex;
            gap: 10px;
        }
        #chat-widget-input {
            flex: 1;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 10px 14px;
            outline: none;
            font-size: 14px;
        }
        #chat-widget-send {
            background: ${CONFIG.primaryColor};
            color: white;
            border: none;
            border-radius: 10px;
            padding: 10px 16px;
            cursor: pointer;
            font-weight: 600;
        }
        .typing-indicator {
            display: flex;
            gap: 4px;
            padding: 4px 0;
        }
        .typing-dot {
            width: 6px;
            height: 6px;
            background: #9ca3af;
            border-radius: 50%;
            animation: typingBounce 1.4s infinite ease-in-out both;
        }
        .typing-dot:nth-child(1) { animation-delay: -0.32s; }
        .typing-dot:nth-child(2) { animation-delay: -0.16s; }
        @keyframes typingBounce {
            0%, 80%, 100% { transform: scale(0); }
            40% { transform: scale(1.0); }
        }
        .header-actions {
            display: flex;
            gap: 12px;
            align-items: center;
        }
        .action-btn {
            background: none;
            border: none;
            color: white;
            cursor: pointer;
            opacity: 0.8;
            transition: opacity 0.2s;
            padding: 4px;
            display: flex;
            align-items: center;
        }
        .action-btn:hover {
            opacity: 1;
        }
    `;

    const styleSheet = document.createElement("style");
    styleSheet.innerText = styles;
    document.head.appendChild(styleSheet);

    // Create DOM Elements
    const container = document.createElement('div');
    container.id = 'chat-widget-container';
    container.innerHTML = `
        <div id="chat-widget-window">
            <div id="chat-widget-header">
                <span>${CONFIG.botName}</span>
                <div class="header-actions">
                    <button id="chat-widget-clear" class="action-btn" title="Clear Chat">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg>
                    </button>
                    <button id="chat-widget-close" class="action-btn" title="Close">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                    </button>
                </div>
            </div>
            <div id="chat-widget-messages"></div>
            <div id="chat-widget-input-container">
                <input type="text" id="chat-widget-input" placeholder="Ask me anything..." autocomplete="off">
                <button id="chat-widget-send">Send</button>
            </div>
        </div>
        <div id="chat-widget-bubble">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
            </svg>
        </div>
    `;
    document.body.appendChild(container);

    // Logic
    const bubble = document.getElementById('chat-widget-bubble');
    const windowEl = document.getElementById('chat-widget-window');
    const closeBtn = document.getElementById('chat-widget-close');
    const clearBtn = document.getElementById('chat-widget-clear');
    const messagesEl = document.getElementById('chat-widget-messages');
    const inputEl = document.getElementById('chat-widget-input');
    const sendBtn = document.getElementById('chat-widget-send');

    let history = JSON.parse(localStorage.getItem(CONFIG.storageKey) || '[]');
    let isLoading = false;

    function saveHistory() {
        localStorage.setItem(CONFIG.storageKey, JSON.stringify(history));
    }

    function appendMessage(role, text) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `chat-msg ${role}`;
        msgDiv.textContent = text;
        messagesEl.appendChild(msgDiv);
        messagesEl.scrollTop = messagesEl.scrollHeight;
        return msgDiv;
    }

    function showTyping() {
        const typingDiv = document.createElement('div');
        typingDiv.className = 'chat-msg assistant';
        typingDiv.innerHTML = `<div class="typing-indicator"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div>`;
        messagesEl.appendChild(typingDiv);
        messagesEl.scrollTop = messagesEl.scrollHeight;
        return typingDiv;
    }

    function loadHistory() {
        messagesEl.innerHTML = '';
        if (history.length === 0) {
            appendMessage('assistant', CONFIG.welcomeMessage);
        } else {
            history.forEach(msg => {
                const displayRole = msg.role === 'bot' ? 'assistant' : msg.role;
                appendMessage(displayRole, msg.content);
            });
        }
    }

    bubble.onclick = () => {
        const isOpen = windowEl.style.display === 'flex';
        windowEl.style.display = isOpen ? 'none' : 'flex';
        if (!isOpen) {
            loadHistory();
            inputEl.focus();
        }
    };

    closeBtn.onclick = () => windowEl.style.display = 'none';

    clearBtn.onclick = () => {
        if (confirm('Clear chat history?')) {
            history = [];
            saveHistory();
            loadHistory();
        }
    };

    async function handleSend() {
        const text = inputEl.value.trim();
        if (!text || isLoading) return;

        inputEl.value = '';
        appendMessage('user', text);
        history.push({ role: 'user', content: text });
        saveHistory();

        isLoading = true;
        sendBtn.disabled = true;
        const typingIndicator = showTyping();

        try {
            const response = await fetch(CONFIG.apiEndpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ messages: history })
            });

            typingIndicator.remove();

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ error: 'Unknown error' }));
                appendMessage('error', errorData.error || `Error ${response.status}`);
                return;
            }

            // Create a message div for the streaming response
            const botMsgDiv = appendMessage('assistant', '');
            let fullResponse = '';

            const reader = response.body.getReader();
            const decoder = new TextDecoder();

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value, { stream: true });
                
                // Cloudflare Workers AI returns data in SSE format: data: {"response": "..."}
                const lines = chunk.split('\n');
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const dataStr = line.slice(6);
                        if (dataStr === '[DONE]') continue;
                        try {
                            const data = JSON.parse(dataStr);
                            if (data.response) {
                                fullResponse += data.response;
                                botMsgDiv.textContent = fullResponse;
                                messagesEl.scrollTop = messagesEl.scrollHeight;
                            }
                        } catch (e) {
                            // If not JSON, it might be raw text (depending on provider)
                            fullResponse += dataStr;
                            botMsgDiv.textContent = fullResponse;
                            messagesEl.scrollTop = messagesEl.scrollHeight;
                        }
                    }
                }
            }

            history.push({ role: 'assistant', content: fullResponse });
            saveHistory();

        } catch (err) {
            if (typingIndicator) typingIndicator.remove();
            appendMessage('error', 'Network error. Please check your connection.');
            console.error('Streaming Error:', err);
        } finally {
            isLoading = false;
            sendBtn.disabled = false;
            inputEl.focus();
        }
    }

    sendBtn.onclick = handleSend;
    inputEl.onkeypress = (e) => { if (e.key === 'Enter') handleSend(); };

})();
