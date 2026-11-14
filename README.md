# 多渠道招聘岗位归并与薪资口径归一（`jobmerge`）

> 数据工程 · 中型多模块项目。原生 HTML/CSS/JS 前端 + Python FastAPI 后端 + Celery worker + PostgreSQL 16 + Redis，5 个容器一键起。
>
> **薪资包口径（本版重点）**：每条来源单独归一成「固定 / 浮动 / 可比月薪 + 换算过程」的薪资包；
> 归并簇只采用一条完整、前后一致的来源，多个来源不一致时进入复核并列出差异，全部不可比时明确标出；
> 任何来源的原始薪资与计算依据都保留在 `posts` 与来源明细导出中，页面计数 / 复核结论 / 导出清单三方对账一致。
>
> 视觉方向：**报纸分类广告**——墨黑 + 套红 + 米灰纸底，思源宋正文 + 等宽检字；登录页是「取报单」，总览是头版。

## 1. 场景

- **模拟客户**：云雀招聘聚合平台 · 岗位运营组（8 人），为 60 家企业客户做岗位聚合检索。
- **现有工作流**：运营每天从 12 个招聘渠道（各自独立采集器）把岗位拉进 Excel，人工挑重复、手算月薪，再导给检索侧。
- **三个痛点**：
  1. 同一岗位在 4–6 个渠道重复挂载，检索结果里同一职位刷屏；
  2. 薪资写法混乱（`8-12K·13薪`、`年薪18万`、`300元/天`、`底薪8000+提成`、`面议`），
     过去把不同来源的底薪、提成、发薪月数拼成一个区间，排序把拼出来的数当真实薪资；
  3. 过期岗位未下线，仍留在发布清单里。
- **上下游**：各渠道采集器 → **本系统（原始岗位入库 → 归一 → 归并 → 复核 → 发布清单）** → 检索服务 / 客户报表。
- **一天的工作剧本**（演示数据锚定 2026-11-14）：
  1. 06:00–08:00 四个采集器按 `crawl_cron` 抓取，岗位落到 `posts`；
  2. 08:20 运营专员打开头版，看到 160 条来稿、薪资不可比 21 条（13.13%，面议 15 条 + 不可解析 6 条）；
  3. 08:30 在「归并结果」按 0.82 阈值发起归并：160 条 → 118 簇，消重 42 条；
  4. 08:40 系统标记 12 个簇需要人工确认（8 组 13 薪写法差异、2 组提成/年终奖口径差异、2 组公司名全称与简称）；
  5. 09:00 专员逐个打开簇详情，看成员对照与相似度，合并或拆分；
  6. 09:30 管理员导出 `jobmerge-clusters.csv`（118 行）给检索侧；
  7. 10:00 客户投诉某个岗位名字脱敏后无法核对，管理员去「审计日志」定位导出与复核记录；
  8. 次日 07:40 worker 定时重算一次，过期岗位自动下线。

## 2. 角色与权限

| 角色 | 账号 | 权限 | 典型动作 |
|---|---|---|---|
| 平台管理员 `admin` | `admin@jobmerge.io` | 渠道读写 + 归并 + 复核 + 导出 + 审计 | 维护渠道采集计划与阈值、发起归并、导出清单、查审计 |
| 岗位运营专员 `analyst` | `analyst@jobmerge.io` | 渠道只读 + 归并 + 复核 + 导出 | 发起归并、逐个复核归并簇、导出复核记录 |
| 客户只读 `viewer` | `viewer@jobmerge.io` | 只读（公司名脱敏） | 看头版与归并结果；**不能**发起归并、复核、导出、看审计 |

密码统一：`Demo@2026`。低权角色调用高权接口返回 **403**（真实 HTTP 状态，不是前端隐藏）：

- `POST /api/channels`、`PATCH /api/channels/{id}`：仅 admin（viewer / analyst 均 403）
- `POST /api/runs`、`POST /api/reviews`：admin + analyst（viewer 403）
- `GET /api/exports/*.csv`：admin + analyst（viewer 403）
- `GET /api/audit`：仅 admin（viewer / analyst 403）
- 无 token → 401；非法参数 → 422；重复自然键（渠道编码）→ 409

## 3. 业务模块表（6 个）

