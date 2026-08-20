import logging
import os
import sqlite3
import tempfile
import traceback

from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from openai import OpenAI
from werkzeug.utils import secure_filename


load_dotenv()


# --------------------------------------------------
# Logging
# --------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

logger = logging.getLogger("gonbadapp")


# --------------------------------------------------
# Flask and API configuration
# --------------------------------------------------

app = Flask(__name__)
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "gonbad-shams-secret-key"
)

DB_NAME = "database.db"

GAPGPT_API_KEY = os.environ.get("GAPGPT_API_KEY", "")
GAPGPT_BASE_URL = "https://api.gapgpt.app/v1"

client = OpenAI(
    api_key=GAPGPT_API_KEY,
    base_url=GAPGPT_BASE_URL
)


# --------------------------------------------------
# Database
# --------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    logger.info("Database initialization started")

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

    logger.info("Database initialization completed")


init_db()


# --------------------------------------------------
# AI analysis configuration
# --------------------------------------------------

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
    """
    متن گزارش را تحلیل می‌کند و نتیجه را در SQLite ذخیره می‌کند.
    """
    logger.info(
        "Analysis started: sender=%s, text_length=%d",
        sender,
        len(raw_text or "")
    )

    if not GAPGPT_API_KEY:
        logger.error("Analysis stopped: GAPGPT_API_KEY is missing")
        raise RuntimeError("GAPGPT_API_KEY_MISSING")

    try:
        logger.info("Sending analysis request to AI service")

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

        logger.info("Analysis response received from AI service")

        analysis = response.choices[0].message.content

        if not analysis:
            logger.error("Analysis response was empty")
            raise RuntimeError("AI_EMPTY_ANALYSIS")

    except Exception:
        logger.exception("AI analysis request failed")
        raise

    conn = None

    try:
        logger.info("Database insert started")

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

        logger.info("Database insert completed")

    except Exception:
        logger.exception("Database insert failed")
        raise

    finally:
        if conn is not None:
            conn.close()
            logger.info("Database connection closed")

    return analysis


# --------------------------------------------------
# Text report route
# --------------------------------------------------

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

        except Exception:
            logger.exception("Text report processing failed")
            flash(
                "در پردازش گزارش متنی خطایی رخ داد. جزئیات در Logs قابل مشاهده است.",
                "error"
            )

        return redirect(url_for("index"))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reports ORDER BY id DESC")
    reports = cursor.fetchall()
    conn.close()

    return render_template("index.html", reports=reports)


# --------------------------------------------------
# Voice report route
# --------------------------------------------------

