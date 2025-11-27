#Deploy
#gcloud run deploy huuhub-bg-service --source . --region asia-northeast1 --platform managed --service-account=105679435990-compute@developer.gserviceaccount.com --no-allow-unauthenticated --cpu=2 --memory=2Gi --port=8080 --timeout=300

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import Response
from rembg import remove, new_session
from PIL import Image, ImageFilter
from io import BytesIO
from typing import Literal
import os

app = FastAPI()
#SESSION = new_session()
SESSION = new_session(model_name="u2net_cloth_seg")

# 入力画像の長辺上限（これより大きいときだけ縮小）
MAX_SIDE = 4624


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/remove-bg")
async def remove_bg(
    file: UploadFile = File(...),
    # ✅ デフォルトは透明PNG（質重視）
    mode: Literal["white", "transparent"] = "white",
    size: int = 1024,  # white モード
):
    """
    背景除去 API
    - mode="transparent"  : ほぼ生の解像度のまま、背景だけ透明にして返す（デフォルト）
    - mode="white"        : 白背景＋size x size にリサイズして返す
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="画像ファイルを送ってください。")

    # 1) 画像読み込み
    try:
        raw_bytes = await file.read()
        img = Image.open(BytesIO(raw_bytes)).convert("RGBA")
    except Exception:
        raise HTTPException(status_code=400, detail="画像の読み込みに失敗しました。")

    # 2) 大きすぎる場合だけ縮小（長辺 4624px まで）
    w, h = img.size
    if max(w, h) > MAX_SIDE:
        ratio = MAX_SIDE / float(max(w, h))
        new_w = int(w * ratio)
        new_h = int(h * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        w, h = img.size

    # rembg に bytes で渡す
    buf_in = BytesIO()
    img.save(buf_in, format="PNG")
    input_bytes = buf_in.getvalue()

    # 3) rembg で背景除去
    try:
        cutout_bytes = remove(input_bytes, session=SESSION)
        cutout = Image.open(BytesIO(cutout_bytes)).convert("RGBA")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"背景除去に失敗しました: {e}")

    # 3.5) ★ 境界をカッチリさせる処理（アルファを2値化＋少し膨らませ）
    r, g, b, a = cutout.split()

    # しきい値 220 以上を完全不透明、未満を完全透明にする
    # 数値を上げる(230〜240) → よりパキッと / 下げる(200前後) → 多少なめらか
    THRESHOLD = 220
    a = a.point(lambda v: 255 if v >= THRESHOLD else 0)

    # マスクを 1 ピクセルぶん膨らませて、輪郭欠けを防ぐ（3x3 の MaxFilter）
    a = a.filter(ImageFilter.MaxFilter(3))
    a = a.filter(ImageFilter.MinFilter(3))

    cutout = Image.merge("RGBA", (r, g, b, a))

    # =========================
    # A. 透明PNGモード（質重視）
    # =========================
    if mode == "transparent":
        buf = BytesIO()
        cutout.save(buf, format="PNG")
        buf.seek(0)
        return Response(content=buf.getvalue(), media_type="image/png")

    # =========================
    # B. 白背景＋正方形リサイズ
    # =========================
    try:
        size = int(size)
        if size <= 0 or size > 4096:
            size = 1024
    except Exception:
        size = 1024

    # 白背景キャンバス
    background = Image.new("RGB", (size, size), (255, 255, 255))

    cw, ch = cutout.size
    # 基本は縮小のみ（拡大するとまたボケるので）
    ratio = min(1.0, size / float(max(cw, ch)))
    new_cw = int(cw * ratio)
    new_ch = int(ch * ratio)

    cutout_resized = cutout.resize((new_cw, new_ch), Image.LANCZOS)

    offset_x = (size - new_cw) // 2
    offset_y = (size - new_ch) // 2

    background.paste(cutout_resized, (offset_x, offset_y), mask=cutout_resized)

    buf_out = BytesIO()
    background.save(buf_out, format="PNG")
    buf_out.seek(0)
    return Response(content=buf_out.getvalue(), media_type="image/png")


# ローカル開発用（Cloud Run では使われない）
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
