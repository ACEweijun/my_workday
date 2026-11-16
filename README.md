# workday_maintenance（工作日 · 维护台账）

Home Assistant 自定义集成。**一个集成、一份数据、两个侧栏网页**：工作日 / 调休 / 待办 / 纪念日，加上维护台账。

- **月历**：法定节假日 / 调休自动获取（holiday-cn，拉取失败自动降级为周末规则，不报错）；格子按状态着色——蓝底=上班、灰底=休息、红边=被手动调整过
- **待办 / 纪念日**：逾期在前排序、勾选完成、点文字编辑；纪念日支持每周 / 每月 / 每季度 / 每年重复
- **维护台账**：多项目、小项间隔（天数 + 计数）、一键记一次、多项记录、历史可编辑
- **联动**：维护到期写进日历与「今天要做的事」，可自动同步为待办
- **实时**：两页共用一条 WebSocket 订阅，任一页面写入，另一页即时刷新

## 安装

1. HACS → 自定义存储库 → `https://github.com/ACEweijun/workday_maintenance` → 类型「集成」→ 搜索「workday_maintenance」→ 下载
2. **重启 Home Assistant**（必须完整重启，不能只重新加载）
3. 设置 → 设备与服务 → 添加集成 → workday_maintenance → 提交

手动安装：把 `custom_components/workday_maintenance` 整个文件夹复制到 `/config/custom_components/`，重启后按第 3 步添加。

## 两个网页

侧栏会多出两个入口，两页之间没有互跳按钮，切换请用侧边栏。

| 入口 | 地址 | 内容 |
|---|---|---|
| **我的工作日** | `/workday_maintenance/workday.html` | 月历（点格子切换班/休、右键新增与记录）、统计卡（本月剩余 / 今天 / 距离下一个事件）、待办、纪念日、自定义工作日、维护到期 |
| **维护台账** | `/workday_maintenance/maintenance.html` | 项目、维护小项（间隔天数 + 计数）、记一次 / 多项记录、历史记录、导出 |

格子颜色（`shared.css` 顶部「日历格子颜色配置区」可改）：淡蓝=上班、灰=休息、红边=用户手动调整（来源见悬停浮层）。

## 数据

只有一份 `.storage` 键 `workday_maintenance.merged`：

```
workday:     自定义班休 / 待办 / 纪念日
maintenance: 全部维护项目（小项 + 历史）
```

新建 / 删除项目不需要管理员权限。前端通过 `workday_maintenance.get_snapshot` 一次取全量，实体属性里不放 JSON，不撑大 recorder。

放假数据来自 [holiday-cn](https://github.com/NateScarlet/holiday-cn)（jsDelivr），每年自动拉当年与次年。

## 实体

| 实体 ID | 说明 |
|---|---|
| `binary_sensor.workday_maintenance_today` / `tomorrow` | 今天 / 明天是否上班 |
| `sensor.workday_maintenance_left` / `total` / `month_progress` | 本月剩余 / 总数 / 进度 |
| `sensor.workday_maintenance_next_holiday` | 距下个节假日 |
| `sensor.workday_maintenance_due_maintenance` | 到期维护项数，属性带到期清单 |
| `sensor.workday_maintenance_today_tasks` | 今天要做的事：待办 + 已到期维护 |
| `calendar.workday_maintenance` | 同一日历含班休、节假日与维护到期事件 |

## 服务

统一命名空间 `workday_maintenance.*`，全部支持 `response_variable`。

| 分组 | 服务 |
|---|---|
| 读取 | `get_snapshot`、`list_projects`、`export_markdown` |
| 工作日 | `set_day`、`set_custom`、`clear_custom`、`refresh_data`、`set_year_data` |
| 待办 / 纪念日 | `set_todos`、`set_anniversaries` |
| 维护项目 | `add_project`、`update_project`、`delete_project`、`set_counter` |
| 维护小项 | `add_item`、`update_item`、`delete_item`、`set_baseline` |
| 维护记录 | `log_service`、`update_record`、`delete_record` |
| 联动 | `sync_maintenance_todos` |

`set_todos` / `set_anniversaries` 可直接传数组以保留记录 ID。配置项：`soon_days`（提前几天算"快到期"，默认 7）、`holiday_url`（放假数据源）、自动同步到期项为待办开关。

## 前端定制

- **格子颜色**：`frontend/shared.css` 最顶部「日历格子颜色配置区」——上班 / 休息 / 标休 / 标班四组（文字色、底色）+ 红边色，浅色 / 深色主题各一份，改完保存刷新即可。
- **本地预览**：`frontend/demo-data.js` 是虚拟数据层，非 HA 环境（本地文件 / 静态服务器）打开页面时自动加载虚拟数据，部署到 HA 后自动失效，不接入真实数据。改排版 → 刷新即见效果。
- **移动端**：620px 断点，手机端字号与触控高度单独适配。

## 开发与自检

```bash
python -m unittest discover -s tests -v
```

tests 用桩模块加载纯逻辑，不需要安装 Home Assistant。仓库自带 GitHub Actions：每次提交跑单测 + hassfest + HACS 校验。

## v2.1.0 变更（相对 2.0.0）

- 全部界面重构：格子改为上下两行（顶行日期 + 待/维计数、次行按优先级展示纪念日 > 待办 > 维护，多条带数量前缀）；统计卡「距离」合并为一行
- 色系统重做：蓝 / 灰底色表达是否上班，红边表达手动调整，法定节假日 / 补班并入结果色；颜色集中在 `shared.css` 顶部配置区
- 新增 `demo-data.js` 本地预览数据层（非 HA 环境自动启用）
- 维护台账：小项卡片状态色左缘、「＋ 记一次」紧凑化、计数改一行仪表条

更早版本的演进记录见 git tag（v1.0.x ~ v2.0.0）。

## 许可

MIT
