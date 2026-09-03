import os
import requests
from flask import Blueprint, request, jsonify

telegram_bp = Blueprint('telegram', __name__)

# Fetch the token from environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8790012594:AAGdMLQALZZB9V1vRcHWFgTZhfmr15fbylk")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# --- Layer-by-Layer Keyboard Generators ---
def get_main_menu():
    return {
        "keyboard": [
            [{"text": "🎓 Internship Programs"}, {"text": "📜 Certificates & Verification"}],
            [{"text": "👥 Campus Ambassador Portal"}, {"text": "🤝 Enterprise/Company Hosting"}],
            [{"text": "💬 Talk to a Human"}]
        ],
        "resize_keyboard": True
    }

def get_internship_submenu():
    return {
        "keyboard": [
            [{"text": "💡 How do I apply?"}, {"text": "📅 What are the deadlines?"}],
            [{"text": "⏳ What is the 30-day window?"}, {"text": "💸 Are there upfront fees?"}],
            [{"text": "🔙 Back to Main Menu"}]
        ],
        "resize_keyboard": True
    }

def get_certificate_submenu():
    return {
        "keyboard": [
            [{"text": "🔍 How to verify a credential"}, {"text": "📑 What is the grading matrix?"}],
            [{"text": "🥇 How do I get an Elite LOR?"}, {"text": "🔙 Back to Main Menu"}]
        ],
        "resize_keyboard": True
    }

def get_ambassador_submenu():
    return {
        "keyboard": [
            [{"text": "🎁 What are the perks & swag?"}, {"text": "📈 How does ranking work?"}],
            [{"text": "🔙 Back to Main Menu"}]
        ],
        "resize_keyboard": True
    }

