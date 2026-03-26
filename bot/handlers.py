import os
import httpx
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from shared.config import settings

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000/api/v1")
_AUTH = lambda: {"Authorization": f"Bearer {settings.api_token}"}

# ConversationHandler state for /prompt
PROMPT_AWAITING_ANSWER = 1


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _chat_id(update: Update) -> str:
    return str(update.effective_chat.id)


def _username(update: Update) -> str:
    u = update.effective_user
    return (u.username or u.first_name or "") if u else ""


def format_prompt(result: dict) -> str:
    """Format a brief dict into Markdown for Telegram."""
    lines = []
    if result.get("raw_summary"):
        lines.append(f"*{result['raw_summary'].split(chr(10))[0]}*")
        lines.append("")
    if result.get("tags"):
        lines.append("🏷 " + "  ".join(f"`{t}`" for t in result["tags"]))
        lines.append("")
    if result.get("features"):
        lines.append("*Features:*")
        lines.extend(f"• {f}" for f in result["features"])
        lines.append("")
    if result.get("decisions"):
        lines.append("*Decisions:*")
        lines.extend(f"• {d}" for d in result["decisions"])
        lines.append("")
    if result.get("next_steps"):
        lines.append("*Next Steps:*")
        lines.extend(f"☐ {s}" for s in result["next_steps"])
        lines.append("")
    if result.get("blockers"):
        lines.append("*Blockers:*")
        lines.extend(f"⚠️ {b}" for b in result["blockers"])
        lines.append("")
    if result.get("raw_summary") and "Context: " in result["raw_summary"]:
        ctx = result["raw_summary"].split("Context: ", 1)[1].strip()
        lines.append(f"_{ctx}_")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Voice handler (unchanged flow, now passes telegram_username)
# ---------------------------------------------------------------------------

