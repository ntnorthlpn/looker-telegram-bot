"""
screenshot_to_telegram.py
=========================
ถ่ายภาพหน้าเว็บ Looker Studio แล้วส่งไปยัง Telegram Group
รองรับการตั้งเวลาทำงานอัตโนมัติ

ติดตั้ง dependencies:
    pip install playwright requests pillow schedule cloudinary
    playwright install chromium

Secret Keys เก็บใน GitHub Secrets — ไม่เขียนใน code
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
#  CONFIG — รับค่าจาก Environment Variables (GitHub Secrets)
#  ไม่มีค่าจริงใน code เลย
# ============================================================
TARGET_URLS = [
    os.environ["TARGET_URL_1"],
    os.environ["TARGET_URL_2"],
    os.environ["TARGET_URL_3"],
]
SCREENSHOT_PATH = "looker_report.png"

# ============================================================
#  TELEGRAM — รับจาก GitHub Secrets
# ============================================================
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]

# ============================================================
#  CLOUDINARY — รับจาก GitHub Secrets
# ============================================================
CLOUDINARY_CLOUD_NAME = os.environ["CLOUDINARY_CLOUD_NAME"]
CLOUDINARY_API_KEY    = os.environ["CLOUDINARY_API_KEY"]
CLOUDINARY_API_SECRET = os.environ["CLOUDINARY_API_SECRET"]

# ตั้งค่า Cloudinary
cloudinary.config(
    cloud_name = CLOUDINARY_CLOUD_NAME,
    api_key    = CLOUDINARY_API_KEY,
    api_secret = CLOUDINARY_API_SECRET,
    secure     = True,
)

VIEWPORT_WIDTH  = 1280
VIEWPORT_HEIGHT = 1200
WAIT_SECONDS    = 15
MAX_IMAGE_WIDTH = 1280
JPEG_QUALITY    = 85


# ============================================================
#  STEP 1 : ถ่าย Screenshot
# ============================================================
async def take_screenshot(
    url: str,
    output_path: str,
    width: int    = VIEWPORT_WIDTH,
    height: int   = VIEWPORT_HEIGHT,
    wait_sec: int = WAIT_SECONDS,
) -> str:
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
        page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        except Exception as e:
            print(f"    ⚠️  networkidle timeout ({e}) — ถ่ายภาพต่อเลย")

        print(f"[1/4] ⏳ รอ chart โหลด {wait_sec} วินาที...")
        await page.wait_for_timeout(wait_sec * 1000)

        for selector in ["canvas", "table", "[data-testid]", ".reportPage"]:
            try:
                await page.wait_for_selector(selector, timeout=5_000)
                print(f"    ✅ พบ element: {selector}")
                await page.wait_for_timeout(2_000)
                break
            except Exception:
                pass

        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1000)

        metrics = await page.evaluate("""() => ({
            scrollWidth:   document.documentElement.scrollWidth,
            scrollHeight:  document.documentElement.scrollHeight,
            clientWidth:   document.documentElement.clientWidth,
            viewportWidth: window.innerWidth,
            bodyWidth:     document.body.scrollWidth,
        })""")
        print(f"    📐 scrollWidth  : {metrics['scrollWidth']}px")
        print(f"    📐 scrollHeight : {metrics['scrollHeight']}px")
        print(f"    📐 clientWidth  : {metrics['clientWidth']}px")
        print(f"    📐 viewportWidth: {metrics['viewportWidth']}px")
        print(f"    📐 bodyWidth    : {metrics['bodyWidth']}px")

        await page.screenshot(path=output_path, full_page=True)

        # Crop ตัดส่วนหัวออก 120px
        from PIL import Image as _CropImg
        with _CropImg.open(output_path) as _im:
            w, h = _im.size
            cropped = _im.crop((0, 120, w, h))
            cropped.save(output_path)

        from PIL import Image as _Img
        with _Img.open(output_path) as _im:
            print(f"    📸 ภาพที่ได้จริง: {_im.size[0]}×{_im.size[1]}px")

        await browser.close()

    print(f"[1/4] ✅ บันทึกภาพแล้ว: {output_path}")
    return output_path


# ============================================================
#  STEP 2 : Resize ภาพ
# ============================================================
def resize_image(input_path: str, max_width: int = MAX_IMAGE_WIDTH, quality: int = JPEG_QUALITY) -> str:
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
#  STEP 3 : Upload ไปยัง Cloudinary
# ============================================================
def upload_to_cloudinary(image_path: str, public_id: str = "looker_reports/report_latest_SectionB") -> str:
    """
    Upload ภาพไปยัง Cloudinary แล้วคืน public URL
    """
    print(f"[3/4] ☁️  กำลัง upload ภาพไปยัง Cloudinary...")

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

    storage_mb   = result["storage"]["usage"]   / (1024**2)
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
    chat_id: str = TELEGRAM_CHAT_ID,
    token: str   = TELEGRAM_BOT_TOKEN,
    caption: str = None,
) -> bool:
    print(f"[4/4] 📨 กำลังส่งไปยัง Telegram chat_id: {chat_id}")

    url     = f"https://api.telegram.org/bot{token}/sendPhoto"
    payload = {
        "chat_id":    chat_id,
        "photo":      image_url,
        "caption":    caption or "",
        "parse_mode": "HTML",
    }

    response = requests.post(url, json=payload, timeout=30)

    if response.status_code == 200:
        print(f"[4/4] ✅ ส่ง Telegram สำเร็จ!")
        return True
    else:
        print(f"[4/4] ❌ ส่ง Telegram ไม่สำเร็จ: {response.status_code} {response.text}")
        return False
# ============================================================
#  STEP 4b : ส่ง 3 ภาพพร้อมกันใน message เดียว (media group)
# ============================================================
def send_images_to_telegram(
    image_urls: list,
    chat_id: str = TELEGRAM_CHAT_ID,
    token: str   = TELEGRAM_BOT_TOKEN,
    caption: str = "",
) -> bool:
    print(f"[4/4] 📨 กำลังส่ง {len(image_urls)} ภาพไปยัง Telegram...")

    # สร้าง media group — ภาพแรกใส่ caption
    media = []
    for i, url in enumerate(image_urls):
        item = {"type": "photo", "media": url}
        if i == 0:
            item["caption"]    = caption
            item["parse_mode"] = "HTML"
        media.append(item)

    payload = {
        "chat_id": chat_id,
        "media":   media,
    }

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMediaGroup",
        json=payload,
        timeout=30,
    )

    if response.status_code == 200:
        print(f"[4/4] ✅ ส่ง Telegram สำเร็จ!")
        return True
    else:
        print(f"[4/4] ❌ ส่ง Telegram ไม่สำเร็จ: {response.status_code} {response.text}")
        return False

# ============================================================
#  MAIN FLOW
# ============================================================
async def run():
    
    from datetime import timezone, timedelta
    TZ_BANGKOK = timezone(timedelta(hours=7))
    timestamp = datetime.now(TZ_BANGKOK).strftime("%Y-%m-%d %H:%M:%S")
     
    print("=" * 55)
    print(f"  📸 Screenshot → Telegram  |  {timestamp}")
    print("=" * 55)

    temp_files = []

    try:
        image_urls = []

        # ดึง 3 URL พร้อมกัน
        for i, url in enumerate(TARGET_URLS, start=1):
            png_path = f"looker_report_{i}.png"
            temp_files.append(png_path)
            temp_files.append(png_path.replace(".png", ".jpg"))

            png_path  = await take_screenshot(url, png_path)
            jpg_path  = resize_image(png_path)
            image_url = upload_to_cloudinary(jpg_path, public_id=f"looker_reports/report_latest_{i}")
            image_urls.append(image_url)

        check_cloudinary_usage()

        # ส่ง 3 ภาพพร้อมกันใน message เดียว 
     
        caption = (
            f"📊 <b>รายงานสถานะงานเหตุเสีย</b>\n"
            f"📡 Broadband, โทรศัพท์ และ SP/PON/OLT DOWN\n"
            f"🔧 ที่อยู่ระหว่างดำเนินการ\n"
            f"🕐 {timestamp}"
        )
        
        # รับ chat_id หลายคน คั่นด้วย comma
        chat_ids_raw = os.environ.get("TELEGRAM_CHAT_ID", "")
        chat_ids = [c.strip() for c in chat_ids_raw.split(",") if c.strip()]
        
        # ส่งให้ทุก user
        for chat_id in chat_ids:
            send_images_to_telegram(image_urls, chat_id=chat_id, caption=caption)
            print(f"✅ ส่งให้ chat_id: {chat_id} สำเร็จ")
    except Exception as e:
        print(f"\n❌ เกิดข้อผิดพลาด: {e}")
        sys.exit(1)

    finally:
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)
                print(f"🗑️  ลบไฟล์ชั่วคราว: {f}")

    print("\n✅ เสร็จสิ้น!")
     


# ============================================================
#  ENTRY POINT
# ============================================================
if __name__ == "__main__":
    asyncio.run(run())
