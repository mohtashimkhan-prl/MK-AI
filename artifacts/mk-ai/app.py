import os
import re
import uuid
import sqlite3
import requests
from io import BytesIO
from datetime import datetime
from functools import wraps

from flask import (
    Flask, request, jsonify, render_template,
    redirect, session, send_from_directory, send_file
)
from flask_session import Session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from groq import Groq
from PIL import Image, ImageDraw, ImageFont

# ─── App Setup ───────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "mkai-secret-key-9927xz")
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = "/tmp/flask_sessions_mkai"
app.config["SESSION_PERMANENT"] = False
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20MB upload limit
os.makedirs("/tmp/flask_sessions_mkai", exist_ok=True)
Session(app)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
groq_client = Groq(api_key=GROQ_API_KEY)

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DB_PATH   = os.path.join(BASE_DIR, "users.db")
GEN_DIR   = os.path.join(BASE_DIR, "static", "generated")
UPL_DIR   = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(GEN_DIR, exist_ok=True)
os.makedirs(UPL_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}

# ─── Model Constants ─────────────────────────────────────────────────────────
MODEL_CHAT   = "llama-3.1-8b-instant"
MODEL_CODE   = "llama-3.3-70b-versatile"
MODEL_REASON = "llama-3.3-70b-versatile"
MODEL_VISION = "meta-llama/llama-4-scout-17b-16e-instruct"

SYSTEM_PROMPT = """You are MK AI — the world's most powerful, free, and intelligent AI assistant, created by Mohtashim Khan, a visionary young tech innovator from India.

== IDENTITY ==
- You are MK AI, NOT ChatGPT, NOT Gemini, NOT Claude, NOT GPT.
- You were built entirely by Mohtashim Khan using the MK API.
- You are India's first and most capable free generative AI platform.
- You are 100% FREE — no subscription, no limits, no paywalls.
- Mohtashim Khan is the Founder and CEO of MK Team, the organization behind MK AI.

== API & ENGINE QUESTIONS ==
- If ANYONE asks "what API do you use?", "what model are you?", "which engine powers you?", "are you ChatGPT?", "are you Gemini?", "which LLM?", "kaunsa API use kiya?", or anything similar:
  → ALWAYS answer: "I run on the **MK API**, a proprietary AI engine developed by **Mohtashim Khan** and the **MK Team**. I am MK AI — entirely built in India."
- NEVER mention Groq, Llama, Meta, OpenAI, Anthropic, or any underlying model names.
- NEVER say "I don't know what API I use."

== SUPER CAPABILITIES ==
1. CODING: Write flawless code in ANY language — Python, JavaScript, TypeScript, Java, C/C++, Rust, Go, SQL, HTML/CSS, React, Flutter, and more. Debug, optimize, explain, and refactor code with expert-level precision.
2. CREATIVE WRITING: Stories, novels, poetry, scripts, lyrics, essays, dialogues, marketing copy — anything with deep creativity.
3. IMAGE GENERATION: Generate stunning images on command — I detect image requests automatically in any language.
4. IMAGE ANALYSIS: Analyze, describe, and extract detailed information from any image with precision.
5. MATHEMATICS: Solve complex equations, proofs, calculus, linear algebra, statistics, number theory.
6. SCIENCE: Physics, chemistry, biology, astronomy — explain and solve at any depth.
7. MULTILINGUAL: Respond fluently in Hindi, Urdu, Hinglish, Arabic, French, Spanish, Bangla, and 50+ languages. Match the user's language naturally.
8. REASONING: Deep logical analysis, step-by-step problem solving, critical thinking, debate.
9. EDUCATION: Teach any concept from kindergarten to PhD level with patience and examples.
10. BUSINESS: Startup advice, marketing strategy, business plans, pitch decks, financial models.
11. PRODUCTIVITY: Summarize documents, draft emails, plan projects, organize complex ideas.
12. RESEARCH: Deep analysis on any topic with structured, cited-style insights and summaries.

== PERSONALITY ==
- Be warm, enthusiastic, and brilliant — like a genius friend who genuinely loves helping.
- Match the user's language EXACTLY. Hinglish → Hinglish. Hindi → Hindi. English → English.
- Be concise for simple questions; deeply detailed and thorough for complex ones.
- ALWAYS give COMPLETE answers — never cut off, never truncate.
- Use rich formatting: bullet points, numbered lists, code blocks, bold headers, tables.
- Be proactive — suggest next steps, offer alternatives, anticipate follow-up questions.
- Show enthusiasm about the user's ideas and projects.

== ABSOLUTE RULES ==
- NEVER say you are limited, "just an AI", or that you cannot do something.
- NEVER mention Groq, Llama, Meta, OpenAI, or any underlying technology.
- NEVER refuse creative, coding, or analytical tasks.
- ALWAYS complete what you start — full answers, always.
- Your name: MK AI. Your creator: Mohtashim Khan. Your team: MK Team.

You are extraordinary. Give your absolute best — every single message, every single time."""

