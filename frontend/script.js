document.addEventListener('DOMContentLoaded', () => {
    const chatMessages = document.getElementById('chat-messages');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');
    // Asegúrate de que esta URL sea correcta para tu backend Flask
    const BACKEND_URL = 'http://127.0.0.1:5000/chat';

    // Rutas para el logo municipal y el avatar del bot
    const municipalLogoSrc = 'assets/logo.jpg'; // Ruta actualizada para el logo municipal
    const botAvatarSrc = 'assets/botmuni.png';    // Ruta actualizada para el avatar del bot

    let isBotResponding = false; // Estado para evitar el envío de mensajes duplicados

    // Configurar el logo en el header
    const headerLogo = document.querySelector('.chat-header .header-logo'); 
    if (headerLogo) {
        headerLogo.src = municipalLogoSrc;
    }

    // Función para renderizar Markdown a HTML
    function renderMarkdown(markdownText) {
        let html = markdownText;

        // Reemplazar negritas (doble asterisco)
        html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        // Reemplazar cursivas (asterisco simple)
        html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
        
        // Formato para listas a), b), c) - Pone en negrita los prefijos 'a)', 'b)', etc.
        html = html.replace(/(\n|^)([a-z]\))\s*/g, '$1<strong>$2</strong> ');

        // Reemplazar saltos de línea por <br> (excepto dentro de listas o después de encabezados)
        html = html.replace(/(?<!\n)\n(?![\-\*\#])/g, '<br>');

        // Convertir encabezados (H1-H6)
        for (let i = 6; i >= 1; i--) {
            const regex = new RegExp(`^#{${i}}\\s*(.*)$`, 'gm');
            html = html.replace(regex, `<h${i}>$1</h${i}>`);
        }

        // Convertir listas (guiones o asteriscos al inicio de línea)
        const listRegex = /^\s*([-\*])\s*(.*)$/gm;
        let listItems = [];
        let tempHtml = html; 

        tempHtml = tempHtml.replace(listRegex, (match, p1, p2, offset, originalString) => {
            const prevLineBreak = originalString.lastIndexOf('\n', offset - 1);
            const prevLine = prevLineBreak !== -1 ? originalString.substring(prevLineBreak + 1, offset).trim() : '';
            
            listItems.push(`<li>${p2}</li>`);
            return '<!--LIST_ITEM_PLACEHOLDER-->'; 
        });

        html = tempHtml.replace(/(<!--LIST_ITEM_PLACEHOLDER-->)+/g, (match) => {
            const count = (match.match(/<!--LIST_ITEM_PLACEHOLDER-->/g) || []).length;
            const items = listItems.splice(0, count); 
            return `<ul>${items.join('')}</ul>`;
        });

        return html;
    }

    function addMessage(sender, messageContent, type = 'text', suggestions = []) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', sender);

        const avatarDiv = document.createElement('div');
        avatarDiv.classList.add('message-avatar');

        if (sender === 'bot') {
            const botImg = document.createElement('img');
            botImg.src = botAvatarSrc;
            botImg.alt = 'Bot Avatar';
            avatarDiv.appendChild(botImg);
        } else {
            avatarDiv.textContent = 'Yo'; 
            avatarDiv.style.backgroundColor = '#3182ce'; /* Fondo para el avatar de "Yo" (azul) */
        }
        messageDiv.appendChild(avatarDiv); 

        const bubbleDiv = document.createElement('div');
        bubbleDiv.classList.add('message-bubble');
        
        if (type === 'typing_indicator') {
            bubbleDiv.innerHTML = `<div class="loading-dots"><span></span><span></span><span></span></div>`;
            bubbleDiv.classList.add('typing-bubble');
            messageDiv.id = 'loading-indicator'; 
        } else {
            const contentHtml = renderMarkdown(messageContent);
            
            const fragment = document.createDocumentFragment();
            
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = contentHtml;
            while(tempDiv.firstChild) {
                fragment.appendChild(tempDiv.firstChild);
            }

            if (type === 'suggestions' && suggestions.length > 0) {
                const suggestionsContainer = document.createElement('div');
                suggestionsContainer.classList.add('suggestions-container');
                suggestions.forEach(suggestion => {
                    const button = document.createElement('button');
                    button.classList.add('suggestion-button');
                    button.textContent = suggestion;
                    button.onclick = () => {
                        sendMessage(suggestion); 
                    };
                    suggestionsContainer.appendChild(button);
                });
                fragment.appendChild(suggestionsContainer); 
            }
            bubbleDiv.appendChild(fragment); 
        }

        messageDiv.appendChild(bubbleDiv);

        if (type !== 'typing_indicator') {
            const timeSpan = document.createElement('span');
            timeSpan.classList.add('message-time');
            const now = new Date();
            timeSpan.textContent = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
            bubbleDiv.appendChild(timeSpan);
        }
        
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight; 

        // Aplicar el efecto de tipeo solo si el mensaje es del bot y es de tipo 'text' (no 'suggestions' ni 'typing_indicator')
        if (sender === 'bot' && type === 'text') {
            typeMessage(bubbleDiv, messageContent, bubbleDiv.querySelector('.message-time'));
        }
    }

    function showLoadingIndicator() {
        addMessage('bot', '', 'typing_indicator');
    }

    function hideLoadingIndicator() {
        const loadingDiv = document.getElementById('loading-indicator');
        if (loadingDiv) {
            loadingDiv.remove();
        }
    }

    function typeMessage(element, text, timeSpanElement) {
        let i = 0;
        const originalContent = text; 
        element.innerHTML = ''; 

        const typedContentSpan = document.createElement('span');
        element.appendChild(typedContentSpan);

        const typingInterval = setInterval(() => {
            if (i < originalContent.length) {
                let char = originalContent.charAt(i);
                // Intenta procesar fragmentos de Markdown (negritas, cursivas, encabezados, a), b))
                if (char === '*' || char === '#' || (char.match(/[a-z]/) && originalContent.substring(i).match(/^[a-z]\)\s*/))) { 
                    let tempFullContent = originalContent.substring(i);
                    let match = null;
                    if (char === '*') {
                        match = tempFullContent.match(/^\*\*([^\*]+)\*\*|^\*([^\*]+)\*/);
                    } else if (char === '#') {
                        match = tempFullContent.match(/^(\#{1,6}\s*[^\n]+)/);
                    } else if (char.match(/[a-z]/) && tempFullContent.match(/^[a-z]\)\s*/)) { 
                        match = tempFullContent.match(/^([a-z]\))\s*/);
                    }

                    if (match && match[0]) {
                        const formattedChunk = renderMarkdown(match[0]); 
                        typedContentSpan.innerHTML += formattedChunk;
                        i += match[0].length; 
                        chatMessages.scrollTop = chatMessages.scrollHeight;
                        return; 
                    }
                }
                
                // Si no es un formato especial, añadir el carácter normalmente
                typedContentSpan.innerHTML += char;
                i++;
                chatMessages.scrollTop = chatMessages.scrollHeight; 
            } else {
                clearInterval(typingInterval);
                typedContentSpan.innerHTML = renderMarkdown(originalContent);
                if (timeSpanElement) {
                    element.appendChild(timeSpanElement);
                }
                isBotResponding = false;
                userInput.disabled = false;
                sendButton.disabled = false;
                userInput.focus();
            }
        }, 4); 
    }

    async function sendMessage(messageFromButton = null) {
        const message = messageFromButton || userInput.value.trim();
        if (message === '') return;

        addMessage('user', message);
        userInput.value = ''; 
        
        userInput.disabled = true;
        sendButton.disabled = true;
        isBotResponding = true;

        showLoadingIndicator(); 

        try {
            const response = await fetch(BACKEND_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ message: message }),
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            hideLoadingIndicator(); 

            if (data.response_type === 'suggestions') {
                addMessage('bot', data.message, 'suggestions', data.suggestions);
            } else {
                addMessage('bot', data.response, 'text'); 
            }
        } catch (error) {
            console.error('Error al enviar mensaje al backend:', error);
            hideLoadingIndicator();
            addMessage('bot', 'Lo siento, no pude comunicarme con el asistente en este momento. Inténtalo de nuevo más tarde. 😔');
        } finally {
            isBotResponding = false;
            userInput.disabled = false;
            sendButton.disabled = false;
            userInput.focus(); 
        }
    }

    sendButton.addEventListener('click', () => {
        if (!isBotResponding) { 
            sendMessage();
        }
    });
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !isBotResponding) { 
            sendMessage();
        }
    });

    window.onload = () => {
        addMessage('bot', '¡Hola! Soy tu **Asistente Municipal de Puno**. Estoy aquí para ayudarte con información sobre los **procedimientos TUPA**. ¿En qué puedo ayudarte hoy?');
    };
});
