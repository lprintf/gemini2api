"""
Gemini 水印去除工具

基于逆向 alpha 混合算法去除 Gemini 生成图片右下角的可见水印。
使用真实的水印 alpha 映射数据（从 GeminiWatermarkTool 提取）。

参考: https://github.com/allenk/GeminiWatermarkTool

使用示例:
    from server.services.tasks.remove_watermark.main import WatermarkRemover
    from PIL import Image

    img = Image.open("input.png")
    img_no_wm = WatermarkRemover.remove_watermark(img)
    img_no_wm.save("output.png")

技术说明:
    Gemini水印算法: watermarked = alpha * 255 + (1 - alpha) * original
    逆向算法: original = (watermarked - alpha * 255) / (1 - alpha)
    其中 alpha 来自预提取的水印透明度映射
"""


from pathlib import Path
from typing import Literal, Optional

from PIL import Image


class WatermarkRemover:
    """Gemini 水印去除器"""

    # 水印尺寸常量
    WATERMARK_SIZE_SMALL = 48
    WATERMARK_SIZE_LARGE = 96

    # 水印位置常量（右下角边距） - 来自 GeminiWatermarkTool
    MARGIN_SMALL = 32  # 48x48 水印使用 32px 边距
    MARGIN_LARGE = 64  # 96x96 水印使用 64px 边距

    # 缓存 alpha 映射
    _alpha_map_small = None
    _alpha_map_large = None

    @staticmethod
    def _load_alpha_map(size: int) -> list:
        """
        加载真实的 alpha 映射（从背景图像计算）

        Args:
            size: 水印尺寸 (48 或 96)

        Returns:
            Alpha 映射二维列表 (size x size)，值范围 [0, 1]
        """
        bg_path = Path(__file__).parent / f"bg_{size}.png"

        if not bg_path.exists():
            raise FileNotFoundError(
                f"背景图像文件不存在: {bg_path}\n"
                "请先从 GeminiWatermarkTool 提取背景图像"
            )

        # 加载背景图像
        bg_img = Image.open(bg_path).convert("RGB")
        bg_pixels = bg_img.load()

        # 计算 alpha map: 取 RGB 三个通道的最大值，然后归一化
        # 这与 GeminiWatermarkTool 的算法一致
        alpha_map = []
        for y in range(size):
            row = []
            for x in range(size):
                r, g, b = bg_pixels[x, y]
                alpha = max(r, g, b) / 255.0
                row.append(alpha)
            alpha_map.append(row)

        return alpha_map

    @classmethod
    def get_alpha_map(cls, size: int) -> list:
        """
        获取 alpha 映射（带缓存）

        Args:
            size: 水印尺寸 (48 或 96)

        Returns:
            Alpha 映射二维列表
        """
        if size == 48:
            if cls._alpha_map_small is None:
                cls._alpha_map_small = cls._load_alpha_map(48)
            return cls._alpha_map_small
        else:  # 96
            if cls._alpha_map_large is None:
                cls._alpha_map_large = cls._load_alpha_map(96)
            return cls._alpha_map_large

    @staticmethod
    def detect_watermark_size(width: int, height: int) -> Literal[48, 96]:
        """
        自动检测水印尺寸 - 基于 GeminiWatermarkTool 的逻辑

        Args:
            width: 图片宽度
            height: 图片高度

        Returns:
            水印尺寸（48 或 96）
        """
        # 来自 GeminiWatermarkTool:
        # Large (96x96): 当宽度AND高度都 > 1024
        # Small (48x48): 其他情况 (包括 1024x1024)
        if width > 1024 and height > 1024:
            return WatermarkRemover.WATERMARK_SIZE_LARGE
        return WatermarkRemover.WATERMARK_SIZE_SMALL

    @staticmethod
    def remove_watermark(
        image: Image.Image,
        watermark_size: Optional[Literal[48, 96]] = None,
        verbose: bool = False,
    ) -> Image.Image:
        """
        去除图片右下角的水印

        Args:
            image: PIL Image 对象
            watermark_size: 水印尺寸（48 或 96），None 表示自动检测
            verbose: 是否打印详细信息

        Returns:
            去除水印后的 PIL Image 对象
        """
        # 确保图片是 RGB 模式
        if image.mode == "RGBA":
            # 转换为 RGB
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(
                image, mask=image.split()[3] if len(image.split()) == 4 else None
            )
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")

        width, height = image.size

        # 自动检测水印尺寸
        if watermark_size is None:
            watermark_size = WatermarkRemover.detect_watermark_size(width, height)

        if verbose:
            print(f"  [水印去除] 图片尺寸: {width}x{height}")
            print(f"  [水印去除] 水印尺寸: {watermark_size}x{watermark_size}")

        # 确定边距
        margin = (
            WatermarkRemover.MARGIN_LARGE
            if watermark_size == 96
            else WatermarkRemover.MARGIN_SMALL
        )

        # 计算水印区域位置
        x_start = width - watermark_size - margin
        y_start = height - watermark_size - margin

        # 边界检查
        if x_start < 0 or y_start < 0:
            if verbose:
                print("  [水印去除] ⚠ 图片太小，无法去除水印")
            return image

        # 加载真实的 alpha 映射
        try:
            alpha_map = WatermarkRemover.get_alpha_map(watermark_size)
        except FileNotFoundError as e:
            if verbose:
                print(f"  [水印去除] ⚠ {e}")
            return image

        # 复制图片用于修改
        result = image.copy()
        pixels = result.load()

        # 应用逆向 alpha 混合
        # 公式: original = (watermarked - alpha * logo_value) / (1 - alpha)
        # logo_value = 255.0 (纯白色水印)

        logo_value = 255.0
        alpha_threshold = 0.002  # 忽略非常小的 alpha 值（来自 GeminiWatermarkTool）
        max_alpha = 0.99  # 避免除以接近零的数（来自 GeminiWatermarkTool）

        # 逐像素处理
        for row in range(watermark_size):
            for col in range(watermark_size):
                alpha = alpha_map[row][col]

                # 只处理 alpha > threshold 的像素（避免黑色背景参与计算）
                if alpha < alpha_threshold:
                    continue

                # 限制 alpha
                alpha = min(alpha, max_alpha)
                one_minus_alpha = 1.0 - alpha

                # 图片坐标
                img_x = x_start + col
                img_y = y_start + row

                # 获取原始像素
                r, g, b = pixels[img_x, img_y]

                # 逆向 alpha 混合
                r_orig = (r - alpha * logo_value) / one_minus_alpha
                g_orig = (g - alpha * logo_value) / one_minus_alpha
                b_orig = (b - alpha * logo_value) / one_minus_alpha

                # 限制范围并转换为整数
                r_orig = max(0, min(255, int(r_orig + 0.5)))
                g_orig = max(0, min(255, int(g_orig + 0.5)))
                b_orig = max(0, min(255, int(b_orig + 0.5)))

                pixels[img_x, img_y] = (r_orig, g_orig, b_orig)

        if verbose:
            print("  [水印去除] ✓ 水印已去除")

        return result



if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python main.py <input_image> [output_image]")
        sys.exit(1)
    img = Image.open(sys.argv[1])
    result = WatermarkRemover.remove_watermark(img, verbose=True)
    out = sys.argv[2] if len(sys.argv) > 2 else "output.webp"
    result.save(out)
    print(f"\n✓ 已保存到: {out}")

