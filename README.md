# RECALL 🎙️🚀

**RECALL** is your AI teammate for hackathons. It listens to your voice conversations, transcribes them locally using Whisper, and uses Gemini AI to extract structured development briefs (features, decisions, next steps, and blockers) directly to your Telegram.

---

## ⚡ Quick Start

### 1. Get Your Tokens
*   **Telegram:** Message [@BotFather](https://t.me/botfather) to create a bot and get your **BOT_TOKEN**.
*   **Gemini:** Get a free API key from [Google AI Studio](https://aistudio.google.com/).
*   **Internal Security:** Generate a random string for your `API_TOKEN` (e.g., `my-super-secret-token`).

### 2. Configure Your Environment
Copy the example environment file and fill in your keys:
```bash
cp .env.example .env
# Edit .env with your favorite text editor
```

### 3. Launch with Docker (Recommended)
This starts the Bot, the API, the Database, and the AI Workers all at once:
```bash
docker-compose up --build
```
*Note: The first run will take a few minutes as it downloads the Whisper AI model (~74MB).*

---

## 🤖 Telegram Commands

*   **Send a Voice Message:** 🎧 Just record and send! The bot will reply with a structured brief.
*   **/challenge:** 🤔 Get Gemini to analyze your latest brief and ask probing questions about your plan.
*   **/history:** 📜 View a list of your 5 most recent project briefs with their IDs.
*   **/get {ID}:** 🔍 Retrieve the full details of a specific brief (e.g., `/get 1`).

---

## 🛠️ Manual Development

If you prefer to run things without Docker:

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the Components (In separate terminals)
*   **Redis:** `docker run -p 6379:6379 redis` (Required for the task queue)
*   **API:** `uvicorn api.main:app --reload`
*   **Worker:** `celery -A worker.celery_app worker --loglevel=info -P solo`
*   **Bot:** `python -m bot.main`

---

## 🏗️ Architecture
*   **Interface:** `python-telegram-bot`
*   **Backend:** `FastAPI` + `Celery` + `Redis`
*   **AI:** `OpenAI Whisper` (Local Transcription) & `Google Gemini 1.5 Flash` (Brief Extraction)
*   **Database:** `SQLite` + `SQLAlchemy`