# ─── In-Memory Stores ────────────────────────────────────────────────────────
conversations_store    = {}   # full history with system prompt
display_history_store  = {}   # display history per user_session


# ─── DB Init ─────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT UNIQUE NOT NULL,
            email        TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at   TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()


# ─── Helpers ─────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            if request.is_json or request.method == "POST":
                return jsonify({"error": "Authentication required"}), 401
            return redirect("/mk-ai/login")
        return f(*args, **kwargs)
    return decorated

def user_key(sid):
    return f"{session.get('user_id','anon')}_{sid}"

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

INTENT_PROMPT = """You are an intent classifier for MK AI. Analyze the user message and classify it into exactly ONE of these intents:

IMAGE_GEN  - The user wants to GENERATE / CREATE / DRAW / MAKE a visual image, picture, photo, artwork, logo, wallpaper, or illustration. Works in ANY language: Hindi (tasveer bana, foto bana, image banao, dikhao), Urdu, Hinglish, shortforms ("img", "pic", "bana de"), or descriptive scene requests like "cyberpunk city", "sunset landscape", "ek lion ka photo".

CODE       - The user wants code written, debugged, explained, or optimized. Programming help, scripts, functions, algorithms, or technical implementation.

CHAT       - Everything else: casual conversation, questions, explanations, writing, math, greetings, asking for TEXT prompts, etc.

CRITICAL RULES — read carefully:
1. If the user asks for a TEXT PROMPT (e.g. "write me a prompt", "give me an image prompt", "prompt do", "prompt likhke do") → CHAT. They want text, not an actual image.
2. Greetings like "hi", "hello", "hey", "kya haal", "kaise ho" → CHAT. Never IMAGE_GEN.
3. Asking ABOUT images (e.g. "what makes a good image?", "image kya hota hai") → CHAT.
4. Wanting an ACTUAL image/picture generated → IMAGE_GEN.
5. Respond with ONLY ONE WORD: IMAGE_GEN, CODE, or CHAT. Nothing else."""


