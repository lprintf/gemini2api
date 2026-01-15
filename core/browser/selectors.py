"""
Gemini 页面选择器常量

集中管理所有 CSS/XPath 选择器，便于维护和适配页面变化
"""

# =============================================================================
# 输入区域
# =============================================================================

INPUT_BOX = 'div[contenteditable="true"]'

SUBMIT_BUTTON = [
    'button[aria-label*="发送"]',
    'button[aria-label*="Send"]',
    'button[aria-label*="submit"]',
]

UPLOAD_MENU_BUTTON = [
    'button[aria-label="打开文件上传菜单"]',
    'button[aria-label="Open file upload menu"]',
    'button[aria-label*="Add files"]',
    'button[aria-label*="上传"]',
    'button[aria-label*="upload"]',
]

# =============================================================================
# 模型选择
# =============================================================================

MODEL_MENU_BUTTON = '[data-test-id="bard-mode-menu-button"]'

MODEL_OPTION_FAST = [
    '[data-test-id="bard-mode-option-fast"]',
    '[data-test-id="bard-mode-option-快速"]',
    '[data-test-id="bard-mode-option-Flash"]',
]

MODEL_OPTION_PRO = [
    '[data-test-id="bard-mode-option-pro"]',
    '[data-test-id="bard-mode-option-Pro"]',
]

# =============================================================================
# 工具栏 / 图片生成
# =============================================================================

TOOLS_BUTTON = [
    "button.toolbox-drawer-button",
    'button[aria-label="工具"]',
    'button[aria-label="Tools"]',
]

IMAGE_GEN_OPTION = [
    "text=Create images",
    "text=生成图片",
]

IMAGE_GEN_DESELECT = ".toolbox-drawer-item-deselect-button"

# =============================================================================
# 侧边栏 / 临时对话
# =============================================================================

MAIN_MENU_BUTTON = [
    "button.main-menu-button",
    'button[data-test-id="side-nav-menu-button"]',
    'button[aria-label="主菜单"]',
    'button[aria-label="Main menu"]',
    'button[aria-label*="展开菜单"]',
    'button[aria-label*="Expand menu"]',
]

TEMP_CHAT_BUTTON = [
    'button[aria-label*="临时"]',
    'button[aria-label*="Temporary"]',
    'button:has-text("临时对话")',
    'button:has-text("Temporary chat")',
]

TEMP_CHAT_CARD = ".temporary-chat-card"
TEMP_CHAT_TITLE = ".gds-title-l"

# =============================================================================
# 对话响应区域
# =============================================================================

RESPONSE_CONTAINER = [
    "model-response",
    "message-content model-response",
    "response-container",
]

# 生成的图片（排除头像）
GENERATED_IMAGE = 'img[src*="googleusercontent"]'
AVATAR_PATTERN = "/a/ACg8oc"

# =============================================================================
# 下载按钮
# =============================================================================

DOWNLOAD_BUTTON = [
    'button[aria-label*="下载"]',
    'button[aria-label*="Download"]',
    'button[aria-label*="保存"]',
    'button[aria-label*="Save"]',
]

# =============================================================================
# 弹窗 / 同意按钮
# =============================================================================

AGREE_BUTTON = [
    'button:has-text("Agree")',
    'button:has-text("同意")',
    'button:has-text("I agree")',
    'button:has-text("Accept")',
    'button:has-text("接受")',
    'button:has-text("OK")',
    'button:has-text("确定")',
    '[role="dialog"] button[data-mdc-dialog-action="accept"]',
    '[role="dialog"] button.mdc-dialog__button--default',
]

# =============================================================================
# 辅助函数
# =============================================================================


def is_generated_image(src: str) -> bool:
    """判断是否为生成的图片（排除头像）"""
    return src and "googleusercontent" in src and AVATAR_PATTERN not in src


def get_model_keywords(model: str) -> list[str]:
    """获取模型关键词用于验证"""
    if model == "Fast":
        return ["Fast", "快速", "flash"]
    else:
        return ["Pro", "pro"]
