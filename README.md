# 我的日程 · my_workday

Home Assistant 自定义集成。**一个集成、一份数据、两个独立网页**：工作日 / 调休 / 待办 / 纪念日，加上家里的维护台账。

> 1.0.0 起把原来的 `my_maintenance` 完整合并进本集成，后端、存储、服务、事件全部重写。旧版 `.storage` 数据不兼容，需要重新录入。

## 两个网页

装好重启后，侧边栏会多出两个入口：

| 入口 | 地址 | 内容 |
|---|---|---|
| **我的工作日**（主体） | `/my_workday/workday.html` | 月历、调休与补班、待办分组、纪念日、自定义工作日、维护到期提示 |
| **维护台账** | `/my_workday/maintenance.html` | 多项目、维护小项、周期与计数、记录一次维护、历史、导出 |

两个页面各自独立渲染，**共用同一份 `shared.css` / `shared.js`**（一套配色、一个 620px 断点、一次 token 解析、一条 WebSocket 订阅）。页面之间**没有互跳按钮**，切换请用侧边栏。在任一页面写入数据，后端会广播 `my_workday_updated` 事件：当前打开的页面实时刷新，切到另一个页面时会重新拉取最新快照。

## 安装

1. HACS → 自定义存储库 → `https://github.com/ACEweijun/my_workday` → 类型「集成」（HA 2026.11 起入口在 设置 → Marketplace）
2. 搜索「我的日程」→ 下载 → **重启 Home Assistant**
3. 设置 → 设备与服务 → 添加集成 → 我的日程 → 提交

手动安装：把 `custom_components/my_workday` 整个文件夹复制到 `/config/custom_components/`，重启后按第 3 步添加。

## 数据放哪

只有一个 `.storage` 键 `my_workday.merged`：

```
workday:     自定义工作日 / 年度覆盖 / 待办 / 纪念日
maintenance: 全部维护项目（小项 + 历史）
```

不再有「每个维护项目一个 config entry」的模型，因此新建 / 删除项目**不需要管理员权限**，也不再走 WebSocket config entry API。前端通过 `my_workday.get_snapshot` 一次拿到完整数据，实体属性里不再塞大段 JSON（不会撑大 recorder 数据库）。

放假数据来自 [holiday-cn](https://github.com/NateScarlet/holiday-cn)（jsDelivr），每年自动拉当年与次年。**拉不到时降级为「按周末判断」并在页面标注**，不再让整个集成报错——维护台账不会跟着一起挂。

## 实体

| 实体 ID | 说明 |
|---|---|
| `binary_sensor.my_workday_today` / `tomorrow` | 今天 / 明天是否上班 |
| `sensor.my_workday_left` / `total` / `month_progress` | 本月剩余 / 总数 / 进度 |
| `sensor.my_workday_next_holiday` | 距下个节假日 |
| `sensor.my_workday_due_maintenance` | **到期维护项数**，属性带全部到期清单与项目汇总 |
| `sensor.my_workday_today_tasks` | **今天要做的事**：今日未完成待办 + 已到期维护 |
| `calendar.my_workday` | **同一个日历**里既有上班 / 补班 / 节假日，也有维护到期事件 |

旧版 `sensor.my_maintenance_<slug>_*` 每项目实体不再生成；需要明细请用 `get_snapshot` 或 `list_projects` 服务。

## 服务（统一命名空间 `my_workday.*`）

| 分组 | 服务 |
|---|---|
| 读取 | `get_snapshot`、`list_projects`、`export_markdown` |
| 工作日 | `set_day`、`set_custom`、`clear_custom`、`refresh_data`、`set_year_data` |
| 待办 / 纪念日 | `set_todos`、`set_anniversaries` |
| 维护项目 | `add_project`、`update_project`、`delete_project`、`set_counter` |
| 维护小项 | `add_item`、`update_item`、`delete_item`、`set_baseline` |
| 维护记录 | `log_service`、`update_record`、`delete_record` |
| 联动 | `sync_maintenance_todos` |

全部服务支持 `response_variable`。`set_todos` / `set_anniversaries` 可直接传 `todos` / `anniversaries` 数组以保留记录 ID（同步生成的 `[维护]` 待办不会被覆盖丢失）。

## 联动

- **同一日历**：`calendar.my_workday` 同时输出工作日事件与维护到期事件，HA 原生日历卡片一眼看全。
- **到期 → 待办**：`sync_maintenance_todos` 把已到期 / 快到期的维护项写成 `[维护]` 前缀待办；在「设置 → 设备与服务 → 我的日程 → 配置」打开「自动把维护到期项写成待办」后，每天 0 点自动同步，重复执行会先清掉旧的同步项。
- **页间实时**：后端 `hass.bus.async_fire("my_workday_updated", {"scope": ...})`，网页通过 `/api/websocket` 订阅事件；页面刷新或首次加载时若服务尚未就绪会自动重试 3 次，重试期间控件点击会被拦截并提示「数据还在加载」。
- **汇总**：`sensor.my_workday_today_tasks` 把两类「今天要做的事」合成一个数。

## 与旧版差异

| 项 | 旧版 | 1.0.0 |
|---|---|---|
| 集成数量 | 2 个（`my_workday` + `my_maintenance`） | 1 个 |
| 配置模型 | 工作日单 entry + 维护每项目一 entry | 单 entry，项目是数据列表 |
| 存储 | 多份 `.storage` | 1 份 `my_workday.merged` |
| 页面容器 | 另有 `unified.html` 双 iframe 容器页 | **移除**，两个页面各自独立 |
| 每项目实体 | 6 个 × N 项目 | 不再生成，改用汇总实体 + 服务 |
| 金额字段 | 已去掉 | 仍不提供 |
| 故障行为 | holiday-cn 拉不到时集成报错 | 降级为周末规则，标注数据来源 |

## 开发与自检

```bash
python -m unittest discover -s tests -v
```

`tests/` 用桩模块加载纯逻辑，不需要装 Home Assistant。仓库自带 GitHub Actions：每次提交跑单测 + hassfest + HACS 校验。

## 许可

MIT
