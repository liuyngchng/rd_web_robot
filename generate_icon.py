"""生成 rd_web_robot 桌面图标"""
import math
from pathlib import Path
from PIL import Image, ImageDraw

SIZES = [16, 32, 48, 64, 128, 256]
BASE_DIR = Path(__file__).resolve().parent

# 配色（参考 kb-chat-flow 蓝白主题）
ACCEPT = "#4b6cb7"
ACCEPT_DARK = "#2c487e"
WHITE = "#ffffff"
ACCENT = "#a6e3a1"  # 播放按钮绿


def draw_icon(size: int) -> Image.Image:
    """绘制一个 size×size 的圆角方块，内含播放三角 + 录制圆点"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = max(1, size // 16)
    radius = max(4, size // 8)
    r = radius

    # ── 圆角矩形背景──
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=r,
        fill=ACCEPT,
    )

    # ── 顶部渐变暗条（模仿 macOS 风格微光泽）──
    overlay_top = max(2, size // 6)
    draw.rounded_rectangle(
        [margin, margin, size - margin, margin + overlay_top],
        radius=r,
        fill=(255, 255, 255, 40),
    )

    # ── 白色图形：播放三角 ──
    cx, cy = size / 2, size / 2
    play_scale = size / 64   # 以 64px 为基准

    # 播放三角，稍微偏左以给录制圆让位
    tri_offset_x = -2 * play_scale
    tri_base_x = cx + tri_offset_x
    tri_w = 10 * play_scale
    tri_h = 12 * play_scale

    tri_points = [
        (tri_base_x - tri_w * 0.4, cy - tri_h),
        (tri_base_x - tri_w * 0.4, cy + tri_h),
        (tri_base_x + tri_w * 0.6, cy),
    ]
    draw.polygon(tri_points, fill=WHITE)

    # ── 录音圆点 ──
    dot_cx = cx + 6 * play_scale
    dot_r = max(2, int(3.5 * play_scale))
    draw.ellipse(
        [dot_cx - dot_r, cy - dot_r, dot_cx + dot_r, cy + dot_r],
        fill="#f38ba8",  # 粉红录制点
    )

    return img


def main():
    img_256 = draw_icon(256)

    # 保存 PNG（用于 Linux/macOS .png 图标和文档引用）
    png_path = BASE_DIR / "icon.png"
    img_256.save(png_path, "PNG")
    print(f"[icon] {png_path}")

    # 保存 ICO（Windows，含多尺寸）
    ico_path = BASE_DIR / "icon.ico"
    frames = []
    for s in SIZES:
        frames.append(draw_icon(s).resize((s, s), Image.LANCZOS))
    frames[0].save(
        ico_path, format="ICO", sizes=[(s, s) for s in SIZES],
        append_images=frames[1:],
    )
    print(f"[icon] {ico_path}")


if __name__ == "__main__":
    main()
