import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash
from openai import OpenAI

app = Flask(__name__)
app.secret_key = "gonbad-shams-secret-key"

# مسیر پایگاه داده
DB_NAME = "database.db"

# تنظیمات اتصال به GapGPT
GAPGPT_API_KEY = "sk-yAJzrlMABXk7zNcpSlccNkQ73iAiDseRNVTHeYTc8thLhfGA"
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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            raw_text TEXT,
            analysis TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

SYSTEM_PROMPT = """
تو دستیار هوشمند مدیریت عملیات و ساخت شرکت «گنبد شمس» هستی.
گزارش متنی دریافتی را تحلیل کن و خروجی را دقیق، مرتب و در این ساختار بنویس:

۱. دسته‌بندی: (یکی از موارد: خرید و هزینه‌ها / انبار و مصرف / تولید و کارگاه / فروش و مشتری / وظایف و برنامه‌ریزی)
۲. استخراج داده: [شخص گزارش‌دهنده | موضوع | پروژه/محصول | مقادیر یا مبالغ | اقدام بعدی | مسئول پیگیری]
۳. اقدام فوری: (کاری که باید الان انجام شود)
۴. مسئول پیگیری: (نام مسئول پیگیری)
"""

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        sender = request.form.get("sender", "نامشخص").strip()
        raw_text = request.form.get("raw_text", "").strip()

        if not raw_text:
            flash("متن گزارش نمی‌تواند خالی باشد.", "error")
            return redirect(url_for("index"))

        try:
            # ارسال متن به مدل GapGPT برای تحلیل
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"گزارش‌دهنده: {sender}\nمتن گزارش: {raw_text}"}
                ],
                temperature=0.3
            )
            analysis = response.choices[0].message.content

            # ذخیره در دیتابیس
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO reports (sender, raw_text, analysis) VALUES (?, ?, ?)",
                (sender, raw_text, analysis)
            )
            conn.commit()
            conn.close()

            flash("گزارش با موفقیت ثبت و تحلیل شد.", "success")
        except Exception as e:
            flash(f"خطا در ارتباط با هوش مصنوعی: {str(e)}", "error")

        return redirect(url_for("index"))

    # نمایش لیست گزارش‌ها
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reports ORDER BY id DESC")
    reports = cursor.fetchall()
    conn.close()

    return render_template("index.html", reports=reports)

if __name__ == "__main__":
    app.run(debug=True)
