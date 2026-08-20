import os
import sqlite3
import tempfile

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from openai import OpenAI
from dotenv import load_dotenv


load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "gonbad-shams-secret-key")

DB_NAME = "database.db"

GAPGPT_API_KEY = os.environ.get("GAPGPT_API_KEY", "")
GAPGPT_BASE_URL = "https://api.gapgpt.app/v1"

client = OpenAI(
    api_key=GAPGPT_API_KEY,
    base_url=GAPGPT_BASE_URL
)


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            raw_text TEXT,
            analysis TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.commit()
    conn.close()


init_db()


SYSTEM_PROMPT = """
تو دستیار هوشمند مدیریت عملیات و ساخت شرکت «گنبد شمس» هستی.

گزارش متنی دریافتی را تحلیل کن و خروجی را دقیق، مرتب و در این ساختار بنویس:

۱. دسته‌بندی:
یکی از این موارد را انتخاب کن:
- خرید و هزینه‌ها
- انبار و مصرف
- تولید و کارگاه
- فروش و مشتری
- وظایف و برنامه‌ریزی

۲. اطلاعات استخراج‌شده:
[شخص گزارش‌دهنده | موضوع | پروژه/محصول | مقادیر یا مبالغ | اقدام بعدی | مسئول پیگیری]

۳. اقدام فوری:
کاری که باید در اولین فرصت انجام شود.

۴. اولویت:
فوری / بالا / متوسط / پایین

۵. مسئول پیگیری:
نام شخص یا اشخاص مسئول.

۶. موارد نامشخص:
اطلاعاتی که در گزارش وجود ندارد یا نیاز به بررسی دارد.

اگر گزارش ناقص است، حدس بی‌دلیل نزن و موارد نامشخص را صریح بنویس.
"""


def analyze_and_store_report(sender, raw_text):
    if not GAPGPT_API_KEY:
        raise RuntimeError("متغیر محیطی GAPGPT_API_KEY در تنظیمات سرویس وجود ندارد.")

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": (
                    f"گزارش‌دهنده: {sender}\n"
                    f"متن گزارش: {raw_text}"
                )
            }
        ],
        temperature=0.3
    )

    analysis = response.choices[0].message.content

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO reports (sender, raw_text, analysis)
        VALUES (?, ?, ?)
        """,
        (sender, raw_text, analysis)
    )
    conn.commit()
    conn.close()

    return analysis


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        sender = request.form.get("sender", "نامشخص").strip()
        raw_text = request.form.get("raw_text", "").strip()

        if not sender:
            sender = "نامشخص"

        if not raw_text:
            flash("متن گزارش نمی‌تواند خالی باشد.", "error")
            return redirect(url_for("index"))

        try:
            analyze_and_store_report(sender, raw_text)
            flash("گزارش با موفقیت ثبت و تحلیل شد.", "success")
        except Exception as e:
            flash(f"خطا در ارتباط با هوش مصنوعی: {str(e)}", "error")

        return redirect(url_for("index"))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reports ORDER BY id DESC")
    reports = cursor.fetchall()
    conn.close()

    return render_template("index.html", reports=reports)


@app.route("/process_voice", methods=["POST"])
def process_voice():
    try:
        sender = request.form.get("sender", "نامشخص").strip()
        if not sender:
            sender = "نامشخص"

        audio_file = request.files.get("audio")
        if not audio_file or audio_file.filename == "":
            return jsonify({
                "ok": False,
                "message": "فایل صوتی دریافت نشد."
            }), 400

        if not GAPGPT_API_KEY:
            return jsonify({
                "ok": False,
                "message": "متغیر محیطی GAPGPT_API_KEY تنظیم نشده است."
            }), 500

        suffix = os.path.splitext(audio_file.filename)[1] or ".webm"
        temp_path = None

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_audio:
            temp_path = temp_audio.name
            audio_file.save(temp_path)

        try:
            with open(temp_path, "rb") as f:
                transcription = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f
                )
            raw_text = getattr(transcription, "text", "").strip()
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

        if not raw_text:
            return jsonify({
                "ok": False,
                "message": "تبدیل صوت به متن نتیجه‌ای برنگرداند."
            }), 500

        analysis = analyze_and_store_report(sender, raw_text)

        return jsonify({
            "ok": True,
            "message": "ویس با موفقیت پردازش شد.",
            "raw_text": raw_text,
            "analysis": analysis
        }), 200

    except Exception as e:
        return jsonify({
            "ok": False,
            "message": f"ارسال یا پردازش ویس انجام نشد: {str(e)}"
        }), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
