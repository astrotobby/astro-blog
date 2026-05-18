# Chatbot Setup & Deployment Guide

## Overview

This Astro blog includes an AI-powered chatbot widget that uses Anthropic's Claude API to provide intelligent responses to visitor questions.

## Features

- **Real-time Chat Widget**: Fixed position chat bubble in the bottom-left corner
- **Message History**: Persistent chat history stored in browser localStorage
- **Streaming Responses**: Smooth, real-time message display
- **Error Handling**: Graceful error messages and retry logic
- **Responsive Design**: Works on desktop and mobile devices
- **Accessible**: WCAG 2.1 AA compliant

## Architecture

### Frontend
- **File**: `/public/js/chat-widget.js`
- **Features**:
  - Self-contained widget (no external dependencies)
  - Local message history persistence
  - Automatic typing indicators
  - Error state handling
  - Mobile-responsive UI

### Backend
- **File**: `/src/pages/api/chat.ts`
- **Features**:
  - Cloudflare Workers integration
  - Message history validation and cleaning
  - Anthropic Claude API integration
  - Proper error handling and logging
  - Support for streaming responses

## Setup Instructions

### 1. Get an Anthropic API Key

1. Visit [https://console.anthropic.com/](https://console.anthropic.com/)
2. Sign up or log in to your account
3. Navigate to the API keys section
4. Create a new API key
5. Copy the key (you'll need it for deployment)

### 2. Local Development

```bash
# Install dependencies
npm install

# Set up environment
cp .env.example .env.local

# Edit .env.local and add your Anthropic API key
# ANTHROPIC_API_KEY=sk-ant-...

# Start development server
npm run dev
```

The chatbot will be available at `http://localhost:3000` and the API endpoint at `http://localhost:3000/api/chat`.

### 3. Cloudflare Deployment

#### Option A: Using Wrangler CLI

```bash
# Build the project
npm run build

# Deploy to Cloudflare
npm run deploy
```

#### Option B: Using Cloudflare Dashboard

1. Go to [https://dash.cloudflare.com/](https://dash.cloudflare.com/)
2. Select your account and navigate to Workers & Pages
3. Create a new Worker or use existing one
4. Upload the built files from the `dist` directory
5. Set environment secrets in the Worker settings:
   - Go to Settings > Environment Variables
   - Add `ANTHROPIC_API_KEY` with your API key value

### 4. Setting Environment Variables on Cloudflare

**Via Wrangler CLI:**
```bash
wrangler secret put ANTHROPIC_API_KEY
# Paste your API key when prompted
```

**Via Cloudflare Dashboard:**
1. Go to Workers & Pages > Your Worker
2. Click Settings > Environment Variables
3. Add a new secret:
   - Name: `ANTHROPIC_API_KEY`
   - Value: Your Anthropic API key
4. Save

## Configuration

### Widget Customization

Edit the `CONFIG` object in `/public/js/chat-widget.js`:

```javascript
const CONFIG = {
    apiEndpoint: '/api/chat',           // API endpoint
    primaryColor: '#4F46E5',             // Widget color (Indigo-600)
    botName: 'Tobby\'s Assistant',       // Bot display name
    welcomeMessage: 'Hi there! ...',     // Initial greeting
    storageKey: 'chat_widget_history',   // localStorage key
    maxRetries: 3,                       // API retry attempts
    retryDelay: 1000                     // Delay between retries (ms)
};
```

### System Prompt Customization

Edit the system prompt in `/src/pages/api/chat.ts`:

```typescript
system: "You are Tobby's Assistant, a helpful AI on the AstroSignal blog. Help visitors with questions about AI, technology, and the blog content. Be concise, friendly, and informative.",
```

## Troubleshooting

### Chatbot Not Responding

1. **Check API Key**: Verify that `ANTHROPIC_API_KEY` is set correctly on Cloudflare
2. **Check Network**: Open browser DevTools (F12) > Network tab > look for `/api/chat` requests
3. **Check Logs**: View Cloudflare Worker logs in the dashboard
4. **Check Browser Console**: Look for JavaScript errors in the console

### "ANTHROPIC_API_KEY not configured" Error

- Ensure the environment variable is set on Cloudflare Workers
- Use `wrangler secret put ANTHROPIC_API_KEY` to set it
- Wait a few minutes for the change to propagate

### Messages Not Saving

- Check browser localStorage is enabled
- Clear localStorage if corrupted: `localStorage.clear()`
- Check browser console for errors

### Slow Responses

- Anthropic API may be rate-limited
- Check your API quota at [https://console.anthropic.com/](https://console.anthropic.com/)
- Consider upgrading your Anthropic plan for higher rate limits

## API Endpoint Reference

### POST `/api/chat`

**Request:**
```json
{
  "messages": [
    { "role": "user", "content": "Hello!" },
    { "role": "assistant", "content": "Hi there!" },
    { "role": "user", "content": "How are you?" }
  ]
}
```

**Response:**
```
Plain text response from Claude
```

**Error Response:**
```json
{
  "error": "Error message describing what went wrong"
}
```

## Performance Optimization

- Widget is lazy-loaded after page content
- Messages are cached in browser localStorage
- API responses are streamed for better UX
- Typing indicators provide visual feedback during processing

## Security Considerations

- API key is stored securely on Cloudflare Workers (not exposed to frontend)
- All API requests are validated server-side
- Message history is stored only in browser localStorage
- CORS is properly configured for the API endpoint

## Monitoring & Analytics

Monitor chatbot usage through:
1. **Cloudflare Dashboard**: View request logs and metrics
2. **Browser Console**: Check for errors during development
3. **Anthropic Dashboard**: Monitor API usage and costs

## Support & Resources

- [Anthropic API Documentation](https://docs.anthropic.com/)
- [Cloudflare Workers Documentation](https://developers.cloudflare.com/workers/)
- [Astro Documentation](https://docs.astro.build/)

## License

This chatbot implementation is part of the AstroSignal blog project.
