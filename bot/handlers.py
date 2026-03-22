import os
import httpx
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from shared.config import settings

# API URL - uses env var (set by docker-compose) or defaults to localhost
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000/api/v1")


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice messages"""
    # 1. Download the voice file from Telegram's servers
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)

    await update.message.reply_text("🎧 Transcribing your voice message...")

    # 2. Send the file path to our FastAPI server
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{API_BASE_URL}/transcribe",
                headers={"Authorization": f"Bearer {settings.api_token}"},
                json={
                    "audio_url": file.file_path,
                    "session_id": str(update.effective_chat.id)
                },
                timeout=30.0
            )

            if response.status_code != 200:
                await update.message.reply_text("❌ Failed to start transcription. Please try again.")
                return

            job_id = response.json()["job_id"]

            # 3. Poll (keep asking) the server if the job is done
            for _ in range(30):  # Wait up to 30 seconds
                await asyncio.sleep(1)

                result_response = await client.get(
                    f"{API_BASE_URL}/jobs/{job_id}",
                    headers={"Authorization": f"Bearer {settings.api_token}"},
                    timeout=10.0
                )

                if result_response.status_code != 200:
                    continue

                result = result_response.json()

                if result["status"] == "completed":
                    # 4. Success! Format and send the brief
                    msg = format_prompt(result)
                    await update.message.reply_text(msg, parse_mode="Markdown")
                    return
                elif result["status"] == "failed":
                    await update.message.reply_text(f"❌ Transcription failed: {result.get('error', 'Unknown error')}")
                    return

            await update.message.reply_text("⏱️ This is taking a while! Use /history in a moment to check if it's finished.")
        
        except Exception as e:
            await update.message.reply_text(f"❌ Connection error: Could not reach the API server.")


def format_prompt(result: dict) -> str:
    """Format the AI result into a beautiful Telegram message using Markdown"""
    lines = []

    # Get the "Building" one-liner
    if result.get("raw_summary"):
        lines.append(f"*{result['raw_summary'].split(chr(10))[0]}*")
        lines.append("")

    # Features list
    if result.get("features"):
        lines.append("*Features:*")
        for f in result["features"]:
            lines.append(f"• {f}")
        lines.append("")

    # Decisions list
    if result.get("decisions"):
        lines.append("*Decisions:*")
        for d in result["decisions"]:
            lines.append(f"• {d}")
        lines.append("")

    # Next steps list with checkboxes
    if result.get("next_steps"):
        lines.append("*Next Steps:*")
        for s in result["next_steps"]:
            lines.append(f"☐ {s}")
        lines.append("")

    # Blockers with warning icons
    if result.get("blockers"):
        lines.append("*Blockers:*")
        for b in result["blockers"]:
            lines.append(f"⚠️ {b}")
        lines.append("")

    # Add the extra context at the bottom in italics
    if result.get("raw_summary") and "\n" in result["raw_summary"]:
        parts = result["raw_summary"].split("Context: ")
        if len(parts) > 1:
            lines.append(f"_{parts[1].strip()}_")

    return "\n".join(lines)


async def challenge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /challenge command - generate questions for the last prompt"""
    chat_id = str(update.effective_chat.id)

    async with httpx.AsyncClient() as client:
        # 1. First, find the latest prompt ID from your history
        history_response = await client.get(
            f"{API_BASE_URL}/history",
            headers={"Authorization": f"Bearer {settings.api_token}"},
            params={"session_id": chat_id, "limit": 1},
            timeout=10.0
        )

        if history_response.status_code != 200:
            await update.message.reply_text("❌ Could not fetch your history.")
            return

        history = history_response.json()
        if not history.get("prompts"):
            await update.message.reply_text("No project briefs found! Send a voice message first.")
            return

        latest_prompt = history["prompts"][0]
        prompt_id = latest_prompt["id"]

        await update.message.reply_text("🤔 Analyzing your brief and generating challenges...")

        # 2. Call the challenge API for that specific prompt
        response = await client.post(
            f"{API_BASE_URL}/challenge",
            headers={"Authorization": f"Bearer {settings.api_token}"},
            json={"prompt_id": prompt_id},
            timeout=30.0
        )

        if response.status_code != 200:
            await update.message.reply_text("❌ Failed to generate challenges.")
            return

        challenges = response.json()["challenges"]

        # 3. Format and send the response
        lines = ["*Project Challenges:*", ""]
        for i, c in enumerate(challenges, 1):
            lines.append(f"{i}. {c}")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /history command - show recent project briefs"""
    chat_id = str(update.effective_chat.id)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{API_BASE_URL}/history",
            headers={"Authorization": f"Bearer {settings.api_token}"},
            params={"session_id": chat_id, "limit": 5},
            timeout=10.0
        )

        if response.status_code != 200:
            await update.message.reply_text("❌ Could not fetch history.")
            return

        prompts = response.json().get("prompts", [])

        if not prompts:
            await update.message.reply_text("No project briefs yet. Send me a voice message!")
            return

        lines = ["*Your Recent Project Briefs:*", ""]
        for p in prompts:
            # Extract the first line of the summary (the 'Building' line)
            summary = p.get("raw_summary", "").split("\n")[0] if p.get("raw_summary") else "Untitled"
            lines.append(f"`ID: {p['id']}` — {summary[:50]}...")

        lines.append("")
        lines.append("Use `/get ID` to see the full brief (e.g., `/get 1`)")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /get command - retrieve a specific brief by its ID"""
    if not context.args:
        await update.message.reply_text("Usage: `/get ID` (example: `/get 1`)")
        return

    try:
        prompt_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid ID. Please use a number (example: `/get 1`)")
        return

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{API_BASE_URL}/prompts/{prompt_id}",
            headers={"Authorization": f"Bearer {settings.api_token}"},
            timeout=10.0
        )

        if response.status_code == 404:
            await update.message.reply_text("Brief not found.")
            return
        elif response.status_code != 200:
            await update.message.reply_text("❌ Failed to fetch the brief.")
            return

        prompt = response.json()
        msg = format_prompt(prompt)
        await update.message.reply_text(msg, parse_mode="Markdown")