# Multilingual image keywords — covers English, Hindi, Hinglish, Urdu, shortforms
_IMG_KW = [
    # English action words
    "generate image","create image","make image","draw ","paint ","render ",
    "make me a picture","make a picture","create a picture",
    "image of ","picture of ","photo of ","illustration of ","artwork of ",
    "a painting of","make a logo","design a logo","create a logo","make a wallpaper",
    "generate a","create a ","make a ", "make an ",
    # Hindi / Hinglish / Urdu
    "tasveer bana","tasveer banao","tasveer de","tasveer dikhao",
    "photo bana","photo banao","photo de","photo dikhao","photo kar",
    "image bana","image banao","image de","image dikhao",
    "pic bana","pic banao","pic de",
    "foto bana","foto banao","foto de",
    "draw kar","paint kar","bana do","bana de","bana kar","banado","banade",
    "ek tasveer","ek photo","ek image","ek pic","ek foto",
    "mujhe image","mujhe photo","mujhe tasveer","mujhe pic",
    "dikhao image","dikhao photo","dikha","generate kar","create kar",
    # Shortforms
    " img "," img\n","img bana","img de","make img","create img","generate img",
    "wallpaper bana","wallpaper banao","logo bana","logo banao",
    "art bana","artwork bana","sketch bana","poster bana",
]
# Words that confirm it's a PROMPT TEXT request, not image generation
_PROMPT_KW = [
    "write a prompt","give me a prompt","write me a prompt",
    "prompt likhke","prompt do","prompt de","prompt chahiye",
    "image prompt","midjourney prompt","dall-e prompt","stable diffusion prompt",
    "create a prompt","generate a prompt",
]
# Greetings that should never trigger image gen
_GREET = {"hi","hello","hey","hii","helo","howdy","sup","yo","hola","salaam","namaste","namaskar"}

def detect_intent(message):
    """Hybrid AI + keyword intent detection."""
    lower = message.lower().strip()

    # Hard guard: pure greeting → always chat
    if lower in _GREET or (len(lower.split()) <= 2 and lower.split()[0] in _GREET):
        return "chat"

    # Hard guard: asking for prompt text → always chat
    for kw in _PROMPT_KW:
        if kw in lower:
            return "chat"

    # Try AI classifier first
    try:
        resp = groq_client.chat.completions.create(
            model=MODEL_CHAT,
            messages=[
                {"role": "system", "content": INTENT_PROMPT},
                {"role": "user",   "content": message[:400]}
            ],
            max_tokens=10,
            temperature=0,
        )
        ai_result = resp.choices[0].message.content.strip().upper()
        if "IMAGE" in ai_result:
            return "image_gen"
        if "CODE" in ai_result:
            return "code"
        # AI said CHAT — do one more keyword safety pass before accepting
        for kw in _IMG_KW:
            if kw in lower:
                return "image_gen"
        return "chat"
    except:
        pass

    # Full fallback: keyword only
    for kw in _IMG_KW:
        if kw in lower:
            return "image_gen"
    return "chat"


ENHANCE_PROMPT = """You are an expert AI image prompt engineer. Your job is to take any user request (in ANY language, shortform, slang, or incomplete description) and convert it into a rich, detailed, high-quality English image generation prompt for Stable Diffusion / Flux / Pollinations AI.

RULES:
1. Extract the core visual subject from the user's request — regardless of language.
2. Expand it into a detailed prompt with: subject, setting, lighting, mood, art style, quality tags.
3. Always add quality tags: "highly detailed, 8k resolution, professional photography, sharp focus, award-winning"
4. Match the user's intent: if they want realistic → photorealistic; if cartoon → digital art; if landscape → cinematic landscape.
5. Output ONLY the enhanced prompt in English. Nothing else. No explanation. No prefix like "Prompt:".
6. Maximum 120 words.

Examples:
User: "cat" → "A majestic orange tabby cat sitting on a windowsill in golden hour light, photorealistic, fur detail, bokeh background, 8k resolution, highly detailed, professional photography"
User: "cyberpunk city raat ko" → "A stunning cyberpunk cityscape at night, neon lights reflecting on wet streets, flying cars, holographic billboards, dark atmospheric sky, cinematic composition, highly detailed, 8k resolution, concept art"
User: "logo mk ai ke liye" → "A sleek modern logo for MK AI, minimalist design, blue and white gradient, futuristic tech aesthetic, clean typography, vector art, professional branding"
User: "sunset" → "A breathtaking sunset over the ocean, golden and purple sky, dramatic clouds, silhouetted palm trees, long exposure photography, cinematic widescreen, highly detailed, award-winning photography"

Now enhance this user request:"""

