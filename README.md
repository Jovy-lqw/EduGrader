# EduGrader

本地单用户智慧树作业批阅工具。系统读取学生提交中的 PDF 报告，调用
OpenAI 兼容大模型生成评分，并可写回未发布成绩。

## 安全边界

- 只处理作业，不读取或操作考试。
- 只解析 PDF；其他附件仅记录为已忽略。
- 不保存智慧树密码，登录和验证码均在官方页面完成。
- 不调用成绩发布接口。
- 写入前校验自动发布已关闭；无法确认时整批停止。
- 每次写入前检查提交和远端成绩冲突，写入后回读分数及发布状态。
- 无 PDF、解析失败、模型校验失败或远端冲突时跳过，不盲目写入。

## 环境

- macOS
- Python 3.9+
- Node.js 20+
- Chromium（由 Playwright 安装）
- 可选：Tesseract + `chi_sim`，用于扫描版 PDF OCR

## 首次安装

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium

cd frontend
npm install
npm run build
cd ..
```

扫描版 PDF 需要额外安装 OCR：

```bash
brew install tesseract tesseract-lang
```

未安装 OCR 时，文本型 PDF 不受影响；扫描版 PDF 会被跳过且不会写入成绩。

## 启动

```bash
./start.sh
```

浏览器打开：

`http://127.0.0.1:8000`

首次使用流程：

1. 在“系统配置”填写 OpenAI 兼容 API 地址、模型和 API Key。
2. 回到“新建批阅”，点击“登录”，在官方智慧树页面完成鉴权。
3. 选择课程和作业，粘贴评分细则并核对结构化评分项。
4. 确认智慧树该作业的自动发布已关闭。
5. 选择批阅范围、人工确认开关和是否写入，然后启动任务。

API Key 保存在 `data/secrets.json`，文件权限为当前用户可读写；也可通过
`EDUGRADER_LLM_API_KEY` 环境变量提供，环境变量优先。

## 演示模式

在“系统配置”把运行模式切到“本地演示”，可在不登录智慧树的情况下检查
课程、作业和 PDF 流程。评分仍调用已配置的大模型。

## 验证

```bash
.venv/bin/python -m unittest discover -s tests -v
cd frontend && npm run build
```

## 本地数据

- `data/edugrader.db`：任务、评分结果和审计记录
- `data/settings.json`：非敏感配置
- `data/secrets.json`：大模型密钥
- `browser-profile/`：智慧树浏览器登录态
- `downloads/`：任务临时文件；默认评分后删除 PDF

上述目录均已加入 `.gitignore`。