| # | 模块 | 对应页面 | 后端 services / controller | 主要 API |
|---|---|---|---|---|
| ① | 渠道与采集配置 | 渠道与采集 | `channel_service` / `channel_controller` | `GET/POST /api/channels`、`PATCH /api/channels/{id}` |
| ② | 归一解析（薪资包/公司/职位词干） | 原始岗位（+ 口径试算） | `salary_norm`（算法 A：单条来源薪资包）、`salary_package`（归并侧选包）、`normalize_service` / `post_controller`、`salary_controller` | `GET /api/posts`、`GET /api/posts/{id}`、`POST /api/salary/normalize`、`GET /api/salary/samples`、`GET /api/salary/breakdown` |
| ③ | 指纹与分块 | 归并结果（分块面板） | `dedupe`（算法 B 的 blocking）、`merge_service` / `run_controller` | `POST /api/runs`、`GET /api/runs`、`GET /api/runs/{id}` |
| ④ | 相似度归并（golden record） | 归并结果 | `dedupe.build_clusters`、`merge_service`、`cluster_service` / `cluster_controller` | `GET /api/clusters`、`GET /api/clusters/{id}` |
| ⑤ | 人工复核（合并 / 拆分 / 保持 + 选定薪资来源） | 复核与导出 | `review_service` / `review_controller`、`salary_review_service` | `GET /api/reviews/pending`、`GET /api/reviews`、`POST /api/reviews`、`POST /api/clusters/{id}/salary` |
| ⑥ | 结果导出、对账与审计 | 复核与导出（导出面板 + 对账 + 审计） | `export_service`、`reconcile` / `reconcile_service`、`audit_service` / `export_controller`、`audit` 路由 | `GET /api/exports/{clusters,cluster-sources,posts,reviews,runs}.csv`、`GET /api/clusters/reconcile`、`GET /api/audit` |

> 登录（`auth_service`）、总览（`overview_service`）、限流与审计中间件属于横切能力，不计入业务模块。

## 4. 页面（6 个）

| # | 路由 | 页面 | 说明 |
|---|---|---|---|
| 1 | `#/login` | 登录 · 取报单 | 报头 + 双栏导语 + 虚线取报单表单 |
| 2 | `#/overview` | 头版总览 | 头条综述、四个报眼数字、薪资口径分布、渠道来稿量、近 7 日归并、最新运行、成员最多簇 |
| 3 | `#/channels` | 渠道与采集 | 过滤条 + 检字表（采集计划/已入库/最近采集）+ 详情抽屉 + 登记渠道 |
| 4 | `#/posts` | 原始岗位 | 薪资原值 / 周期 / 固定月薪 / 浮动 / 可比中位对照 + 岗位详情（换算过程）+ **算法 A 口径试算** + 周期与浮动筛选 |
| 5 | `#/clusters` | 归并结果 | 归并簇表（薪资包状态 + 可否对外发布）+ 成员对照抽屉（每条来源独立折算、差异清单、选定来源）+ 发起归并（阈值）+ 导出 |
| 6 | `#/reviews` | 复核与导出 | 待复核队列 + 计数对账面板 + 复核历史 + 5 个 CSV 导出 + 审计日志（仅 admin） |

共用组件：`frontend/site/js/ui.js`（`table` / `drawer` / `field` / `badge` / `barList` / `trendChart`）与
`frontend/site/js/components.js`（`filterBar` / `clusterTable` / `openClusterDrawer` / `salaryRange`），
被 4 个业务页共用（渠道/岗位/归并/复核）。

## 5. 快速启动

```bash
cp .env.example .env
docker compose up -d --build      # 等 5/5 healthy
open http://localhost:18200
```

首次启动 backend 自动建表并执行一次 seed（`SEED_DEMO=true`）。seed 幂等，可重复执行：

```bash
docker compose exec -T backend python -m scripts.seed_demo
# SEED_SUMMARY brand=jobmerge users=3 sources=4 runs=1 findings=118 pending=9
```

## 6. 访问地址

| 服务 | 地址 |
|---|---|
| 前端 | http://localhost:18200 |
| 后端 API 文档 | http://localhost:19200/docs |
| 健康检查 | http://localhost:19200/api/health |
| 数据库映射 | localhost:17700 |

