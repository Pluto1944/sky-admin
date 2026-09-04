"""War layout collection and publishing domain."""

from .models import LayoutCandidate, PostPayload
from .composer import compose_article
from .extractor import extract_layouts
from .socialdata_guard import SocialDataBudgetExceeded, SocialDataBudgetGuard
from .socialdata_source import SocialDataError, SocialDataSource
from .service import RunResult, WarLayoutService
from .settings import WarLayoutSettings
from .x_http import XHttpTransport
from .wechat_http import WeChatHttpClient

__all__ = ["LayoutCandidate", "PostPayload", "RunResult", "WarLayoutService", "WarLayoutSettings", "XHttpTransport", "WeChatHttpClient", "SocialDataBudgetExceeded", "SocialDataBudgetGuard", "SocialDataError", "SocialDataSource", "compose_article", "extract_layouts"]
