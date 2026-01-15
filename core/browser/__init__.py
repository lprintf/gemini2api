"""Browser 模块"""

from .config import (
    DEFAULT_PERMISSIONS,
    DEFAULT_TIMEOUT,
    DEFAULT_VIEWPORT,
    get_launch_args,
)
from .selectors import (
    AGREE_BUTTON,
    AVATAR_PATTERN,
    DOWNLOAD_BUTTON,
    GENERATED_IMAGE,
    IMAGE_GEN_DESELECT,
    IMAGE_GEN_OPTION,
    INPUT_BOX,
    MAIN_MENU_BUTTON,
    MODEL_MENU_BUTTON,
    MODEL_OPTION_FAST,
    MODEL_OPTION_PRO,
    RESPONSE_CONTAINER,
    SUBMIT_BUTTON,
    TEMP_CHAT_BUTTON,
    TEMP_CHAT_CARD,
    TEMP_CHAT_TITLE,
    TOOLS_BUTTON,
    UPLOAD_MENU_BUTTON,
    get_model_keywords,
    is_generated_image,
)

__all__ = [
    # config
    "DEFAULT_PERMISSIONS",
    "DEFAULT_TIMEOUT",
    "DEFAULT_VIEWPORT",
    "get_launch_args",
    # selectors
    "AGREE_BUTTON",
    "AVATAR_PATTERN",
    "DOWNLOAD_BUTTON",
    "GENERATED_IMAGE",
    "IMAGE_GEN_DESELECT",
    "IMAGE_GEN_OPTION",
    "INPUT_BOX",
    "MAIN_MENU_BUTTON",
    "MODEL_MENU_BUTTON",
    "MODEL_OPTION_FAST",
    "MODEL_OPTION_PRO",
    "RESPONSE_CONTAINER",
    "SUBMIT_BUTTON",
    "TEMP_CHAT_BUTTON",
    "TEMP_CHAT_CARD",
    "TEMP_CHAT_TITLE",
    "TOOLS_BUTTON",
    "UPLOAD_MENU_BUTTON",
    "get_model_keywords",
    "is_generated_image",
]