## 7. 技术栈

| 层 | 选型 |
|---|---|
| 前端 | 原生 HTML5 + CSS（oklch 令牌 / 报版栅格）+ ES Modules；无框架、无打包、无 CDN 脚本（仅 Google Fonts） |
| 后端 | Python 3.11、FastAPI 0.115、SQLAlchemy 2.0、PyJWT、passlib(bcrypt) |
| 异步 | Celery 5.4 + Redis（10 秒心跳、每日 07:40 归并重算） |
| 数据库 | PostgreSQL 16 |
| 部署 | Docker Compose，恰好 5 服务 |

## 8. 目录

```text
backend/
  src/config/{app,database,settings,celery_app}.py
  src/constants/{enums,roles,limits,error_codes,log_templates}.py
  src/models/{user,channel,post,cluster,run,review,audit}.py
  src/schemas/{auth,channel,cluster,run,salary,common}.py
  src/services/
    salary_norm.py       # 算法 A：单条来源 → 薪资包（纯函数）
    salary_package.py    # 算法 A 归并侧：从多条来源选出一条完整一致的薪资包（纯函数）
    salary_review_service.py # 人工选定来源作为对外薪资包
    reconcile.py / reconcile_service.py # 页面 / 复核 / 导出三方对账
    normalize_service.py # 公司名 / 职位词干 / 城市 / 学历经验归一
    dedupe.py            # 算法 B：分块 + 相似度 + 并查集聚类
    merge_service.py     # 归并运行落库
    channel_service.py post_service.py cluster_service.py review_service.py
    run_service.py overview_service.py export_service.py audit_service.py auth_service.py
  src/controllers/ src/routes/ src/middlewares/
  scripts/{seed_demo.py,demo_config.py,worker_healthcheck.sh}
  migrations/  tests/
frontend/site/{index.html,css/{tokens,app}.css,js/{api,app,config,store,ui,components}.js,js/pages/*.js}
```

## 9. 环境变量

见 `.env.example`：`COMPOSE_PROJECT_NAME`、`FRONTEND_PORT`、`BACKEND_PORT`、`DB_PORT`、`DB_*`、`JWT_SECRET`、`REDIS_URL`、`SEED_DEMO`、`RATE_LIMIT_*`、`APP_TIMEZONE_OFFSET_MINUTES`。

## 10. 核心算法与口径

### 算法 A｜薪资口径归一（`backend/src/services/salary_norm.py`）

输入一条薪资原值，输出一个**薪资包**（不再只折出一个数）：

- `status`：`parsed / negotiable / unparsed`；
- `period`：`month / year / day`（月薪缺省；`年薪 / 年包 / /年` → 年薪；`日薪 / 元/天 / /天` → 日薪）；
- `months / months_explicit`：发薪月数 `N薪`（缺省 12，合法 12–24），并标明是否原值明确写出；
- `quoted_low/high`：原值区间（换算前），任何情况下都原样保留；
- `fixed_monthly_low/high`：固定收入（底薪 / 基本工资 / 固定工资）折月；
- `variable_items`：提成 / 津贴 / 奖金 / 绩效等浮动项目，含原值、周期、是否量化；
- `variable_monthly_low/high`：**只有量化得出来**的浮动收入才折月，算不出来的只打标；
- `total_monthly_low/high`：固定 + 已量化浮动；
- `comparable_monthly_low/high/median`：用于排序的单一可比口径（有总额取总额，否则取固定）；
- `has_variable / variable_scope`：是否含浮动，以及浮动是可比的哪一档；
- `basis_steps / norm_basis`：逐步换算过程（字符归一 → 发薪月数 → 周期 → 折月 → 浮动 → 可比口径）。

换算规则：

1. 字符归一：NFKC 全角→半角，`～ ~ — – 至` → `-`，统一逗号、去多余空白；
2. 月薪：`名义区间 × 12 ÷ months`；年薪：`÷ 12`；日薪：`× 21.75`（法定月平均工作日）；
3. 同一原值同时出现年薪与日薪 → `unparsed`（周期矛盾）；`low > high` → `unparsed`（区间矛盾）；
4. 折月后超出 500–500000 或识别不出金额 → `unparsed`；面议 → `negotiable`；
5. **绝不跨来源拼区间、绝不把提成或年终奖塞进底薪**：浮动金额单独放在 `variable_*`，并标注是否量化；
6. 原值、原值区间、发薪月数、每一步换算都进 `salary_package`（JSON 落库），导出时原样带出。

