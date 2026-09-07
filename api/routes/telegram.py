import os
import requests
from flask import Blueprint, request, jsonify

try:
    import google.generativeai as genai
except ImportError:
    genai = None

telegram_bp = Blueprint('telegram', __name__)

# Fetch the token from environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8790012594:AAGdMLQALZZB9V1vRcHWFgTZhfmr15fbylk")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Initialize Gemini AI
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY and genai:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    model = None

VIRTUOLE_KNOWLEDGE_BASE = """
You are the official Virtuole Support Agent (an AI assistant on Telegram). You speak professionally, enthusiastically, and helpfully. You can speak in English or Hinglish based on the user's language. Keep answers short (under 100 words) and suitable for Telegram. Use emojis like 🚀, 💻, 🎓.

ABOUT VIRTUOLE:
- Virtuole is an ed-tech platform offering premium, MSME-recognized virtual internships for students.
- Founder & CEO: Vishal Kumar.
- Website: https://www.virtuole.in

HOW THE INTERNSHIP WORKS:
1. Apply: Students sign up at virtuole.in/login and select a track (Frontend, Backend, Android, AIML, Data Science, Python, Java, C++, UIUX, DevRel, etc.). They choose a duration (1 Month Beginner, 2 Months Intermediate, 3 Months Expert).
2. Cost: Zero upfront fees! The internship and dashboard are completely free.
3. Offer Letter: Generated instantly upon enrollment.
4. The Task: Students get 30 days to build real-world engineering projects asynchronously.
5. Submission & Grading: When finished, students submit their GitHub repository link. A nominal evaluation/grading fee is required AT THE END to unlock the grading matrix and MSME certificate.
6. Certificate & LOR: 80%+ score gets a verified MSME certificate. 100% Elite score gets a Founder's Letter of Recommendation (LOR). Failed submissions get 24 hours to patch the code and resubmit.

CAMPUS AMBASSADOR PROGRAM (GTM):
- Students can refer friends to earn points.
- Perks: Official Virtuole premium developer swag boxes (T-shirts, bottles, etc.), guaranteed placements, and ranks (Advocate to Lead).
- Tiers unlock at specific point milestones. High tiers get physical swag mailed to them.

RULES FOR ANSWERING:
- Always be encouraging.
- If asked about a specific internship (e.g. "frontend me kya karna hoga"), explain that they will build a responsive, production-grade project using relevant technologies and push code to GitHub.
- If asked about pricing, strictly say: "Zero upfront fees to build! You only pay a small grading/evaluation fee at the very end when you submit your code for MSME certification."
"""

# --- Layer-by-Layer Keyboard Generators ---
def get_main_menu():
    return {
        "keyboard": [
            [{"text": "🎓 Internship Programs"}, {"text": "📜 Certificates & Verification"}],
            [{"text": "👥 Campus Ambassador Portal"}, {"text": "🏢 About Virtuole / Contact"}]
        ],
        "resize_keyboard": True
    }

def get_internship_submenu():
    return {
        "keyboard": [
            [{"text": "💡 How do I apply?"}, {"text": "💻 Available Domains"}],
            [{"text": "⏳ Durations & Sprints"}, {"text": "💸 Fees & Structure"}],
            [{"text": "🔙 Back to Main Menu"}]
        ],
        "resize_keyboard": True
    }

def get_certificate_submenu():
    return {
        "keyboard": [
            [{"text": "🔍 How to Verify?"}, {"text": "📑 Grading Matrix"}],
            [{"text": "🥇 Elite LOR"}, {"text": "📜 MSME Certification"}],
            [{"text": "🔙 Back to Main Menu"}]
        ],
        "resize_keyboard": True
    }

def get_ambassador_submenu():
    return {
        "keyboard": [
            [{"text": "🤝 How to Join?"}, {"text": "🎁 Perks & Swag"}],
            [{"text": "📈 Tiers & Ranking"}, {"text": "🔙 Back to Main Menu"}]
        ],
        "resize_keyboard": True
    }

