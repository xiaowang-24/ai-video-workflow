# AI Video Workflow · 三层锁长视频工作流

> 用「资产锁定」解决 AI 视频最大的三个痛点：**人物不换脸 · 产品不变形 · 镜头不跳变**。

一套面向长视频（30 秒以上、多镜头）的 AI 生成工作流：先把人物、产品、场景、声音做成**带角度参考图的锁定资产**，再让后续每一帧、每一个镜头都只能引用这些资产 ID，模型没有"自由发挥"的空间。

前后端一体，启动即用，自带网页操作台，不需要单独部署前端。

---

## 核心设计：三层锁 + 资产 ID

传统的 AI 视频工具是「一句提示词 → 一段视频」，镜头一多，人物和产品就会漂移。本项目换了个思路：**先建立一致性锚点，再生成画面**。

| 层 | 资产 ID | 作用 | 角度视图 |
|---|---|---|---|
| 人物锁 | `CHAR_001` | 固定脸型、发型、五官、服装 | 正脸 / 3/4 侧 / 正侧面 / 半身 / 全身 / 服装细节 |
| 产品锁 | `PROD_001` | 固定包装、颜色、材质、Logo | 正面 / 侧面 / 背面 / 顶视 / 45° / Logo 特写 |
| 场景锁 | `SCENE_001` | 固定空间关系与光线基调 | 全景 / 局部 |
| 声音锁 | `VOICE_001` | 固定音色，全片统一 | CosyVoice 声纹提取 |

流程是 **生成 → 人工确认 → 锁定**。锁定后 `locked: true`，后续接口一律禁止改写该资产（会直接返回 409 类错误），从数据层面杜绝"越生成越不像"。

项目状态机：

```
created  ──生成资产──▶  assets_ready  ──人工锁定──▶  assets_locked
```

## 四组独立 API 通道

不绑定任何一家模型厂商。设置页里四组通道各自填 **Base URL + API Key + 模型名**，互不干扰，可以混搭（比如 LLM 用 DeepSeek、视频用可灵、配音用 CosyVoice）：

| 通道 | 用途 | 兼容示例 |
|---|---|---|
| `llm` | 生成描述、提示词、分镜脚本 | OpenAI / DeepSeek / 任意 OpenAI 兼容接口 |
| `image` | 多角度参考图生成 | OpenAI 兼容生图、即梦多参考 |
| `video` | 视频片段生成 | Veo 3 / Sora 2 / 可灵 Kling / Seedance / 即梦 |
| `audio` | 配音、声纹克隆 | 阿里云百炼 CosyVoice |

配置只落在本机 `backend/storage/settings.json`，不上传任何第三方。留空则自动进入 **演示模式（Mock）**：用 Pillow 合成带角度标注的占位图，整条链路照样能跑通，方便先看流程再接真 Key。

内置 `services/model_catalog.py` 模型能力目录，自动判断某模型是否支持**原生音视频**（Veo、Sora）还是**纯画面需后期配音**（Kling、Seedance、即梦），并给出智能提示——但最终填什么模型由你决定，目录只做推荐。

## 已实现 / 规划中

- ✅ **Step 0 创建项目**：标题、创意简述、目标时长、六类素材上传（人物图 / 产品图 / 场景图 / 配音音频 / 背景音乐 / 参考视频）
- ✅ **Step 1 主资产生成**：多角度视图批量生成、AI 自动写结构化描述、单个角度重生成、源图替换
- ✅ **Step 1.5 资产锁定**：逐项人工核对后锁定，建立一致性锚点
- ✅ **设置页**：四通道配置 + 模型能力探测 + 视频声音来源策略（auto / native / tts）
- ✅ **网页操作台**：单页应用，全流程点选操作，无需 Postman
- ⏳ **Step 3 起**：分镜规划、首尾帧、5 秒片段生成、配音合成、成片串联（接口位已预留，逐步实现）

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | FastAPI 0.115 + Uvicorn + Pydantic v2 |
| 前端 | 原生单页 + Tailwind CDN，由 FastAPI 直接托管 |
| AI 编排 | OpenAI 兼容协议 + 火山方舟 + 阿里云百炼 |
| 图像处理 | Pillow（演示模式占位图、多角度模拟、光照与透视变换） |
| 异步 | asyncio（轻量实现，后续可平滑升级 Celery） |
| 存储 | 本地文件系统 + JSON 单事实源（无需数据库） |

