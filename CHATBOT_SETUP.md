# Chatbot Setup & Deployment Guide

## Overview

This Astro blog includes an AI-powered chatbot widget that uses Cloudflare Workers AI to provide intelligent responses to visitor questions.

## Features

- **Real-time Chat Widget**: Fixed position chat bubble in the bottom-left corner
- **Message History**: Persistent chat history stored in browser localStorage
- **Streaming Responses**: Smooth, real-time message display using Server-Sent Events (SSE)
- **Cloudflare Native**: Leverages Cloudflare Workers AI for high-performance, low-latency inference

## Architecture

### Frontend
- **File**: `/public/js/chat-widget.js`
- **Features**:
  - Self-contained widget (no external dependencies)
  - Local message history persistence
  - Automatic typing indicators
  - Streaming response handling (SSE)
  - Mobile-responsive UI

### Backend
- **File**: `/src/pages/api/chat.ts`
- **Features**:
  - Cloudflare Workers integration
  - Uses `@cf/meta/llama-3.1-8b-instruct` model
  - Supports streaming responses directly from Cloudflare AI
  - Proper error handling and logging

## Setup Instructions

### 1. Cloudflare Account
Ensure you have a Cloudflare account with Workers AI enabled.

### 2. Local Development
To run the project locally with Cloudflare features, you need to use Wrangler.

```bash
# Install dependencies
npm install

# Start development server with remote connection for AI
npm run dev
```

### 3. Cloudflare Deployment

#### Using Wrangler CLI
The project is configured to deploy to Cloudflare Pages/Workers.

```bash
# Build and deploy
npm run deploy
```

#### Configuration
Ensure your `wrangler.jsonc` or Cloudflare Dashboard has the `AI` binding configured:

```json
"ai": {
  "binding": "AI"
}
```

## Configuration

### Widget Customization
Edit the `CONFIG` object in `/public/js/chat-widget.js`.

### System Prompt Customization
Edit the system prompt in `/src/pages/api/chat.ts`.

## Troubleshooting

### Chatbot Not Responding
1. **Check AI Binding**: Verify that the `AI` binding is correctly set in your Cloudflare settings.
2. **Check Logs**: View Cloudflare Worker logs in the dashboard.
3. **Check Browser Console**: Look for JavaScript errors in the console.

### Slow Responses
- Cloudflare Workers AI latency depends on the model and region. Llama 3.1 8B is generally fast.

## API Endpoint Reference

### POST `/api/chat`
**Request:**
```json
{
  "messages": [
    { "role": "user", "content": "Hello!" }
  ]
}
```

**Response:**
A stream of Server-Sent Events (SSE) containing the AI's response.

## License
This chatbot implementation is part of the AstroSignal blog project.