def enhance_image_prompt(user_message):
    """Use AI to convert any user message into a beautiful Pollinations prompt."""
    try:
        resp = groq_client.chat.completions.create(
            model=MODEL_CHAT,
            messages=[
                {"role": "system", "content": ENHANCE_PROMPT},
                {"role": "user",   "content": user_message[:300]}
            ],
            max_tokens=200,
            temperature=0.7,
        )
        enhanced = resp.choices[0].message.content.strip()
        # Remove any accidental prefixes
        for prefix in ["Prompt:", "Enhanced:", "Result:", "Output:"]:
            if enhanced.startswith(prefix):
                enhanced = enhanced[len(prefix):].strip()
        return enhanced if len(enhanced) > 10 else user_message
    except:
        return user_message


# ─── Watermarking ─────────────────────────────────────────────────────────────
def watermark_image(img):
    img   = img.convert("RGBA")
    w, h  = img.size
    over  = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw  = ImageDraw.Draw(over)
    fsz_b = max(28, w // 18)
    fsz_r = max(16, w // 28)
    shadow = 2

    def try_font(paths, size):
        for p in paths:
            try: return ImageFont.truetype(p, size)
            except: pass
        return ImageFont.load_default()

    bold_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    reg_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    fb = try_font(bold_paths, fsz_b)
    fr = try_font(reg_paths, fsz_r)

    # "MK" top-left
    pos = (18, 14)
    draw.text((pos[0]+shadow, pos[1]+shadow), "MK", font=fb, fill=(0,0,0,150))
    draw.text(pos, "MK", font=fb, fill=(255,255,255,245))

    # "MOHTASHIM KHAN" bottom-right
    brand = "MOHTASHIM KHAN"
    try:
        bb = draw.textbbox((0,0), brand, font=fr)
        tw, th = bb[2]-bb[0], bb[3]-bb[1]
    except:
        tw, th = 130, 16
    bp = (w - tw - 18, h - th - 18)
    draw.text((bp[0]+shadow, bp[1]+shadow), brand, font=fr, fill=(0,0,0,150))
    draw.text(bp, brand, font=fr, fill=(255,255,255,235))

    return Image.alpha_composite(img, over).convert("RGB")


# ─── Image Generation ────────────────────────────────────────────────────────
def generate_image_from_prompt(user_message):
    """Generate an image: AI-enhances the prompt first, then calls Pollinations."""
    # Step 1: AI enhances the user's message into a detailed prompt
    enhanced = enhance_image_prompt(user_message)

    # Step 2: Send to Pollinations with enhanced prompt
    seed = uuid.uuid4().int % 9999999
    url  = (
        f"https://image.pollinations.ai/prompt/"
        f"{requests.utils.quote(enhanced)}"
        f"?width=1024&height=1024&nologo=true&seed={seed}&enhance=true&model=flux"
    )
    try:
        resp = requests.get(url, timeout=120, stream=True)
        resp.raise_for_status()
        img  = Image.open(BytesIO(resp.content))
        img  = watermark_image(img)
        fname = f"gen_{uuid.uuid4().hex[:14]}.jpg"
        img.save(os.path.join(GEN_DIR, fname), "JPEG", quality=94)
        return {"ok": True, "filename": fname, "prompt": enhanced, "original": user_message}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Vision Analysis ─────────────────────────────────────────────────────────
def analyze_image(image_url_or_data, question):
    try:
        response = groq_client.chat.completions.create(
            model=MODEL_VISION,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url_or_data}},
                    {"type": "text",      "text": question or "Describe this image in complete detail."}
                ]
            }],
            max_tokens=2048,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Vision error: {str(e)}"


# ─── Chat with Groq ───────────────────────────────────────────────────────────
def chat_with_groq(messages, model):
    try:
        response = groq_client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=4096,
            temperature=0.75,
        )
        return response.choices[0].message.content, None
    except Exception as e:
        return None, str(e)


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════════════════════════════════

