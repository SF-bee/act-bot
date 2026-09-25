#!/usr/bin/env bash
# 从 NapCat 容器抓最新登录二维码，放大成可扫图，供手机 QQ 扫码登录。
#
# 什么时候用：快速登录（deploy/docker/.env 的 NAPCAT_QQ / ACCOUNT）失效时，
#   容器日志会出现「请扫描下面的二维码」，此时用本脚本把码导出来扫。
#
# 用法： bash deploy/docker/fetch-qr.sh
# 依赖： docker（容器在跑）、uv（临时装二维码依赖，不动项目 .venv）
# 产物： deploy/docker/runtime/qr/qrcode-scan.png（runtime/ 已 gitignore）
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONTAINER="${NAPCAT_CONTAINER:-act-napcat}"
OUT_DIR="${QR_OUT_DIR:-$REPO_DIR/deploy/docker/runtime/qr}"
mkdir -p "$OUT_DIR"

echo "容器: $CONTAINER"
echo "输出: $OUT_DIR"
docker cp "$CONTAINER:/app/napcat/cache/qrcode.png" "$OUT_DIR/qrcode-raw.png"

cd "$REPO_DIR"
uv run --quiet --with 'qrcode[pil]' --with pillow --with zxing-cpp python - "$OUT_DIR" <<'PY'
import os, sys
from PIL import Image
from zxingcpp import read_barcode
import qrcode

out_dir = sys.argv[1]
raw = os.path.join(out_dir, "qrcode-raw.png")
res = read_barcode(Image.open(raw))
url = res.text if res else ""
if not url:
    print("未解出二维码：可能新码还没生成，等几秒重跑。")
    sys.exit(1)
qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=12, border=4)
qr.add_data(url)
qr.make(fit=True)
scan = os.path.join(out_dir, "qrcode-scan.png")
qr.make_image(fill_color="black", back_color="white").save(scan)
check = read_barcode(Image.open(scan))
print("解码成功:", url[:28] + "…")
print("放大校验:", "OK" if (check and check.text == url) else "FAIL")
print("可扫图:", scan)
PY
echo "用手机 QQ 扫上面那张图即可登录。"