## 目录结构

```
ai-video-workflow/
├── backend/
│   ├── app/
│   │   ├── config.py            # 从 .env 加载配置、初始化存储目录
│   │   └── main.py              # FastAPI 入口、静态托管、CORS
│   ├── routers/
│   │   ├── upload.py            # 素材上传
│   │   ├── projects.py          # 项目 + 主资产 + 锁定（核心）
│   │   ├── archive.py           # 早期档案卡接口（Step 1 雏形，兼容保留）
│   │   └── settings.py          # 四通道配置 + 模型能力探测
│   ├── services/
│   │   ├── model_catalog.py     # 模型能力目录（音视频原生 / 需配音 / 多参考生图）
│   │   ├── image_service.py     # 多角度生图 + Provider 抽象 + Mock 实现
│   │   ├── openai_service.py    # LLM 结构化描述生成
│   │   ├── volcano_service.py   # 火山方舟（可灵 / Seedance）
│   │   ├── cosyvoice_service.py # 声纹提取与配音
│   │   └── storage.py           # 文件落盘
│   ├── models/schemas.py        # Pydantic 数据模型
│   ├── static/index.html        # 网页操作台（单页）
│   ├── requirements.txt
│   └── .env.example
├── frontend/                    # 预留：独立 Next.js 前端（当前由 static 托管）
├── storage/                     # 预留：素材与产物根目录
└── docs/                        # 设计文档
```

> 运行时数据统一落在 `backend/storage/`（素材、项目 JSON、settings.json、成片），已在 `.gitignore` 中排除。

## 快速开始

```bash
# 1. 进入后端目录
cd backend

# 2. 创建并激活虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 准备配置
cp .env.example .env      # Windows: copy .env.example .env
# 用编辑器填入 OPENAI_API_KEY / VOLCANO_ACCESS_KEY / ALIYUN_ACCESS_KEY_ID 等

# 5. 启动
python -m app.main
```

打开：

- 网页操作台 → <http://localhost:8000>
- 交互式 API 文档 → <http://localhost:8000/docs>

Windows 下也可以双击根目录的 `start.bat`，脚本会自动建虚拟环境、装依赖、复制 `.env` 并打开浏览器。

**最小可跑通配置**：只想看界面和流程，一个 Key 都不用填——直接启动，系统会自动进入演示模式。

## API 一览

**素材**

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/upload` | 上传图片 / 音频，返回 `file_id` |
| GET | `/api/upload/uploads/{file_id}` | 取回文件 |

**项目与主资产（核心）**

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/projects` | 创建项目（含六类素材上传） |
| GET | `/api/projects` | 项目列表 |
| GET | `/api/projects/{pid}` | 项目详情（含资产与锁定状态） |
| PUT | `/api/projects/{pid}` | 修改标题 / 创意简述等 |
| POST | `/api/projects/{pid}/generate-assets` | 批量生成 CHAR / PROD / SCENE / VOICE 资产及多角度图 |
| POST | `/api/projects/{pid}/lock` | **锁定资产**（锁定后不可改） |
| POST | `/api/projects/{pid}/assets/{asset_id}/angles/{angle}/regenerate` | 单角度重生成 |
| POST | `/api/projects/{pid}/assets/{asset_id}/replace-source` | 替换源图并重建角度 |

**设置**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET / PUT | `/api/settings` | 读写四通道配置 |
| GET | `/api/settings/video-models` | 视频模型能力目录 |
| POST | `/api/settings/video-models/detect` | 按模型名探测是否原生音频 |
| GET | `/api/settings/image-models` | 图像模型目录 |
| POST | `/api/settings/image-models/detect` | 探测是否支持多参考生图 |

**档案卡（Step 1 早期接口，兼容保留）**

`POST /api/archive/create` · `GET/PUT /api/archive/{id}` · `POST /api/archive/{id}/confirm` · `POST /api/archive/{id}/regenerate-{character|product}-angle/{angle}`

## 安全与隐私

- `.env`、`backend/storage/`（含 `settings.json` 里的真实 Key 与用户上传素材）已加入 `.gitignore`，**不会被提交**
- 所有 Key 仅存本机，服务不做任何外发遥测
- 生产部署建议：关闭 `main.py` 中的 `allow_origins=["*"]`，并在反向代理层加鉴权
- 素材涉及真实人脸时，请注意当地的肖像权与深度合成合规要求

## License

[MIT](LICENSE)
