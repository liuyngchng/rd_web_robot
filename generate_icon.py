"""生成 rd_web_robot 桌面图标"""
from pathlib import Path
from PIL import Image, ImageDraw

BASE_DIR = Path(__file__).resolve().parent

COLOR_BG = "#4b6cb7"
COLOR_WHITE = "#ffffff"
COLOR_DOT = "#f38ba8"


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, size // 12)
    r = max(3, size // 7)

    # 圆角蓝底
    d.rounded_rectangle([m, m, size - m, size - m], radius=r, fill=COLOR_BG)

    # 播放三角
    cx, cy = size / 2, size / 2
    sp = size / 64
    bx, bw, bh = cx - 3 * sp, 10 * sp, 14 * sp
    pts = [
        (bx - bw * 0.35, cy - bh),
        (bx - bw * 0.35, cy + bh),
        (bx + bw * 0.65, cy),
    ]
    d.polygon(pts, fill=COLOR_WHITE)

    # 录制圆点
    dot_r = max(1, int(4 * sp))
    d.ellipse(
        [cx + 7 * sp - dot_r, cy - dot_r, cx + 7 * sp + dot_r, cy + dot_r],
        fill=COLOR_DOT,
    )

    return img


def main():
    img = draw_icon(256)
    img.save(BASE_DIR / "icon.png", "PNG")
    img.save(BASE_DIR / "icon.ico", format="ICO", sizes=[(256, 256)])
    print("[icon] icon.png + icon.ico 已生成")


if __name__ == "__main__":
    main()