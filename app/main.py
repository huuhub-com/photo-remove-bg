#Deploy
#gcloud run deploy huuhub-bg-service --source . --region asia-northeast1 --platform managed --service-account=105679435990-compute@developer.gserviceaccount.com --no-allow-unauthenticated --cpu=2 --memory=2Gi --port=8080 --timeout=300

#TEST
#source .venv/bin/activate
#uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import Response
from PIL import Image, ImageFilter
from io import BytesIO

app = FastAPI()

@app.post("/remove-bg")
async def remove_bg(
    file: UploadFile = File(...),
    mode: str = "white",   # ★ デフォルトを white に
    size: int = 1024       # ★ TikTok 用の 1024x1024
):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="画像ファイルを送ってください。")

    raw = await file.read()
    img = Image.open(BytesIO(raw)).convert("RGBA")

    w, h = img.size
    pix = img.load()

    # =========================
    # 1. クロマキー判定（グリーンバックを透明化）
    # =========================
    GREEN_THR = 120
    GREEN_RATIO = 1.35

    # 中間バッファ（マスク）
    mask = Image.new("L", (w, h), 0)
    mask_pix = mask.load()

    for y in range(h):
        for x in range(w):
            r, g, b, a = pix[x, y]

            is_green = (
                g > GREEN_THR and
                g > r * GREEN_RATIO and
                g > b * GREEN_RATIO
            )

            if is_green:
                pix[x, y] = (0, 0, 0, 0)
                mask_pix[x, y] = 0
            else:
                pix[x, y] = (r, g, b, 255)
                mask_pix[x, y] = 255

    # =========================
    # 2. グリーンスピル除去（縁のシアンっぽい色を弱める）
    # =========================
    SPILL_RATIO = 1.05  # どれくらい「G が強かったら」対象にするか
    G_SCALE     = 0.50  # G をどれだけ削るか（小さいほど強い）
    RB_SCALE    = 1.15  # R/B をどれだけ持ち上げるか

    for y in range(h):
        for x in range(w):
            r, g, b, a = pix[x, y]
            if a > 0:
                if g > r * SPILL_RATIO and g > b * SPILL_RATIO:
                    new_g = int(g * G_SCALE)
                    new_r = min(255, int(r * RB_SCALE))
                    new_b = min(255, int(b * RB_SCALE))
                    pix[x, y] = (new_r, new_g, new_b, a)

    # =========================
    # 3. 縁の 1px 収縮（フリンジ削除）
    # =========================
    mask = mask.filter(ImageFilter.MinFilter(3))  # もっと削りたければ 5 に
    mask_pix = mask.load()  # ★ filter 後に load し直すのを忘れない

    # mask を α に反映
    for y in range(h):
        for x in range(w):
            r, g, b, _ = pix[x, y]
            a = mask_pix[x, y]
            pix[x, y] = (r, g, b, a)

    # =========================
    # 4. トリミング（外側の余白をカット）
    # =========================
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)

    # =========================
    # 5-A. 透明PNGを返す（確認用・特殊用途）
    # =========================
    if mode == "transparent":
        buff = BytesIO()
        img.save(buff, format="PNG")
        return Response(buff.getvalue(), media_type="image/png")

    # =========================
    # 5-B. 白背景 1024x1024 にレイアウト（TikTok 用）
    # =========================
    # ニュートラルホワイト背景（255,255,255）
    bg = Image.new("RGB", (size, size), (255, 255, 255))

    iw, ih = img.size
    ratio = min(size / iw, size / ih)  # 長辺がちょうど収まるように
    nw, nh = int(iw * ratio), int(ih * ratio)

    resized = img.resize((nw, nh), Image.LANCZOS)

    # 中央配置
    offset_x = (size - nw) // 2
    offset_y = (size - nh) // 2
    bg.paste(resized, (offset_x, offset_y), resized)

    buff = BytesIO()
    bg.save(buff, format="PNG")
    return Response(buff.getvalue(), media_type="image/png")