@app.route("/process_voice", methods=["POST"])
def process_voice():
    stage = "validation"
    temp_path = None

    logger.info("Voice request received: method=%s, path=%s", request.method, request.path)

    try:
        # ------------------------------
        # Validation
        # ------------------------------
        stage = "validation"

        sender = request.form.get("sender", "نامشخص").strip()
        if not sender:
            sender = "نامشخص"

        logger.info("Voice validation started: sender=%s", sender)

        audio_file = request.files.get("audio")

        if audio_file is None:
            logger.error("Validation failed: audio field is missing")

            return jsonify({
                "ok": False,
                "stage": "validation",
                "message": "فیلد فایل صوتی به سرور ارسال نشده است."
            }), 400

        original_filename = audio_file.filename or ""
        safe_filename = secure_filename(original_filename)

        if not original_filename.strip():
            logger.error("Validation failed: audio filename is empty")

            return jsonify({
                "ok": False,
                "stage": "validation",
                "message": "نام فایل صوتی خالی است."
            }), 400

        content_type = audio_file.content_type or "نامشخص"

        allowed_mime_types = {
            "audio/webm",
            "audio/ogg",
            "audio/wav",
            "audio/wave",
            "audio/x-wav",
            "audio/mpeg",
            "audio/mp4",
            "video/webm"
        }

        logger.info(
            "Audio metadata: safe_filename=%s, mime_type=%s",
            safe_filename or "unknown",
            content_type
        )

        if content_type not in allowed_mime_types:
            logger.error(
                "Validation failed: unsupported MIME type=%s",
                content_type
            )

            return jsonify({
                "ok": False,
                "stage": "validation",
                "message": (
                    "نوع فایل صوتی پشتیبانی نمی‌شود. "
                    "لطفاً با مرورگر دیگری دوباره ضبط کنید."
                )
            }), 400

        if not GAPGPT_API_KEY:
            logger.error("Validation failed: GAPGPT_API_KEY is missing")

            return jsonify({
                "ok": False,
                "stage": "validation",
                "message": (
                    "کلید اتصال سرویس هوش مصنوعی در تنظیمات سرور وجود ندارد."
                )
            }), 500

        # ------------------------------
        # Temporary upload
        # ------------------------------
        stage = "upload"

        suffix = os.path.splitext(safe_filename)[1].lower()

        if not suffix:
            suffix = ".webm"

        logger.info(
            "Temporary audio save started: suffix=%s",
            suffix
        )

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix
        ) as temp_audio:
            temp_path = temp_audio.name
            audio_file.save(temp_path)

        file_size = os.path.getsize(temp_path)

        logger.info(
            "Temporary audio save completed: size_bytes=%d",
            file_size
        )

        if file_size <= 0:
            logger.error("Upload failed: temporary audio file is empty")

            return jsonify({
                "ok": False,
                "stage": "upload",
                "message": "فایل صوتی خالی است و قابل پردازش نیست."
            }), 400

        # ------------------------------
        # Transcription
        # ------------------------------
        stage = "transcription"

        logger.info(
            "Transcription started: model=whisper-1, size_bytes=%d",
            file_size
        )

        try:
            with open(temp_path, "rb") as audio_stream:
                transcription = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_stream
                )

            logger.info("Transcription response received")

        except Exception:
            logger.exception(
                "Transcription failed. "
                "The AI provider may not support audio transcription, "
                "the model may be unavailable, or the request format may differ."
            )
            raise

        raw_text = getattr(transcription, "text", "").strip()

        logger.info(
            "Transcription text received: text_length=%d",
            len(raw_text)
        )

        if not raw_text:
            logger.error("Transcription failed: returned text is empty")

            return jsonify({
                "ok": False,
                "stage": "transcription",
                "message": (
                    "تبدیل صوت به متن انجام شد، اما متنی از سرویس دریافت نشد."
                )
            }), 502

        # ------------------------------
        # Analysis and database
        # ------------------------------
        stage = "analysis"

        logger.info("Voice report analysis started")

        analysis = analyze_and_store_report(sender, raw_text)

        logger.info("Voice report analysis and storage completed")

        return jsonify({
            "ok": True,
            "stage": "completed",
            "message": "ویس با موفقیت به متن تبدیل، تحلیل و ذخیره شد.",
            "raw_text": raw_text,
            "analysis": analysis
        }), 200

    except Exception as exc:
        logger.exception(
            "Voice processing failed at stage=%s, error_type=%s",
            stage,
            type(exc).__name__
        )

        error_messages = {
            "validation": "اطلاعات فایل صوتی معتبر نیست.",
            "upload": "ذخیره موقت فایل صوتی روی سرور انجام نشد.",
            "transcription": (
                "خطا در تبدیل صوت به متن. "
                "ممکن است سرویس GapGPT از تبدیل صوت یا مدل whisper-1 پشتیبانی نکند."
            ),
            "analysis": "تبدیل صوت انجام شد، اما تحلیل گزارش با خطا مواجه شد.",
            "database": "گزارش تحلیل شد، اما ذخیره آن در پایگاه داده انجام نشد.",
            "unknown": "خطای نامشخصی در پردازش ویس رخ داد."
        }

        safe_message = error_messages.get(
            stage,
            error_messages["unknown"]
        )

        return jsonify({
            "ok": False,
            "stage": stage,
            "message": safe_message,
            "error_type": type(exc).__name__
        }), 500

    finally:
        # فایل صوتی نباید روی سرور باقی بماند.
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.info("Temporary audio file deleted")
            except Exception:
                logger.exception("Temporary audio cleanup failed")


# --------------------------------------------------
# Local development
# --------------------------------------------------

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
