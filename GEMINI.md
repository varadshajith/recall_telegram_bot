# GEMINI.md

## Project Status
**Fully Implemented.** The project has been built from the ground up, including the API, the Telegram Bot, and the background Workers for AI processing.

## Key Files
...
- **`Dockerfile` & `docker-compose.yml`**: Full orchestration for the entire system (Bot, API, Workers, Redis, DB).
- **`README.md`**: The end-user manual for setup and commands.

## Usage
The system is ready to be launched using Docker.

### Running RECALL
1.  **Tokens:** Obtain your `TELEGRAM_BOT_TOKEN` and `GEMINI_API_KEY`.
2.  **Environment:** Create a `.env` file from `.env.example`.
3.  **Start:** Run `docker-compose up --build` to start all services simultaneously.

### Technical Stack
...
- **AI Analysis:** Google Gemini 1.5 Flash API (Free Tier)
...