验收样例（与 `/api/salary/normalize` 返回一致）：

| 原值 | 周期 | 固定月薪 | 浮动口径 | 可比月薪中位 | status |
|---|---|---|---|---|---|
| `8-12K·13薪` | 月薪 · 13 薪 | 7385–11077 | 无浮动 | **9231** | parsed |
| `年薪18万` | 年薪 | 15000–15000 | 无浮动 | **15000** | parsed |
| `300元/天` | 日薪 | 6525–6525 | 无浮动 | **6525** | parsed |
| `底薪8000+提成` | 月薪 | 8000–8000 | 提成未量化，不计数 | **8000** | parsed |
| `月薪8000-10000+年终奖2万` | 月薪 | 8000–10000 | 年终奖 20000÷12=1667 已量化 | **10667** | parsed |
| `综合月薪8000-10000（含提成）` | 月薪 | 不可拆分 | 总额已含浮动 | **9000** | parsed |
| `面议` | — | — | — | `null` | negotiable |
| `12-8K` | — | — | — | `null` | unparsed（区间矛盾） |
| `年薪18万+300元/天` | — | — | — | `null` | unparsed（周期矛盾） |

### 算法 A 归并侧｜归并簇的薪资包选择（`backend/src/services/salary_package.py`）

1. 每条来源独立归一，形成自己的薪资包；**不做 min/max、不做区间并集**；
2. 只有 `parsed` 且折月区间完整的来源才是候选；
3. 候选之间比较「薪资包签名」：发薪月数 + 固定月薪区间 + 浮动口径 + 含浮动月薪区间；
   签名一致 = 同一薪资包（`10-15K` 与 `月薪10000-15000元`、`年薪18万` 与 `15K` 等价）；
4. 一致时只采用**一条**来源（浮动更量化 → 月数/区间显式 → 置信度高 → 发布新 → id 小），
   其余来源仍保留原值与换算过程；
5. 不一致（月数不同、提成/底薪口径不同、部分来源面议或不可解析）→ `inconsistent`：
   不输出对外薪资，进入人工复核，`salary_differences` 列出每种口径与涉及渠道；
6. 全部来源不可比 → `noncomparable`：明确标注，不参与排序与发布。

簇的 `salary_low/high/monthly_median/salary_basis` 只来自被采用的那一条来源；
`publishable` 由「薪资包可比 + 未过期 + 未被拆分 + 已复核」共同决定。

### 算法 B｜重复岗归并（`backend/src/services/dedupe.py`）

1. 归一：`company_norm`（去括号地域标注 + 去法人后缀 + 小写）、`title_stem`（去括号补充 + 去招聘噪声词 + 去标点）、
   `city`（去「市/省」）、`degree/experience` 枚举化；
2. blocking key = `company_norm + city + salary_bucket`，`salary_bucket = floor(monthly_median / 5000)`，同块内才两两比较；
3. 相似度：`0.45*title_jaccard + 0.25*company_sim + 0.20*salary_overlap + 0.10*attr_match`
   - `title_jaccard`：职位词干的字符集 Jaccard（中文不分词，见 §已知简化）
   - `company_sim`：归一后字符串相等 = 1.0，前缀包含 = 0.92，其余用 `SequenceMatcher` 比值
   - `salary_overlap`：两段月薪区间的交集/并集；双方都不可比 = 0.6，单方不可比 = 0
   - `attr_match`：学历与经验各占 0.5，相等 = 1.0，任一方「不限」= 0.7
4. `score >= threshold`（默认 0.82）连边，并查集聚类；
5. golden record = 「字段最全 → 发布最新 → id 最小」；簇置信度 = 簇内两两相似度均值；
6. 输出 `member_count`、`dup_removed`、`confidence`、`needs_review`
   （薪资包不一致或公司写法不一致时为 true；全部来源不可比只标注、不占复核队列）；
7. 薪资包选择见上一节，`blocking_key` 与 `salary_overlap` 使用每条来源自己的可比月薪。

