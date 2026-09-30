# EduGrader

EduGrader 是一个在本机运行的智慧树作业批阅工具，支持读取 PDF、DOCX
报告并调用 OpenAI 兼容大模型评分。

## 运行环境

- Windows 10/11 或 macOS
- Python 3.9 及以上版本
- Node.js 20 及以上版本

## 首次安装

### macOS

在项目根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium

cd frontend
npm install
npm run build
cd ..
```

### Windows

打开 PowerShell 或命令提示符，进入项目根目录后执行：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium

cd frontend
npm install
npm run build
cd ..
```

如果没有 `py -3` 命令，可将它替换为 `python`。

## 启动

macOS：

```bash
./start.sh
```

Windows：

```powershell
.\start.bat
```

浏览器访问：

```text
http://127.0.0.1:8000
```

停止服务时，在启动窗口按 `Ctrl+C`。

## 1. 系统配置

1. 打开“系统配置”。
2. 选择“智慧树”运行模式。
3. 填写 OpenAI 兼容地址、模型名称和 API Key。
4. 点击“保存配置”。

首次使用可先选择“本地演示”熟悉页面和操作。

![系统配置页面](docs/images/system-config.png)

## 2. 创建批阅任务

1. 打开“新建批阅”，点击“登录”。
2. 在智慧树页面完成登录后，返回 EduGrader 刷新登录状态。
3. 选择课程和作业。
4. 选择已有评分模板并点击“应用模板”，或新建评分细则。
5. 核对评分项及总分。
6. 选择“仅未批”或“全部提交”。
7. 按需开启“写入前人工确认”和“写入智慧树”。
8. 点击“创建并开始”，确认任务信息。

关闭“写入智慧树”时，评分结果只保存在本机，可用于试运行。

![新建批阅和评分细则](docs/images/new-grading.png)

## 3. 新建评分模板

1. 点击“新建细则”。
2. 粘贴评分要求，或导入 PDF、DOCX、TXT、MD 文件。
3. 点击“生成结构化细则”。
4. 修改评分项，并确认评分项合计等于作业总分。
5. 点击“保存为模板”，填写模板名称。

模板可在评分模板区域编辑或删除。

## 4. 查看评分结果

打开“任务中心”并选择任务，可查看：

- 任务进度及完成、待复核、跳过、失败数量。
- 每名学生的分数、状态和处理原因。
- 评分细则及评分记录。
- 可恢复项重试和修改后重批。

![任务中心和处理状态](docs/images/task-center.png)

## 5. 复核和手工评分

- 点击“待复核”查看需要确认的模型评分。
- 点击学生记录后的“复核”，修改分数或评语后确认。
- 在“未完成”中点击“手工评分”，可直接填写最终总分和评语。
- 已完成的学生记录可查看和导出。

## 6. 删除任务

在任务详情右上角点击“删除任务”。运行中的任务需要先暂停。

删除只会移除本机任务记录，不会撤销已经写入智慧树的成绩。

## 扫描版 PDF

普通 PDF 无需额外配置。扫描版 PDF 需要安装 Tesseract OCR 和简体中文
语言包。

macOS：

```bash
brew install tesseract tesseract-lang
```

Windows：安装 Tesseract OCR，勾选简体中文语言数据 `chi_sim`，并将安装
目录加入系统 `PATH`。

## 常见问题

### 页面无法打开

确认启动窗口没有报错，并检查是否正在访问
`http://127.0.0.1:8000`。

### 无法启动 Chromium

macOS：

```bash
.venv/bin/python -m playwright install chromium
```

Windows：

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

### 登录状态失效

返回“新建批阅”，重新点击“登录”并刷新登录状态。

### 大模型请求失败

检查 API 地址、模型名称、API Key 和网络连接。