async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Transcribe voice message and return structured brief."""
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    await update.message.reply_text("🎧 Transcribing your voice message...")

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{API_BASE_URL}/transcribe",
                headers=_AUTH(),
                json={
                    "audio_url": file.file_path,
                    "session_id": _chat_id(update),
                    "telegram_username": _username(update),
                },
                timeout=30.0,
            )
            if resp.status_code != 200:
                await update.message.reply_text("❌ Failed to start transcription.")
                return

            job_id = resp.json()["job_id"]
            for _ in range(30):
                await asyncio.sleep(1)
                poll = await client.get(
                    f"{API_BASE_URL}/jobs/{job_id}",
                    headers=_AUTH(),
                    timeout=10.0,
                )
                if poll.status_code != 200:
                    continue
                result = poll.json()
                if result["status"] == "completed":
                    await update.message.reply_text(format_prompt(result), parse_mode="Markdown")
                    return
                if result["status"] == "failed":
                    await update.message.reply_text(f"❌ {result.get('error', 'Unknown error')}")
                    return
            await update.message.reply_text("⏱️ Taking longer than expected. Use /history to check.")
        except Exception:
            await update.message.reply_text("❌ Connection error reaching the API.")


# ---------------------------------------------------------------------------
# Existing commands (v1 — updated to use telegram_id param)
# ---------------------------------------------------------------------------

async def challenge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = _chat_id(update)
    async with httpx.AsyncClient() as client:
        hist = await client.get(
            f"{API_BASE_URL}/history",
            headers=_AUTH(),
            params={"telegram_id": chat_id, "limit": 1},
            timeout=10.0,
        )
        if hist.status_code != 200 or not hist.json().get("prompts"):
            await update.message.reply_text("No briefs found. Send a voice message first.")
            return
        prompt_id = hist.json()["prompts"][0]["id"]
        await update.message.reply_text("🤔 Generating challenges...")
        resp = await client.post(
            f"{API_BASE_URL}/challenge",
            headers=_AUTH(),
            json={"prompt_id": prompt_id},
            timeout=30.0,
        )
        if resp.status_code != 200:
            await update.message.reply_text("❌ Failed to generate challenges.")
            return
        lines = ["*Project Challenges:*", ""]
        for i, c in enumerate(resp.json()["challenges"], 1):
            lines.append(f"{i}. {c}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = _chat_id(update)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE_URL}/history",
            headers=_AUTH(),
            params={"telegram_id": chat_id, "limit": 5},
            timeout=10.0,
        )
        prompts = resp.json().get("prompts", []) if resp.status_code == 200 else []
        if not prompts:
            await update.message.reply_text("No briefs yet. Send a voice message!")
            return
        lines = ["*Your Recent Project Briefs:*", ""]
        for p in prompts:
            summary = (p.get("raw_summary") or "Untitled").split("\n")[0]
            lines.append(f"`ID: {p['id']}` — {summary[:50]}...")
        lines += ["", "Use `/get ID` to see the full brief"]
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/get ID`")
        return
    try:
        prompt_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid ID — use a number.")
        return
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE_URL}/prompts/{prompt_id}",
            headers=_AUTH(),
            timeout=10.0,
        )
        if resp.status_code == 404:
            await update.message.reply_text("Brief not found.")
        elif resp.status_code == 200:
            await update.message.reply_text(format_prompt(resp.json()), parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Failed to fetch brief.")


# ---------------------------------------------------------------------------
# New v2 commands
# ---------------------------------------------------------------------------

async def brainstorm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Brainstorm ideas and pivots for the latest brief."""
    await update.message.reply_text("💡 Brainstorming...")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_BASE_URL}/brainstorm",
            headers=_AUTH(),
            params={"telegram_id": _chat_id(update)},
            timeout=30.0,
        )
        if resp.status_code != 200:
            await update.message.reply_text("❌ Brainstorm failed. Send a voice message first.")
            return
        data = resp.json()
        lines = ["*💡 Brainstorm*", ""]
        if data.get("ideas"):
            lines.append("*Feature ideas:*")
            lines.extend(f"• {i}" for i in data["ideas"])
            lines.append("")
        if data.get("pivots"):
            lines.append("*Possible pivots:*")
            lines.extend(f"• {p}" for p in data["pivots"])
            lines.append("")
        if data.get("similar_products"):
            lines.append("*Similar products:*")
            lines.extend(f"• {s}" for s in data["similar_products"])
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Weekly digest of all recent briefs."""
    await update.message.reply_text("📋 Generating your weekly summary...")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE_URL}/summary",
            headers=_AUTH(),
            params={"telegram_id": _chat_id(update)},
            timeout=60.0,
        )
        if resp.status_code != 200:
            await update.message.reply_text("❌ Summary failed. No briefs found?")
            return
        data = resp.json()
        header = f"*📋 Weekly Summary* ({data['prompt_count']} briefs)\n\n"
        await update.message.reply_text(header + data["digest"], parse_mode="Markdown")


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Semantic search: /search <query>"""
    if not context.args:
        await update.message.reply_text("Usage: `/search your query here`")
        return
    query = " ".join(context.args)
    await update.message.reply_text(f"🔍 Searching for: _{query}_", parse_mode="Markdown")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_BASE_URL}/search",
            headers=_AUTH(),
            json={"telegram_id": _chat_id(update), "query": query, "limit": 3},
            timeout=30.0,
        )
        if resp.status_code != 200:
            await update.message.reply_text("❌ Search failed.")
            return
        results = resp.json().get("results", [])
        if not results:
            await update.message.reply_text("No matching briefs found.")
            return
        lines = ["*Search Results:*", ""]
        for r in results:
            summary = (r.get("raw_summary") or "Untitled").split("\n")[0]
            tags = "  ".join(f"`{t}`" for t in r.get("tags", []))
            lines.append(f"`ID {r['prompt_id']}` ({r['score']:.2f}) — {summary[:60]}")
            if tags:
                lines.append(f"  {tags}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def evolution_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show timeline of how ideas evolved."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE_URL}/evolution",
            headers=_AUTH(),
            params={"telegram_id": _chat_id(update)},
            timeout=10.0,
        )
        if resp.status_code != 200:
            await update.message.reply_text("❌ Could not fetch evolution.")
            return
        entries = resp.json().get("entries", [])
        if not entries:
            await update.message.reply_text("No briefs yet. Send a voice message to start!")
            return
        lines = ["*🧬 Idea Evolution*", ""]
        for e in entries:
            date = e["created_at"][:10]
            summary = (e.get("raw_summary") or "Untitled").split("\n")[0]
            tags = "  ".join(f"`{t}`" for t in e.get("tags", []))
            lines.append(f"*{date}* — {summary[:60]}")
            if tags:
                lines.append(f"  {tags}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def ideas_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Filter briefs by tag: /ideas [tag]"""
    tag = context.args[0] if context.args else None
    params = {"telegram_id": _chat_id(update)}
    if tag:
        params["tag"] = tag
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE_URL}/ideas",
            headers=_AUTH(),
            params=params,
            timeout=10.0,
        )
        if resp.status_code != 200:
            await update.message.reply_text("❌ Could not fetch ideas.")
            return
        data = resp.json()
        prompts = data.get("prompts", [])
        header = f"*Ideas tagged `{tag}`*" if tag else "*All Tagged Briefs*"
        if not prompts:
            await update.message.reply_text(f"{header}\n\nNo briefs found.", parse_mode="Markdown")
            return
        lines = [header, ""]
        for p in prompts[:10]:
            summary = (p.get("raw_summary") or "Untitled").split("\n")[0]
            tags_str = "  ".join(f"`{t}`" for t in (p.get("tags") or []))
            lines.append(f"`ID {p['id']}` — {summary[:50]}")
            if tags_str:
                lines.append(f"  {tags_str}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Invite a collaborator: /add @username"""
    if not context.args:
        await update.message.reply_text("Usage: `/add @username`")
        return
    raw = context.args[0].lstrip("@")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_BASE_URL}/collaborators/invite",
            headers=_AUTH(),
            json={"inviter_telegram_id": _chat_id(update), "invitee_username": raw},
            timeout=10.0,
        )
        if resp.status_code == 409:
            await update.message.reply_text(f"Invite already pending for @{raw}.")
            return
        if resp.status_code != 200:
            await update.message.reply_text("❌ Could not send invite.")
            return
        data = resp.json()
        invite_id = data["invite_id"]
        invitee_chat_id = data.get("invitee_chat_id")

        await update.message.reply_text(
            f"✅ Invite sent to @{raw}! They'll need to accept it."
        )
        # If we know the invitee's chat_id, notify them directly
        if invitee_chat_id:
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Accept", callback_data=f"invite_accept_{invite_id}"),
                    InlineKeyboardButton("❌ Decline", callback_data=f"invite_decline_{invite_id}"),
                ]
            ])
            inviter_name = _username(update) or "Someone"
            await context.bot.send_message(
                chat_id=invitee_chat_id,
                text=f"🤝 *{inviter_name}* wants to collaborate with you on Recall!",
                reply_markup=keyboard,
                parse_mode="Markdown",
            )


