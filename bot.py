import os
import time
import sqlite3
import hashlib
import logging

import requests

# ================== الإعدادات ==================
CONFIG = {
    # كل استعلام يُرسل إلى Google مرة واحدة في كل دورة
    "queries": [
        "SOC analyst remote",
        "cybersecurity analyst remote job",
    ],
    "date_restrict": "d1",        # d1 = آخر يوم، w1 = آخر أسبوع
    "results_per_query": 10,      # الحد الأقصى 10 لكل استعلام
    "check_every_seconds": 3600,  # كل ساعة (حافظ على حصة 100 استعلام يومياً)
    "send_cv": True,
    "cv_path": "cv.pdf",
    "cover_letter_path": "cover_letter.txt",
}

GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
GOOGLE_CX = os.environ["GOOGLE_CX"]
TG_TOKEN = os.environ["TG_TOKEN"]
TG_CHAT_ID = os.environ["TG_CHAT_ID"]
TG_API = f"https://api.telegram.org/bot{TG_TOKEN}"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ================== قاعدة البيانات (منع التكرار) ==================
db = sqlite3.connect("seen.db", check_same_thread=False)
db.execute("CREATE TABLE IF NOT EXISTS seen (id TEXT PRIMARY KEY)")


def make_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()


def is_new(job_id: str) -> bool:
    return db.execute("SELECT 1 FROM seen WHERE id=?", (job_id,)).fetchone() is None


def mark_seen(job_id: str):
    db.execute("INSERT OR IGNORE INTO seen (id) VALUES (?)", (job_id,))
    db.commit()


# ================== البحث في Google ==================
def google_search(query: str) -> list[dict]:
    r = requests.get(
        "https://www.googleapis.com/customsearch/v1",
        params={
            "key": GOOGLE_API_KEY,
            "cx": GOOGLE_CX,
            "q": query,
            "dateRestrict": CONFIG["date_restrict"],
            "num": CONFIG["results_per_query"],
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json().get("items", [])


# ================== تلغرام ==================
def tg_send_message(text: str):
    requests.post(
        f"{TG_API}/sendMessage",
        json={"chat_id": TG_CHAT_ID, "text": text, "disable_web_page_preview": True},
        timeout=20,
    )


def tg_send_cv(caption: str):
    with open(CONFIG["cv_path"], "rb") as f:
        requests.post(
            f"{TG_API}/sendDocument",
            data={"chat_id": TG_CHAT_ID, "caption": caption[:1000]},
            files={"document": f},
            timeout=60,
        )


def build_cover_letter(title: str, site: str) -> str:
    with open(CONFIG["cover_letter_path"], encoding="utf-8") as f:
        template = f.read()
    return template.format(title=title, company=site)


def notify(item: dict):
    title = item.get("title", "")
    link = item["link"]
    site = item.get("displayLink", "")
    snippet = item.get("snippet", "")

    msg = (
        f"🆕 نتيجة جديدة\n"
        f"📌 {title}\n"
        f"🌐 {site}\n"
        f"📝 {snippet}\n"
        f"🔗 {link}\n\n"
        f"--- رسالة التقديم ---\n{build_cover_letter(title, site)}"
    )
    tg_send_message(msg)
    if CONFIG["send_cv"]:
        tg_send_cv(f"CV - {title}")


# ================== الحلقة الرئيسية ==================
def run_once():
    for query in CONFIG["queries"]:
        try:
            items = google_search(query)
        except Exception as e:
            logging.warning("فشل البحث عن %r: %s", query, e)
            continue

        for item in items:
            link = item.get("link")
            if not link:
                continue
            job_id = make_id(link)
            if not is_new(job_id):
                continue
            try:
                notify(item)
                logging.info("أُرسلت: %s", item.get("title", link))
            except Exception as e:
                logging.error("فشل الإرسال: %s", e)
                continue  # لا نحفظها ليُعاد المحاولة لاحقاً
            mark_seen(job_id)
            time.sleep(1)  # تجنب حد تلغرام


def main():
    logging.info("البوت بدأ العمل")
    while True:
        run_once()
        time.sleep(CONFIG["check_every_seconds"])


if __name__ == "__main__":
    main()