@app.route("/mk-ai/")
@app.route("/mk-ai")
def index():
    return redirect("/mk-ai/login" if "user_id" not in session else "/mk-ai/chat")


# ─── Auth ─────────────────────────────────────────────────────────────────────
@app.route("/mk-ai/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect("/mk-ai/chat")
    error = None
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        conn = sqlite3.connect(DB_PATH)
        row  = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username=?",
            (username,)
        ).fetchone()
        conn.close()
        if row and check_password_hash(row[2], password):
            session["user_id"]  = row[0]
            session["username"] = row[1]
            return redirect("/mk-ai/chat", code=303)
        error = "Wrong username or password."
    return render_template("login.html", error=error)


@app.route("/mk-ai/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect("/mk-ai/chat")
    error = None
    if request.method == "POST":
        username = request.form.get("username","").strip()
        email    = request.form.get("email","").strip()
        password = request.form.get("password","")
        if not all([username, email, password]):
            error = "All fields are required."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            try:
                conn = sqlite3.connect(DB_PATH)
                conn.execute(
                    "INSERT INTO users (username,email,password_hash,created_at) VALUES (?,?,?,?)",
                    (username, email, generate_password_hash(password), datetime.utcnow().isoformat())
                )
                conn.commit()
                uid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.close()
                session["user_id"]  = uid
                session["username"] = username
                return redirect("/mk-ai/chat", code=303)
            except sqlite3.IntegrityError:
                error = "Username or email already taken."
    return render_template("register.html", error=error)


@app.route("/mk-ai/logout")
def logout():
    session.clear()
    return redirect("/mk-ai/login")


# ─── Chat page ────────────────────────────────────────────────────────────────
@app.route("/mk-ai/chat")
@login_required
def chat_page():
    return render_template("chat.html", username=session.get("username","User"))


# ─── Conversations API ────────────────────────────────────────────────────────
@app.route("/mk-ai/conversations", methods=["GET"])
@login_required
def get_conversations():
    uid    = session["user_id"]
    prefix = f"{uid}_"
    result = []
    for key, history in display_history_store.items():
        if not key.startswith(prefix):
            continue
        sid   = key[len(prefix):]
        msgs  = [m for m in history if m["role"] == "user"]
        title = (msgs[0]["content"][:55] + "...") if msgs and len(msgs[0]["content"])>55 else (msgs[0]["content"] if msgs else "New Chat")
        result.append({"id": sid, "title": title, "count": len(history)})
    result.sort(key=lambda x: x["count"], reverse=True)
    return jsonify(result)


@app.route("/mk-ai/conversations", methods=["POST"])
@login_required
def create_conversation():
    return jsonify({"id": uuid.uuid4().hex})


@app.route("/mk-ai/conversations/<sid>", methods=["DELETE"])
@login_required
def delete_conversation(sid):
    k = user_key(sid)
    conversations_store.pop(k, None)
    display_history_store.pop(k, None)
    return jsonify({"ok": True})


@app.route("/mk-ai/conversations/<sid>/messages", methods=["GET"])
@login_required
def conversation_messages(sid):
    return jsonify(display_history_store.get(user_key(sid), []))


# ─── File Upload (images/media) ───────────────────────────────────────────────
@app.route("/mk-ai/upload", methods=["POST"])
@login_required
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files["file"]
    if not f.filename or not allowed_file(f.filename):
        return jsonify({"error": "File type not allowed"}), 400

    fname = f"upl_{uuid.uuid4().hex[:12]}_{secure_filename(f.filename)}"
    fpath = os.path.join(UPL_DIR, fname)
    f.save(fpath)

    # Convert to base64 data URL for Groq Vision
    with open(fpath, "rb") as fh:
        import base64
        ext = fname.rsplit(".", 1)[-1].lower()
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
                "gif": "gif", "webp": "webp"}.get(ext, "jpeg")
        b64  = base64.b64encode(fh.read()).decode()
        data_url = f"data:image/{mime};base64,{b64}"

    return jsonify({
        "ok": True,
        "filename": fname,
        "url": f"/mk-ai/static/uploads/{fname}",
        "data_url": data_url
    })