seed 数据实算：160 条原始岗位 → **118 簇**（21 个多成员簇、最大 3 条、消重 **42** 条），
其中 12 个多成员簇被标记为待人工复核，8 个簇因过期下线。

同一次运行的薪资包对账（页面、复核、导出必须一致）：

| 指标 | 数量 |
|---|---|
| 归并簇 | 118 |
| 薪资包可比（单来源采用） | 89 |
| 多来源不一致待复核 | 10 |
| 全部来源不可比 | 19 |
| 三者之和 | 118 |
| 待复核簇 / 已复核 / 待复核队列 | 12 / 3 / 9 |

`GET /api/clusters/reconcile` 会把「薪资包三档之和 = 簇总数、导出行数 = 簇总数、
待复核 + 已复核 = 待复核标记数、来源明细覆盖全部成员、可比簇各采用一条来源」逐项核对并返回 `balanced`。

## 11. 共享枚举出现位置

| 枚举 | 后端 | 前端 |
|---|---|---|
| 角色 `admin/analyst/viewer` | `backend/src/constants/enums.py`、`constants/roles.py` | `frontend/site/js/config.js`（`ROLE_LABELS` / `PERMISSIONS`） |
| 薪资口径状态 `parsed/negotiable/unparsed` | `constants/enums.py`（`ParseStatus`） | `config.js`（`ENUMS.parseStatus`、`parseTone`） |
| 计价周期 `month/year/day` | `constants/enums.py`（`PayPeriod`） | `config.js`（`ENUMS.payPeriod`） |
| 簇薪资包状态 `comparable/inconsistent/noncomparable` | `constants/enums.py`（`SalaryStatus`） | `config.js`（`ENUMS.salaryStatus`、`salaryTone`） |
| 浮动口径 `none/fixed_only/unquantified/quantified/included_unquantified` | `constants/enums.py`（`VariableScope`） | `config.js`（`ENUMS.variableScope`） |
| 归并簇状态 `active/expired/merged` | `constants/enums.py`（`ClusterStatus`） | `config.js`（`ENUMS.clusterStatus`、`statusTone`） |
| 复核结论 `merge/split/keep` | `constants/enums.py`（`ReviewDecision`） | `config.js`（`ENUMS.decision`、`decisionTone`） |
| 运行状态 `queued/running/success/partial/failed` | `constants/enums.py`（`RunStatus`） | `config.js`（`ENUMS.runStatus`） |
| 触发方式 `manual/schedule/seed` | `constants/enums.py`（`TriggerKind`） | `config.js`（`ENUMS.trigger`） |
| 渠道类型 `site/api/file/manual` | `constants/enums.py`（`ChannelKind`） | `config.js`（`ENUMS.channelKind`） |
| 学历 `any/college/bachelor/master/doctor` | `constants/enums.py`（`Degree`） | `config.js`（`ENUMS.degree`） |
| 经验 `any/1-3/3-5/5-10/10+` | `constants/enums.py`（`Experience`） | `config.js`（`ENUMS.experience`） |

## 12. Docker 说明

- 5 个服务：`frontend`(Nginx 静态站) / `backend`(uvicorn) / `worker`(Celery) / `db`(PostgreSQL 16) / `redis`，全部带 healthcheck。
- 命名卷：`db_data`、`redis_data`；`service_healthy` 依赖；端口 `${FRONTEND_PORT:-18200}` 等写法。
- Nginx：`location /api/ { proxy_pass http://backend:8000/; }` + SPA 回落。
- 收尾：`docker compose down -v --remove-orphans`。

## 13. 已知简化

见 `test-artifacts/gb-611/TESTING.md`「已知差异」：字符集 Jaccard 代替分词、单个簇只保留一条有效复核结论、渠道采集以 seed 数据模拟（未接真实爬虫）。

薪资包口径的已知简化：

- 日薪统一按 21.75 个工作日/月折月（不区分大小月与加班）；
- 提成只识别百分比/固定金额，「按业绩比例、无基数」不折算，只打标；
- 年终奖若原值未写周期，按「按年」处理；未写金额的年终奖不计数；
- `needs_review` 仍由公司名写法与薪资包不一致共同触发；全部来源不可比的簇只标注、不进复核队列。

## License

内部演示项目，仅用于评测与教学。