async def invite_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button presses for invite accept/decline."""
    query = update.callback_query
    await query.answer()
    data = query.data  # e.g. "invite_accept_3" or "invite_decline_3"
    parts = data.split("_")
    action, invite_id = parts[1], int(parts[2])
    accept = action == "accept"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_BASE_URL}/collaborators/respond",
            headers=_AUTH(),
            json={
                "invite_id": invite_id,
                "responder_telegram_id": str(query.from_user.id),
                "accept": accept,
            },
            timeout=10.0,
        )
    if accept and resp.status_code == 200:
        await query.edit_message_text("✅ You joined the collaboration session!")
    elif resp.status_code == 200:
        await query.edit_message_text("Invite declined.")
    else:
        await query.edit_message_text("❌ Could not process the response.")


# ---------------------------------------------------------------------------
# /prompt — multi-turn ConversationHandler
# ---------------------------------------------------------------------------

async def prompt_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start /prompt: fetch questions and ask them all at once."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_BASE_URL}/prompt/start",
            headers=_AUTH(),
            json={"telegram_id": _chat_id(update)},
            timeout=30.0,
        )
        if resp.status_code != 200:
            await update.message.reply_text("❌ No brief found. Send a voice message first.")
            return ConversationHandler.END
        data = resp.json()
        context.user_data["prompt_prompt_id"] = data["prompt_id"]
        questions = data.get("questions", [])
        lines = ["*Before I generate your coding prompt, answer any of these:*", ""]
        for i, q in enumerate(questions, 1):
            lines.append(f"{i}. {q}")
        lines += ["", "_Reply with your answers (or just say 'skip' to use defaults)_"]
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return PROMPT_AWAITING_ANSWER


async def prompt_receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive answers and generate the vibe-coding prompt."""
    answers = update.message.text
    prompt_id = context.user_data.get("prompt_prompt_id")
    if not prompt_id:
        await update.message.reply_text("❌ Session lost. Start again with /prompt.")
        return ConversationHandler.END

    await update.message.reply_text("⚙️ Generating your coding prompt...")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_BASE_URL}/prompt/complete",
            headers=_AUTH(),
            json={"prompt_id": prompt_id, "answers": answers},
            timeout=30.0,
        )
        if resp.status_code != 200:
            await update.message.reply_text("❌ Could not generate prompt.")
            return ConversationHandler.END
        coding_prompt = resp.json().get("coding_prompt", "")
        await update.message.reply_text(
            f"*Your Coding Prompt:*\n\n{coding_prompt}", parse_mode="Markdown"
        )
    return ConversationHandler.END


async def prompt_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END