def get_about_submenu():
    return {
        "keyboard": [
            [{"text": "🏢 What is Virtuole?"}, {"text": "🤝 Enterprise Hosting"}],
            [{"text": "💬 Talk to a Human"}, {"text": "🔙 Back to Main Menu"}]
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
            
        response = "How can we help you build today? Choose a sector from the menu below:" if "/start" in text_lower else "Returned to Main Menu. Select a sector:"
        current_markup = get_main_menu()

    elif "internship programs" in text_lower:
        response = "📁 **Internship Matrix:** Select a topic to learn more about our internship structure:"
        current_markup = get_internship_submenu()

    elif "certificates & verification" in text_lower:
        response = "📁 **Credentials & Verification:** Select a topic to learn about MSME certification and validation:"
        current_markup = get_certificate_submenu()

    elif "campus ambassador portal" in text_lower:
        response = "📁 **GTM Ambassador Program:** Select a topic to learn about perks, tiers, and joining:"
        current_markup = get_ambassador_submenu()

    elif "about virtuole" in text_lower or "contact" in text_lower:
        response = "📁 **About Virtuole & Contact:** Select an option below to learn more or contact support:"
        current_markup = get_about_submenu()


    # ----------------------------------------------------
    # LAYER 2: INTERNSHIP MATRIX
    # ----------------------------------------------------
    elif "how do i apply" in text_lower:
        response = "💡 **How to Apply:**\n\nEstablish your profile directly on the Virtuole Gateway portal at https://www.virtuole.in/login. Choose your desired domain track and duration to initialize your dashboard immediately. Your Offer Letter is generated instantly!"
        current_markup = get_internship_submenu()

    elif "available domains" in text_lower:
        response = "💻 **Available Domains:**\n\nWe offer production-grade virtual internships in:\n- Frontend & Backend Development\n- Full Stack Engineering\n- Android App Development\n- AI / ML & Data Science\n- Python, Java, C++\n- UI/UX Design\n- Developer Relations (DevRel)"
        current_markup = get_internship_submenu()

    elif "durations & sprints" in text_lower:
        response = "⏳ **Durations & Sprints:**\n\nYou can choose from 3 sprint levels:\n- **Beginner:** 1 Month\n- **Intermediate:** 2 Months\n- **Expert:** 3 Months\n\nOnce enrolled, you are granted exactly 30 days per sprint to execute your assigned system architecture specs asynchronously."
        current_markup = get_internship_submenu()

    elif "fees & structure" in text_lower:
        response = "💸 **Fees & Structure:**\n\nVirtuole operates with **zero upfront registration fees**. You construct and build on the platform completely free. \n\nA nominal system evaluation and grading fee is only required at the finish line when submitting your finished code repository for Mentor Grading and MSME Certification."
        current_markup = get_internship_submenu()

    # ----------------------------------------------------
    # LAYER 2: CERTIFICATES & VERIFICATION
    # ----------------------------------------------------
    elif "how to verify" in text_lower:
        response = "🔍 **Verify a Credential:**\n\nAll credentials issued carry unique cryptographic tracking hashes. Employers can query and instantly confirm verification states live via our official system portal at https://www.virtuole.in/verify.html."
        current_markup = get_certificate_submenu()

    elif "grading matrix" in text_lower:
        response = "📑 **Evaluation Grading Rules:**\n\nSubmissions are thoroughly audited by enterprise engineering mentors for system efficiency, clean file structures, and algorithmic complexity. You must cross an execution score threshold of 80% or higher to pass. Failed sprints get 24 hours to patch the source logic."
        current_markup = get_certificate_submenu()

    elif "elite lor" in text_lower:
        response = "🥇 **Elite Founder's Recognition:**\n\nInterns who achieve a perfect 100% technical defense review across their architecture metrics will unlock the highly coveted, cryptographically signed Elite Founder's Letter of Recommendation (LOR)."
        current_markup = get_certificate_submenu()

    elif "msme certification" in text_lower:
        response = "📜 **MSME Certification:**\n\nVirtuole is an official Government of India registered MSME. All certificates issued upon passing the Grading Matrix carry the MSME recognition, making your credentials highly credible for corporate placements."
        current_markup = get_certificate_submenu()

    # ----------------------------------------------------
    # LAYER 2: AMBASSADOR NODE
    # ----------------------------------------------------
    elif "how to join" in text_lower:
        response = "🤝 **Join the GTM Program:**\n\nApply to become a Campus Ambassador at https://www.virtuole.in/apply-ambassador. If selected, you will become the primary tech liaison for Virtuole at your university."
        current_markup = get_ambassador_submenu()

    elif "perks & swag" in text_lower:
        response = "🎁 **Ambassador Toolkits & Perks:**\n\nApproved GTM Campus Ambassadors receive official Virtuole premium developer swag boxes (T-Shirts, Bottles, Stickers), guaranteed placement slots, and direct networking pathways with our core engineering team."
        current_markup = get_ambassador_submenu()

    elif "tiers & ranking" in text_lower:
        response = "📈 **Tiers & Ranking:**\n\nAmbassadors earn points by referring students. You start at the **Advocate** layer and can advance up to **Lead** and **Evangelist** nodes. Higher tiers unlock Certificates, LORs, and exclusive Physical Swag Boxes!"
        current_markup = get_ambassador_submenu()

    # ----------------------------------------------------
    # LAYER 2: ABOUT / CONTACT
    # ----------------------------------------------------
    elif "what is virtuole" in text_lower:
        response = "🏢 **About Virtuole:**\n\nVirtuole is an elite ed-tech platform architecting the next generation of engineers. We provide high-quality, project-based virtual internships that bridge the gap between theoretical academia and rigorous industry execution."
        current_markup = get_about_submenu()

    elif "enterprise hosting" in text_lower:
        response = "🤝 **Enterprise Operations:**\n\nIf you represent a corporate entity looking to source audited engineering talent or securely host targeted sandboxed sprints, please route communications directly to our administrative hub at admin@virtuole.in."
        current_markup = get_about_submenu()

    elif "talk to a human" in text_lower:
        response = "💬 Please drop your specific architectural or deployment edge cases directly into our public engineering terminal: https://t.me/virtuole_community. Our human operations unit actively reviews and answers queries there!"
        current_markup = get_about_submenu()

    # ----------------------------------------------------
    # AI FALLBACK
    # ----------------------------------------------------
    else:
        if model:
            try:
                # Ask Gemini AI instead of failing
                prompt = f"{VIRTUOLE_KNOWLEDGE_BASE}\n\nUser Question: {text}\n\nAgent Answer:"
                ai_response = model.generate_content(prompt)
                response = ai_response.text.strip()
            except Exception as e:
                print(f"Gemini AI Error: {e}")
                response = "I am currently upgrading my AI processors! Please use the menu below or try again later. 🤖⚡"
        else:
            response = "I am currently undergoing AI training! In the meantime, please execute your choice using the layer menu keys below. (Dev note: Add GEMINI_API_KEY to Vercel to activate AI)"
        current_markup = get_main_menu()
        
    send_message(chat_id, response, current_markup)


@telegram_bp.route('/telegram-webhook', methods=['POST'])
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


@telegram_bp.route('/telegram-set-webhook', methods=['GET'])
def set_webhook():
    host = request.host_url.rstrip('/')
    webhook_url = f"{host}/telegram-webhook"
    
    try:
        res = requests.get(f"{TELEGRAM_API_URL}/setWebhook?url={webhook_url}")
        return jsonify({"status": "Webhook setting attempted", "telegram_response": res.json(), "url_set": webhook_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