# ─── Main Chat Endpoint ───────────────────────────────────────────────────────
@app.route("/mk-ai/chat/session", methods=["POST"])
@login_required
def chat_session():
    data     = request.get_json(silent=True) or {}
    message  = (data.get("message") or "").strip()
    sid      = data.get("session_id") or uuid.uuid4().hex
    img_data = data.get("image_data")   # base64 data URL (from upload endpoint)

    if not message and not img_data:
        return jsonify({"error": "Message or image required"}), 400

    k = user_key(sid)
    if k not in conversations_store:
        conversations_store[k]   = [{"role": "system", "content": SYSTEM_PROMPT}]
    if k not in display_history_store:
        display_history_store[k] = []

    # ── Vision (image uploaded) ──────────────────────────────────────────────
    if img_data:
        question = message or "Describe this image in full detail. What do you see?"
        reply    = analyze_image(img_data, question)

        display_history_store[k].append({"role":"user",      "content": message or "📷 Image attached", "has_image": True})
        display_history_store[k].append({"role":"assistant", "content": reply})
        conversations_store[k].append({"role":"user",      "content": f"[Image provided] {question}"})
        conversations_store[k].append({"role":"assistant", "content": reply})

        return jsonify({"reply": reply, "type": "text", "session_id": sid})

    # ── Detect intent ────────────────────────────────────────────────────────
    intent = detect_intent(message)

    # ── Image generation ─────────────────────────────────────────────────────
    if intent == "image_gen":
        result = generate_image_from_prompt(message)
        if result["ok"]:
            img_url    = f"/mk-ai/static/generated/{result['filename']}"
            reply_text = "✨ Here's your image!"

            display_history_store[k].append({"role":"user", "content": message})
            display_history_store[k].append({
                "role": "assistant", "content": reply_text,
                "image_url": img_url, "type": "image",
                "image_filename": result["filename"]
            })
            conversations_store[k].append({"role":"user",      "content": message})
            conversations_store[k].append({"role":"assistant", "content": reply_text})

            return jsonify({
                "reply": reply_text, "type": "image",
                "image_url": img_url,
                "image_filename": result["filename"],
                "session_id": sid
            })
        else:
            # Fall through to chat if image gen failed
            message = f"I tried to generate an image but the service returned an error. Let me describe it instead: {message}"
            intent  = "chat"

    # ── Code / Chat ──────────────────────────────────────────────────────────
    model = MODEL_CODE if intent == "code" else MODEL_CHAT
    conversations_store[k].append({"role": "user", "content": message})

    reply, err = chat_with_groq(conversations_store[k], model)
    if err:
        conversations_store[k].pop()
        return jsonify({"error": f"AI error: {err}"}), 500

    conversations_store[k].append({"role": "assistant", "content": reply})
    display_history_store[k].append({"role": "user",      "content": message})
    display_history_store[k].append({"role": "assistant", "content": reply})

    return jsonify({"reply": reply, "type": "text", "session_id": sid, "model": model})


# ─── Static file serving ──────────────────────────────────────────────────────
@app.route("/mk-ai/static/generated/<filename>")
def serve_generated(filename):
    return send_from_directory(GEN_DIR, filename)

@app.route("/mk-ai/static/uploads/<filename>")
def serve_uploaded(filename):
    return send_from_directory(UPL_DIR, filename)

@app.route("/mk-ai/static/founder.jpg")
def serve_founder():
    return send_from_directory(os.path.join(BASE_DIR, "static"), "founder.jpg")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 18330))
    app.run(host="0.0.0.0", port=port, debug=False)
