# ALE 实验工作台（ALE Workbench）

原子层刻蚀（ALE）实验的本地科研数据工作台：**录入 → 快照 → 导出/导入 → 数据体检**全程可追溯，桌面网页版与手机网页版并列共存，共用同一套 API 与数据库。

- 桌面版：`/quick`（实验快录）、`/quick-history`（历史）、`/quick-dataset`（数据集）、`/professional`（专业模式）
- 移动版：`/m/quick`、`/m/history`、`/m/dataset`、`/m/me`（PWA 可添加到主屏幕）
- 后续可按 `docs/ale_v2_2/05_mobile_web.md` 升级为 App（Capacitor 套壳）或微信小程序（uni-app）

## 核心能力

| 能力 | 说明 |
|---|---|
| 实验快录 | 一行 = 一次 Run；支持 A/B/C 三个反应源，源与其 Pulse / ΔP / Purge / Wait 整体绑定；ΔP 支持单值或 `70–100` 区间 |
| 结果与派生值 | 膜厚前/后 → 净减薄与 EPC 确定性计算，不接受手填；质量状态、结果标签、建模标记独立留痕 |
| Excel 往返 | 33 列主表（含反应物C）+「记录明细 / 源步骤明细 / 结果明细」三张明细表；导出字段与网页录入一一对应 |
| 批量导入 | 可直接上传原记录表：自动定位表头行，列顺序、空格、全角符号、28/33 列差异均兼容；预览 → 勾选 → 单事务入库 |
| 数据体检 | 可训练性、缺失字段、单位审计、泄漏分组；只读检查，不训练、不预测 |
| 双端共存 | 桌面与移动端同一账户、同一份数据；移动端保存后电脑端立即可见 |

## 技术栈

- 后端：Python 3.14、FastAPI 0.119、Pydantic 2、SQLAlchemy 2（Core 反射，无 ORM 迁移框架）、PyMySQL、PyJWT + Argon2
- 数据库：MySQL 8.4（默认端口 `3307`，库名 `ale_workbench`）
- 前端：Vue 3.5、Vite 7、TypeScript、Element Plus、ECharts、lucide 图标
- 契约：OpenAPI 3.1（`api/openapi/`），版本 1.8.0

## 目录结构

```
ALE_AI/
├─ backend/            FastAPI 应用（app/）、测试（tests/）、依赖（requirements.txt）
│  ├─ app/             路由与业务：quick*.py、auth.py、config.py …
│  ├─ tests/           pytest（真实 MySQL + 事务回滚）
│  └─ .env.example     环境变量模板
├─ frontend/           Vue 3 + Vite
│  ├─ src/views/       桌面页面
│  ├─ src/mobile/      移动端页面（/m）
│  └─ public/          manifest、图标
├─ database/
│  ├─ sql/             建库 DDL
│  ├─ migrations/      增量迁移 0001–0016
│  ├─ apply_schema.py  建库 + 建账号 + 校验
│  ├─ migrate.py       迁移应用与状态核对
│  └─ .dbcreds.example 管理员凭据模板
├─ api/                OpenAPI 契约与生成产物
├─ docs/ale_v2_2/      字段字典、Excel 映射合同、API 合同、移动端与升级路径
├─ start-workbench.ps1 Windows 启动器（进程身份校验、指纹记录）
└─ 启动工作台.cmd      双击入口（转发上面的 ps1）
```

## 快速开始（Windows）

### 1. 环境要求

- Python 3.14（建议虚拟环境放在 `backend/.venv-win`，与启动器一致）
- Node.js 20+
- MySQL 8.4，监听 `127.0.0.1:3307`

### 2. 获取代码并安装依赖

```powershell
git clone <your-repo-url> H:\ALE_AI
cd H:\ALE_AI

python -m venv backend\.venv-win
backend\.venv-win\Scripts\python.exe -m pip install --only-binary=:all: -r backend\requirements.txt

cd frontend
npm ci
npm run build      # 产出 frontend/dist，启动器要求它存在
```

### 3. 建库与账号

