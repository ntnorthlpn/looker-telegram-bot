"""
screenshot_to_line.py
=====================
ถ่ายภาพหน้าเว็บ Looker Studio แล้วส่งไปยัง Telegram Group
รองรับการตั้งเวลาทำงานอัตโนมัติ

ติดตั้ง dependencies:
    pip install playwright requests pillow schedule cloudinary
    playwright install chromium
"""

import asyncio
import os
import sys
import requests 
import cloudinary
import cloudinary.uploader
import cloudinary.api
from datetime import datetime
from pathlib import Path
from PIL import Image
from playwright.async_api import async_playwright

# ============================================================
#  CONFIG — แก้ค่าตรงนี้
# ============================================================
TARGET_URL               = "https://datastudio.google.com/reporting/1483b6e3-3477-4906-8966-ec276423ec27/page/p_u1s42afhzd"
SCREENSHOT_PATH          = "looker_report.png"

# ============================================================
#  LINE CONFIG (ปิดใช้งานชั่วคราว)
# ============================================================
# LINE_CHANNEL_ACCESS_TOKEN = "C7mf18W4AQlMspvkGiLHOYm1PAEXNJmslF5586aXwsXV/JUc/4w0Xws1dLMGfPanAVTbHnlWeJseUCuUiUEBCnU0xJ2UyadJh3r1DKc9NLinmCHKA5+UAnxzO7ZQ1bYVIF43IJ7VWrD582ZZjZI62AdB04t89/1O/w1cDnyilFU="
# LINE_GROUP_ID             = "Ca428ccd489699f5fe31b71dd00284aca"

# ============================================================
#  TELEGRAM CONFIG
# ============================================================
TELEGRAM_BOT_TOKEN        = ""          # จาก @BotFather เช่น 123456:ABC-DEF...
TELEGRAM_CHAT_ID          = ""            # Group/Channel ID เช่น -1001234567890

# ============================================================
#  CLOUDINARY CONFIG — จาก https://cloudinary.com (สมัครฟรี)
# ============================================================
CLOUDINARY_CLOUD_NAME    = ""
CLOUDINARY_API_KEY       = ""
CLOUDINARY_API_SECRET    = ""

# ตั้งค่า Cloudinary
cloudinary.config(
    cloud_name = CLOUDINARY_CLOUD_NAME,
    api_key    = CLOUDINARY_API_KEY,
    api_secret = CLOUDINARY_API_SECRET,
    secure     = True,
)

VIEWPORT_WIDTH            = 1280
VIEWPORT_HEIGHT           = 1200
WAIT_SECONDS              = 15      # วินาทีที่รอให้ chart โหลด (เพิ่มถ้ายังไม่ครบ)
MAX_IMAGE_WIDTH           = 1280     # resize ถ้ากว้างเกินนี้
JPEG_QUALITY              = 85       # คุณภาพภาพ 1-100


# ============================================================
#  STEP 1 : ถ่าย Screenshot
# ============================================================
async def take_screenshot(
    url: str,
    output_path: str,
    width: int  = VIEWPORT_WIDTH,
    height: int = VIEWPORT_HEIGHT,
    wait_sec: int = WAIT_SECONDS,
) -> str:
    """
    เปิดเบราว์เซอร์ ไปยัง url แล้วถ่ายภาพ
    คืนค่า path ของไฟล์ภาพที่บันทึก
    """
    print(f"[1/4] 🌐 กำลังเปิดหน้า: {url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=1,
        )
        page = await context.new_page()

        # ปิด dialog ที่อาจโผล่มา
        page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        except Exception as e:
            print(f"    ⚠️  networkidle timeout ({e}) — ถ่ายภาพต่อเลย")

        # รอให้ chart render เสร็จ
        print(f"[1/4] ⏳ รอ chart โหลด {wait_sec} วินาที...")
        await page.wait_for_timeout(wait_sec * 1000)

        # พยายามรอ element จริง (ไม่บังคับ)
        for selector in ["canvas", "table", "[data-testid]", ".reportPage"]:
            try:
                await page.wait_for_selector(selector, timeout=5_000)
                print(f"    ✅ พบ element: {selector}")
                await page.wait_for_timeout(2_000)
                break
            except Exception:
                pass

          
        # แทนที่ content_size เดิมด้วยนี้ 
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1000)

        # === DEBUG: วัดขนาดจริงก่อนถ่ายภาพ ===
        metrics = await page.evaluate("""() => ({
            scrollWidth:   document.documentElement.scrollWidth,
            scrollHeight:  document.documentElement.scrollHeight,
            clientWidth:   document.documentElement.clientWidth,
            viewportWidth: window.innerWidth,
            bodyWidth:     document.body.scrollWidth,
        })""")
        print(f"    📐 scrollWidth  (DOM กว้างจริง) : {metrics['scrollWidth']}px")
        print(f"    📐 scrollHeight (DOM สูงจริง)   : {metrics['scrollHeight']}px")
        print(f"    📐 clientWidth  (พื้นที่แสดงผล): {metrics['clientWidth']}px")
        print(f"    📐 viewportWidth (window)       : {metrics['viewportWidth']}px")
        print(f"    📐 bodyWidth                    : {metrics['bodyWidth']}px")
        
        
        await page.screenshot(
            path=output_path,
            full_page=True,
        )

        # Crop ตัดส่วนหัวออก
        from PIL import Image as _CropImg
        with _CropImg.open(output_path) as _im:
            w, h = _im.size
            cropped = _im.crop((0, 120, w, h))  # ตัด จากด้านบน
            cropped.save(output_path)
 

        # === DEBUG: ตรวจขนาดไฟล์ที่ได้จริง ===
        from PIL import Image as _Img
        with _Img.open(output_path) as _im:
            print(f"    📸 ภาพที่ได้จริง: {_im.size[0]}×{_im.size[1]}px")


        await browser.close()

    print(f"[1/4] ✅ บันทึกภาพแล้ว: {output_path}")
    return output_path


