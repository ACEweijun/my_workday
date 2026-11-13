"""常量定义。"""
from __future__ import annotations

DOMAIN = "my_workday"
NAME = "我的工作日"

# 数据源。{year} 会被替换成四位年份。
# 备用地址（jsDelivr 不通时在“配置 → 选项”里换成这个）：
#   https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json
DEFAULT_URL = "https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json"

CONF_URL = "url"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_NOTIFY_TIME = "notify_time"
CONF_HOLIDAY_LEAD = "holiday_lead_days"
CONF_MONTH_END_AT = "month_end_left"
CONF_CUSTOM_WORK = "custom_work"
CONF_CUSTOM_REST = "custom_rest"

DEFAULT_NOTIFY_TIME = "08:00:00"
DEFAULT_HOLIDAY_LEAD = "3,1"
DEFAULT_MONTH_END_AT = "3"

STORAGE_VERSION = 1
STORAGE_KEY = "my_workday.custom"

# 自定义日期的三种状态
MODE_WORK = "work"
MODE_REST = "rest"
MODE_AUTO = "auto"

# 实体 ID（固定英文，避免中文名生成不可预期的 ID）
ENTITY_LEFT = "sensor.my_workday_left"
ENTITY_TOTAL = "sensor.my_workday_total"
ENTITY_TODAY = "binary_sensor.my_workday_today"
ENTITY_TOMORROW = "binary_sensor.my_workday_tomorrow"
ENTITY_NEXT_HOLIDAY = "sensor.my_workday_next_holiday"
ENTITY_PROGRESS = "sensor.my_workday_month_progress"
ENTITY_CALENDAR = "calendar.my_workday"

# 服务
SERVICE_SET_CUSTOM = "set_custom"
SERVICE_SET_DAY = "set_day"
SERVICE_CLEAR = "clear_custom"
SERVICE_SET_YEAR = "set_year_data"
SERVICE_SET_ANNIVERSARY = "set_anniversaries"
SERVICE_SET_TODOS = "set_todos"
SERVICE_REFRESH = "refresh_data"

# 当年数据多久复查一次（天）。上游年中若有修订也能跟上
REFRESH_DAYS = 7

# 自定义日期保留多久（天），避免无限增长
KEEP_DAYS = 500

# 集成自带的日历界面
PANEL_URL = "/my_workday"
PANEL_FILE = "workday.html"
PANEL_TITLE = "我的工作日"
PANEL_ICON = "mdi:calendar-check"