def send_message(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    
    try:
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram Send Error: {e}")

def handle_text_message(chat_id, text):
    text_lower = text.lower()
    
    # ----------------------------------------------------
    # LAYER 1: NAVIGATION & TOP LEVEL ROUTING
    # ----------------------------------------------------
    if "back to main menu" in text_lower or "/start" in text_lower:
        if "/start" in text_lower:
            inline_markup = {
                "inline_keyboard": [
                    [{"text": "📢 Join Announcement Channel", "url": "https://t.me/virtuole_in"}],
                    [{"text": "💬 Join Community Group", "url": "https://t.me/virtuole_community"}]
                ]
            }
            welcome_text = "Welcome to Virtuole Support! ⚡\n\nArchitecting the next generation of engineers through rigorous virtual internships and elite MSME-backed credentials."
            send_message(chat_id, welcome_text, reply_markup=inline_markup)
            
        response = "How can we help you build today? Choose an infrastructure layer from the menu below:" if "/start" in text_lower else "Returned to Main Matrix Menu. Select a technical layer:"
        current_markup = get_main_menu()

    elif "internship programs" in text_lower:
        response = "📁 Opened Internship Matrix. Select an engineering question layer:"
        current_markup = get_internship_submenu()

    elif "certificates & verification" in text_lower:
        response = "📁 Opened Credentials Lookup Database. Select an authentication question layer:"
        current_markup = get_certificate_submenu()

    elif "campus ambassador portal" in text_lower:
        response = "📁 Opened GTM Ambassador Node. Select a performance question layer:"
        current_markup = get_ambassador_submenu()

    # ----------------------------------------------------
    # LAYER 2: INTERNSHIP MATRIX PROCESSING
    # ----------------------------------------------------
    elif "how do i apply?" in text_lower or ("apply" in text_lower and "ambassador" not in text_lower):
        response = "Establish your profile directly on the Virtuole Gateway portal at https://www.virtuole.in/login. Choose your desired domain track (Beginner, Intermediate, or Expert) to initialize your dashboard immediately."
        current_markup = get_internship_submenu()

    elif "what are the deadlines?" in text_lower or "deadline" in text_lower:
        response = "📅 **Schedules & Tiers:**\n\nVirtuole runs strict 1-month and 2-month asynchronous sprints initializing on the 1st of every calendar month. Standard applications should be submitted at least 2 weeks before the month begins.\n\nEvent-based activations (Hackathons, Summer Sprints) follow specific timelines pushed to our announcement logs."
        current_markup = get_internship_submenu()

    elif "what is the 30-day window?" in text_lower or "30-day" in text_lower:
        response = "⏳ **Sprint Parameters:**\n\nOnce enrolled, you are granted exactly 30 days to execute your assigned system architecture specs asynchronously. No active hand-holding or passive lectures—just pure engineering production metrics tracked on your live status dashboard."
        current_markup = get_internship_submenu()

    elif "are there upfront fees?" in text_lower or "fee" in text_lower:
        response = "💸 **Financial Architecture:**\n\nVirtuole operates with zero upfront registration or environment allocation fees. You construct and build on the platform completely free. A nominal system evaluation and grading fee is only required at the finish line when submitting your finished code repository into the mentor grading matrix."
        current_markup = get_internship_submenu()

    # ----------------------------------------------------
    # LAYER 2: CERTIFICATION NODE PROCESSING
    # ----------------------------------------------------
    elif "how to verify a credential" in text_lower or "verify" in text_lower:
        response = "🔍 **System Lookup:**\n\nAll credentials issued carry unique cryptographic tracking hashes. Employers can query and instantly confirm verification states live via our official system portal at https://www.virtuole.in/verify.html."
        current_markup = get_certificate_submenu()

    elif "what is the grading matrix?" in text_lower or "matrix" in text_lower:
        response = "📑 **Evaluation Grading Rules:**\n\nSubmissions are thoroughly audited by enterprise engineering mentors for system efficiency, clean file structures, and algorithmic complexity. You must cross an execution score threshold of 80% or higher to pass and log your certificate. Failed sprints get 24 hours to patch the source logic."
        current_markup = get_certificate_submenu()

    elif "how do i get an elite lor?" in text_lower or "lor" in text_lower:
        response = "🥇 **Elite Founder's Recognition:**\n\nInterns who achieve a perfect 100% technical defense review across their architecture metrics will unlock the highly coveted, cryptographically signed Elite Founder's Letter of Recommendation alongside their standard MSME certificate."
        current_markup = get_certificate_submenu()

    # ----------------------------------------------------
    # LAYER 2: AMBASSADOR NODE PROCESSING
    # ----------------------------------------------------
    elif "perks & swag" in text_lower or "swag" in text_lower:
        response = "🎁 **Ambassador Toolkits:**\n\nApproved GTM Campus Ambassadors receive official Virtuole premium developer swag boxes, guaranteed placement slots, direct networking pathways, and automated multipliers toward leadership ranks."
        current_markup = get_ambassador_submenu()

    elif "ranking work" in text_lower or "ranking" in text_lower:
        response = "📈 **Rank Multipliers:**\n\nAmbassadors start at the Advocate layer and advance up to Lead nodes through system growth optimization, campus technical alignment, and hosting localized onboarding gates."
        current_markup = get_ambassador_submenu()

    # ----------------------------------------------------
    # GLOBAL CRITICAL OVERRIDES
    # ----------------------------------------------------
    elif "company looking to host" in text_lower or "company" in text_lower or "host" in text_lower:
        response = "🤝 **Enterprise Operations:**\n\nIf you represent a corporate entity looking to source audited engineering talent or securely host targeted sandboxed sprints, please route communications directly to our administrative hub at admin@virtuole.in."
        current_markup = get_main_menu()

    elif "human" in text_lower or "talk to a human" in text_lower:
        response = "💬 Please drop your specific architectural or deployment edge cases directly into our public engineering terminal (t.me/virtuole_community). Our human operations unit actively reviews and answers queries there!"
        current_markup = get_main_menu()

    else:
        response = "Terminal input unmapped. Please execute your choice using the layer menu keys below or report anomalies to our community group."
        current_markup = get_main_menu()
        
    send_message(chat_id, response, current_markup)


@telegram_bp.route('/api/telegram/webhook', methods=['POST'])
def webhook():
    try:
        update = request.get_json()
        if not update:
            return "OK", 200
            
        if "message" in update:
            message = update["message"]
            chat_id = message.get("chat", {}).get("id")
            text = message.get("text", "")
            
            # Handle new members
            new_members = message.get("new_chat_members", [])
            if new_members:
                for member in new_members:
                    if not member.get("is_bot", False):
                        welcome_msg = f"Welcome to the Virtuole community, {member.get('first_name', 'Builder')}! 🚀\nIf you ever need help or have platform questions, just DM me directly at @virtuole_bot."
                        send_message(chat_id, welcome_msg)
            
            # Handle text messages
            if text and message.get("chat", {}).get("type") == "private":
                handle_text_message(chat_id, text)
                
    except Exception as e:
        print(f"Webhook processing error: {e}")
        
    return "OK", 200


@telegram_bp.route('/api/telegram/set-webhook', methods=['GET'])
def set_webhook():
    host = request.host_url.rstrip('/')
    webhook_url = f"{host}/api/telegram/webhook"
    
    try:
        res = requests.get(f"{TELEGRAM_API_URL}/setWebhook?url={webhook_url}")
        return jsonify({"status": "Webhook setting attempted", "telegram_response": res.json(), "url_set": webhook_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