# ============================================================
#  STEP 2 : Resize ภาพ (ลดขนาดไฟล์ก่อนส่ง)
# ============================================================
def resize_image(input_path: str, max_width: int = MAX_IMAGE_WIDTH, quality: int = JPEG_QUALITY) -> str:
    """
    ย่อขนาดภาพถ้ากว้างเกิน max_width แล้วแปลงเป็น JPEG
    คืนค่า path ของไฟล์ใหม่ (.jpg)
    """
    print(f"[2/4] 🖼️  ปรับขนาดภาพ...")
    img  = Image.open(input_path).convert("RGB")
    w, h = img.size

    if w > max_width:
        ratio    = max_width / w
        new_size = (max_width, int(h * ratio))
        img      = img.resize(new_size, Image.LANCZOS)
        print(f"    📏 Resize: {w}×{h} → {new_size[0]}×{new_size[1]}")
    else:
        print(f"    📏 ขนาดเดิม: {w}×{h} (ไม่ต้อง resize)")

    out_path = str(Path(input_path).with_suffix(".jpg"))
    img.save(out_path, "JPEG", quality=quality, optimize=True)
    size_kb  = os.path.getsize(out_path) / 1024
    print(f"[2/4] ✅ บันทึก JPEG: {out_path} ({size_kb:.1f} KB)")
    return out_path


# ============================================================
#  STEP 3 : Upload รูปไปยัง Cloudinary เพื่อรับ Public URL
# ============================================================
def upload_to_cloudinary(image_path: str) -> str:
    """
    Upload ภาพไปยัง Cloudinary แล้วคืน public URL
    """
    print(f"[3/4] ☁️  กำลัง upload ภาพไปยัง Cloudinary...")

    
    public_id = "looker_reports/report_latest_SectionB"
    result = cloudinary.uploader.upload(
        image_path,
        public_id     = public_id,
        overwrite     = True,
        resource_type = "image",
    )

    url = result["secure_url"]
    print(f"[3/4] ✅ URL: {url}")
    return url

# ============================================================
#  STEP 3.5 : ตรวจสอบ Cloudinary Usage
# ============================================================
 

def check_cloudinary_usage():
    result = cloudinary.api.usage()

    storage_mb  = result["storage"]["usage"]   / (1024**2)
    bandwidth_mb = result["bandwidth"]["usage"] / (1024**2)
    objects      = result["objects"]["usage"]

    credits_used  = result["credits"]["usage"]
    credits_limit = result["credits"]["limit"]
    credits_pct   = result["credits"]["used_percent"]

    print(f"    ☁️  Storage  : {storage_mb:.1f} MB")
    print(f"    ☁️  Bandwidth: {bandwidth_mb:.1f} MB")
    print(f"    ☁️  Objects  : {objects} files")
    print(f"    ☁️  Credits  : {credits_used:.2f} / {credits_limit:.0f} ({credits_pct:.2f}%)")    
     
