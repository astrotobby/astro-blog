(function() {
    // Configuration
    const CONFIG = {
        apiEndpoint: '/api/chat',
        primaryColor: '#4F46E5', // Indigo-600
        botName: 'Tobby\'s Assistant',
        welcomeMessage: 'Hi there! I\'m Tobby\'s Assistant. How can I help you navigate the blog today?',
        storageKey: 'chat_widget_history',
        maxRetries: 3,
        retryDelay: 1000 // ms
    };

    // Inject Styles
    const styles = `
        #chat-widget-container {
            position: fixed;
            bottom: 20px;
            left: 20px;
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
            box-shadow: 0 6px 16px rgba(0,0,0,0.2);
        }
        #chat-widget-window {
            position: absolute;
            bottom: 72px;
            left: 0;
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
            padding: 18px 20px;
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
            scrollbar-width: thin;
        }
        .chat-msg {
            max-width: 85%;
            padding: 10px 14px;
            border-radius: 14px;
            font-size: 14px;
            line-height: 1.5;
            word-wrap: break-word;
            animation: msgFadeIn 0.2s ease-out;
            white-space: pre-wrap;
            overflow-wrap: break-word;
        }
        @keyframes msgFadeIn {
            from { opacity: 0; transform: translateY(5px); }
            to { opacity: 1; transform: translateY(0); }
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
            align-self: flex-start;
            background-color: #fee2e2;
            color: #991b1b;
            border-bottom-left-radius: 2px;
            border-left: 3px solid #dc2626;
        }
        #chat-widget-input-container {
            padding: 16px;
            border-top: 1px solid #f3f4f6;
            display: flex;
            gap: 10px;
            background: white;
        }
        #chat-widget-input {
            flex: 1;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 10px 14px;
            outline: none;
            font-size: 14px;
            transition: border-color 0.2s;
            font-family: inherit;
        }
        #chat-widget-input:focus {
            border-color: ${CONFIG.primaryColor};
            box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
        }
        #chat-widget-send {
            background: ${CONFIG.primaryColor};
            color: white;
            border: none;
            border-radius: 10px;
            padding: 10px 16px;
            cursor: pointer;
            font-weight: 600;
            font-size: 14px;
            transition: opacity 0.2s;
            font-family: inherit;
        }
        #chat-widget-send:hover:not(:disabled) {
            opacity: 0.9;
        }
        #chat-widget-send:disabled {
            opacity: 0.5;
            cursor: not-allowed;
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
        @media (max-width: 480px) {
            #chat-widget-window {
                width: calc(100vw - 40px);
                height: calc(100vh - 100px);
                max-height: 600px;
            }
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
                <button id="chat-widget-close" style="background:none;border:none;color:white;cursor:pointer;font-size:24px;line-height:1;padding:0;width:24px;height:24px;display:flex;align-items:center;justify-content:center;">&times;</button>
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
        typingDiv.innerHTML = `
            <div class="typing-indicator">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        `;
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
                // Normalize role for display
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
                const errorText = await response.text().catch(() => 'Unknown error');
                let errorMsg = 'Error: Unable to get response';
                
                try {
                    const errorData = JSON.parse(errorText);
                    errorMsg = `Error: ${errorData.error || errorText}`;
                } catch {
                    errorMsg = `Error: ${response.status} - ${errorText || 'Server error'}`;
                }
                
                appendMessage('error', errorMsg);
                console.error('Chat API Error:', errorMsg);
                isLoading = false;
                sendBtn.disabled = false;
                inputEl.focus();
                return;
            }

            // Read response as text
            const botResponse = await response.text();

            if (!botResponse) {
                appendMessage('error', 'Error: Empty response from server');
                isLoading = false;
                sendBtn.disabled = false;
                inputEl.focus();
                return;
            }

            // Display bot response
            appendMessage('assistant', botResponse);

            // Save to history
            history.push({ role: 'assistant', content: botResponse });
            saveHistory();

        } catch (err) {
            typingIndicator.remove();
            const errorMsg = `Error: ${err.message || 'Network error'}`;
            appendMessage('error', errorMsg);
            console.error('Chat Widget Error:', err);
        } finally {
            isLoading = false;
            sendBtn.disabled = false;
            inputEl.focus();
        }
    }

    sendBtn.onclick = handleSend;
    inputEl.onkeypress = (e) => { if (e.key === 'Enter' && !isLoading) handleSend(); };

})();