```powershell
# 先在 database\.dbcreds 写入 MySQL 管理员凭据（参考 .dbcreds.example）
python database\apply_schema.py
```

脚本会建库、建 `ale_app` / `ale_ro` 账号、生成随机强密码写入 `database\.appcreds`（不入库）。

### 4. 配置环境变量

```powershell
Copy-Item backend\.env.example backend\.env
# 编辑 backend\.env，至少填写 ALE_JWT_SECRET（≥32 字符）
python -c "import secrets;print(secrets.token_urlsafe(48))"
```

完整变量说明见 **[docs/配置与部署.md](docs/配置与部署.md)**。

### 5. 应用迁移

```powershell
backend\.venv-win\Scripts\python.exe database\migrate.py --status   # 先看状态
backend\.venv-win\Scripts\python.exe database\migrate.py            # 应用（自动备份）
```

### 6. 创建首位管理员

```powershell
# 生成一次性初始化访问码
python -c "import secrets;print(secrets.token_urlsafe(24))" > backend\.setup-code
```

打开 `http://127.0.0.1:8001/login`，页面会进入「初始化工作空间」，填入上面这串访问码即可创建管理员。

### 7. 启动

```powershell
.\启动工作台.cmd
# 或指定端口
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-workbench.ps1 -Port 8001
```

默认入口 `http://127.0.0.1:8001/login`；移动版 `http://127.0.0.1:8001/m`。

> 启动器会校验监听进程身份与源码/构建指纹，端口被其他程序占用时拒绝启动而不是强杀进程。

## 前端开发

```powershell
cd frontend
npm ci
npm run dev      # http://127.0.0.1:5173，/api 代理到 127.0.0.1:8001
npm run build    # 类型检查 + 产物，后端直接托管 dist
```

## 测试

测试使用独立库 `*_test` 与真实 MySQL 事务回滚，不写生产库。

```powershell
# 首次：由生产库克隆结构（不复制业务数据）
backend\.venv-win\Scripts\python.exe database\setup_test_env.py --target ale_workbench_test

cd backend
$env:ALE_DB_NAME="ale_workbench_test"; $env:ALE_REQUIRE_TEST_DB="1"
.venv-win\Scripts\python.exe -m pytest tests\test_quick_v22.py -q
```

## 配置要点

| 项 | 位置 | 是否入库 |
|---|---|---|
| JWT 密钥、部署标识、数据库连接 | `backend/.env` | 否（`.env.example` 提供模板） |
| MySQL 管理员凭据 | `database/.dbcreds` | 否 |
| 应用账号凭据（自动生成） | `database/.appcreds` | 否 |
| 初始化访问码 | `backend/.setup-code` | 否 |
| 原始上传文件 | `storage/` | 否 |

**仓库不包含**：`mysql_data/`、`reports/`、`backups/`、`storage/`、`node_modules/`、`frontend/dist/`、虚拟环境。这些目录由本机生成，含真实实验数据或体积过大。

## 安全与数据边界

- 服务默认只监听 `127.0.0.1`；需要手机访问时显式改绑定或走隧道，不要直接暴露到公网。
- 所有凭据、密钥、原始文件均不入版本控制；提交前请确认 `git status` 中没有 `.env` / `.appcreds` / `.setup-code`。
- 数据库 `payload` JSON 是权威快照，显式列只做确定性投影；不重写历史、不覆盖主键。
- 数据体检与 EPC 均为确定性计算，不做训练、不生成预测指标。

## 文档索引

- `docs/ale_v2_2/01_ux_spec_and_field_dictionary.md` 字段字典
- `docs/ale_v2_2/02_schema_and_migration_plan.md` 表结构与迁移
- `docs/ale_v2_2/03_api_contract.md` API 合同
- `docs/ale_v2_2/04_excel_mapping_contract.md` Excel 映射与批量导入合同
- `docs/ale_v2_2/05_mobile_web.md` 移动网页版与 App / 小程序升级路径
- `docs/配置与部署.md` 环境变量、目录、常见故障
- `progress_log.md` 开发进度（按日期倒序）

## 许可

内部科研项目，未声明开源许可；如需对外发布请先确认数据与代码授权。