# ============================================================
#  STEP 4 : ส่งภาพไปยัง Telegram
# ============================================================
def send_image_to_telegram(
    image_url: str,
    chat_id: str  = TELEGRAM_CHAT_ID,
    token: str    = TELEGRAM_BOT_TOKEN,
    caption: str  = None,
) -> bool:
    """
    ส่งภาพ (และข้อความ caption) ไปยัง Telegram Group/Channel
    ใช้ sendPhoto API ส่งผ่าน URL โดยตรง
    """
    print(f"[4/4] 📨 กำลังส่งไปยัง Telegram chat_id: {chat_id}")

    if token == "YOUR_BOT_TOKEN":
        raise ValueError("❌ กรุณาใส่ TELEGRAM_BOT_TOKEN ก่อนใช้งาน")
    if chat_id == "YOUR_CHAT_ID":
        raise ValueError("❌ กรุณาใส่ TELEGRAM_CHAT_ID ก่อนใช้งาน")

    url     = f"https://api.telegram.org/bot{token}/sendPhoto"
    payload = {
        "chat_id":   chat_id,
        "photo":     image_url,
        "caption":   caption or "",
        "parse_mode": "HTML",   # รองรับ <b>, <i>, <code> ใน caption
    }

    response = requests.post(url, json=payload, timeout=30)

    if response.status_code == 200:
        print(f"[4/4] ✅ ส่ง Telegram สำเร็จ!")
        return True
    else:
        print(f"[4/4] ❌ ส่ง Telegram ไม่สำเร็จ: {response.status_code} {response.text}")
        return False


# ============================================================
#  (ปิดใช้งาน) STEP 4 เดิม : ส่งภาพไปยัง LINE Group
# ============================================================
# def send_image_to_line(
#     image_url: str,
#     group_id: str  = LINE_GROUP_ID,
#     token: str     = LINE_CHANNEL_ACCESS_TOKEN,
#     caption: str   = None,
# ) -> bool:
#     print(f"[4/4] 📨 กำลังส่งไปยัง LINE Group: {group_id}")
#     headers = {
#         "Authorization": f"Bearer {token}",
#         "Content-Type":  "application/json",
#     }
#     messages = []
#     if caption:
#         messages.append({"type": "text", "text": caption})
#     messages.append({
#         "type":                "image",
#         "originalContentUrl":  image_url,
#         "previewImageUrl":     image_url,
#     })
#     payload  = {"to": group_id, "messages": messages}
#     response = requests.post(
#         "https://api.line.me/v2/bot/message/push",
#         headers=headers,
#         json=payload,
#         timeout=30,
#     )
#     if response.status_code == 200:
#         print(f"[4/4] ✅ ส่ง LINE สำเร็จ!")
#         return True
#     else:
#         print(f"[4/4] ❌ ส่ง LINE ไม่สำเร็จ: {response.status_code} {response.text}")
#         return False


# ============================================================
#  MAIN FLOW
# ============================================================
async def run():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 55)
    print(f"  📸 Screenshot → Telegram  |  {timestamp}")
    print("=" * 55)

    try:
        # 1. ถ่ายภาพ
        png_path = await take_screenshot(TARGET_URL, SCREENSHOT_PATH)

        # 2. Resize / แปลง JPEG
        jpg_path = resize_image(png_path)

        # 3. Upload รับ URL
        image_url = upload_to_cloudinary(jpg_path)
        check_cloudinary_usage()
         
        # 4. ส่ง Telegram พร้อม caption วันเวลา
        caption = f"📊 <b>รายงานเหตุเสีย Section B</b>\n🕐 {timestamp}"
        send_image_to_telegram(image_url, caption=caption)

        # (ปิดใช้งาน) ส่ง LINE
        # send_image_to_line(image_url, caption=caption)

    except Exception as e:
        print(f"\n❌ เกิดข้อผิดพลาด: {e}")
        sys.exit(1)

    finally:
        # ลบไฟล์ชั่วคราว
        for f in [SCREENSHOT_PATH, SCREENSHOT_PATH.replace(".png", ".jpg")]:
            if os.path.exists(f):
                os.remove(f)
                print(f"🗑️  ลบไฟล์ชั่วคราว: {f}")

    print("\n✅ เสร็จสิ้น!")


# ============================================================
#  ตั้งเวลาอัตโนมัติ (Optional)
# ============================================================
def run_scheduler():
    """
    รันแบบมี schedule — แก้เวลาได้ตามต้องการ
    รันด้วย:  python screenshot_to_line.py schedule
    """
    import schedule, time

    def job():
        asyncio.run(run())

    # ตัวอย่าง: ส่งทุกวัน 8:00 และ 16:00
    schedule.every().day.at("08:00").do(job)
    schedule.every().day.at("16:00").do(job)

    # หรือทุก 30 นาที:
    # schedule.every(30).minutes.do(job)

    print("⏰ Scheduler เริ่มทำงาน... (Ctrl+C เพื่อหยุด)")
    while True:
        schedule.run_pending()
        time.sleep(30)


# ============================================================
#  ENTRY POINT
# ============================================================
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "schedule":
        run_scheduler()
    else:
        asyncio.run(run())