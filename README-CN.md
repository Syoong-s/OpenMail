# TeleMail

一款多种收件箱界面的邮件客户端，多账号统一管理。支持 Windows 11 (x64) 与 Linux (x86-64) ，所有邮件数据、账号凭据与附件预览均在本地完成，不依赖项目自建云服务或遥测上传。它支持 IMAP/SMTP 多账号管理、智能收件箱分类、自定义过滤规则、对话流视图、通讯录、稍后发送以及基于内置 PDF.js 的离线文档预览。

---

## 使用方法

### 1. 安装与启动

可从 GitHub Releases 下载对应平台的发行包（当前版本 `0.55.2`），或在 Linux 下直接从源码启动：

| 发行包 | 运行依赖 | 是否自动安装依赖 |
| --- | --- | --- |
| Windows 11 x64 ZIP | 已内置 Python、GTK、OpenSSL 和 Antiword；系统需具备 Microsoft Edge WebView2 Evergreen Runtime。 | 标准 Windows 11 已预装 WebView2，通常无需额外安装；若缺失，需手动安装，TeleMail 不会自动安装。启动前须完整解压 ZIP。 |
| Debian / Ubuntu amd64 DEB | Python 3.12+、GTK 3.24+、Fontconfig、OpenSSL 3、WebKitGTK 4.1、SVG 加载器（`librsvg2-common`）及 glibc >= 2.34；预览旧式 `.doc` 文件另需可选组件 `antiword`。 | 使用 `sudo apt install ./telemail-desktop_0.55.2_amd64.deb` 时，apt 会安装已声明的依赖，前提是配置的软件源提供兼容版本；`antiword` 未声明为依赖，需在需要 `.doc` 预览时单独安装。 |
| Linux x86-64 可移动 tar.gz | Python 3.12+、GTK 3.24+、Fontconfig、OpenSSL 3、WebKitGTK 4.1、SVG 加载器及 glibc >= 2.34；预览旧式 `.doc` 文件另需可选组件 `antiword`。 | 不会。启动前需手动安装缺失的系统依赖；解压或运行程序均不会自动安装。 |

实际最低 glibc 版本取决于构建主机，不能保证兼容所有旧版 Linux 发行版，详见[构建指南](docs/BUILDING.md)。

- **Windows 11 (x64)**
  解压 `telemail-0.55.2-windows-amd64.zip`（请保留完整目录结构），双击运行 `TeleMail-Windows-amd64/TeleMail.exe`。包内已自带 Python 与 GTK 运行时，无需安装 Python 或 WSL，仅需系统具备 Microsoft Edge WebView2 Evergreen Runtime。
- **Debian / Ubuntu (amd64)**
  安装 `telemail-desktop_0.55.2_amd64.deb`（系统包管理器会自动处理依赖），完成后可从桌面应用菜单或终端执行 `telemail` 启动：
  ```bash
  sudo apt install ./telemail-desktop_0.55.2_amd64.deb
  ```
- **Linux 通用可移动包 (x86-64)**
  解压 `telemail-0.55.2-linux-amd64.tar.gz` 并运行其中的 `TeleMail`（需系统提供 Python 3.12+、GTK 3.24+、Fontconfig、OpenSSL 3、WebKitGTK 4.1 及 `glibc >= 2.34`）：
  ```bash
  tar -xzf telemail-0.55.2-linux-amd64.tar.gz
  ./TeleMail-Linux-amd64/TeleMail
  # 可选：为当前用户注册桌面快捷方式
  ./TeleMail-Linux-amd64/TeleMail --install-user
  ```
- **从源码运行 (Linux)**
  满足上述 Linux 运行时依赖后，可在仓库根目录直接启动：
  ```bash
  ./run.sh
  # 或使用合成邮件进入演示模式（不连接真实邮箱、不外发邮件）
  ./run.sh --demo
  ```

### 2. 账号配置与常用命令

- **添加邮箱**：首次启动后，通过登录向导或 **“设置 → 账号”** 添加邮箱。内置 Gmail、Outlook、Microsoft 365 及通用 IMAP/SMTP 配置模板，支持密码/应用授权码，或使用自行注册的 OAuth 2.0 客户端（本项目不预置公共 Google/Microsoft OAuth 客户端 ID）。
- **命令行参数**：
  ```bash
  TeleMail --demo                              # 演示模式（使用独立演示目录与合成邮件）
  TeleMail --config <配置文件> --data <数据目录>  # 指定自定义配置与本地数据目录
  TeleMail mailto:user@example.com             # 打开预填收件人的未发送草稿窗口
  TeleMail --version                           # 查看当前版本与平台信息
  ```

### 3. 使用注意事项

- **界面字号与侧栏**：在 **“设置 → 外观 → 界面字号”** 中选择 10–32（默认 14），支持即时预览、保存与取消恢复；弹窗宽高随字号扩大并适配可用窗口。左侧固定图标栏宽度为 58 逻辑像素，固定文件夹使用窗口剩余高度，仅在实际放不下时滚动；展开的文件夹和邮箱侧栏默认宽度为 300 逻辑像素，仍可拖动调整，并保留已保存的宽度。邮件正文字号和 PDF 缩放继续使用各自设置。

- **Windows 多显示器**：使用 Windows 整窗兼容缩放，使窗口、字体与浮窗在 100%、150%、200% 显示器之间保持一致的逻辑尺寸；非主显示器上的非整数缩放可能略柔和。大字号浮窗必要时临时扩大主窗口，跨屏时重新适配工作区，关闭后恢复自动扩大的尺寸，并保留用户手动调整。

> **重要提示（自动整理策略）**：连接真实邮箱后，请先检查 **“设置 → 储存空间”** 中的自动整理设置。当前默认会将收件箱中**超过 365 天且未置顶**的邮件移至服务器垃圾箱（邮箱服务商可能随后永久清空垃圾箱）。如需长期保留全部收件箱邮件，请先关闭该选项或修改保留天数。

- **离线 PDF 阅读**：PDF 附件由内置的 PDF.js 6.4.299 在本机环回地址离线渲染，支持连续滚动、缩放、文字选择、全文搜索高亮与密码解锁，文档不会上传至外部服务器（扫描版 PDF 不提供 OCR）。
- **稍后发送与回执**：定时发送需保持应用处于运行状态，关闭期间到期的任务会在下次启动时处理；阅读回执取决于收件人客户端是否支持并响应。
- **更多文档**：详见 [隐私与数据说明](docs/PRIVACY.md)、[构建与测试指南](docs/BUILDING.md) 及 [开发说明](Develop.md)。

---

## 开源协议

- **项目自有代码**：TeleMail 自有应用代码、原生适配层与构建脚本采用 **[MIT License](LICENSE)** 开源。
- **第三方组件**：随附或引用的第三方组件（包括 PDF.js、Noto Sans CJK SC 字体、CPython、MSYS2/GTK 运行库、Microsoft WebView2 Loader 等）各自保留其原始许可证与版权声明，详见 [NOTICE](NOTICE) 与 [第三方组件说明](docs/THIRD_PARTY.md)。
- **Windows 二进制组合分发**：Windows 发行包包含独立子进程工具 Antiword（`GPL-2.0-or-later`），并通过 GdkPixbuf/libtiff 间接加载 JBIG-KIT（`GPL-2.0-or-later`）。因此，Windows 组合二进制发行包整体按 **GPLv3 或更高版本（`GPL-3.0-or-later`）** 条件提供并随附对应源码，而 TeleMail 自有代码部分仍保留 MIT 许可权限；详情请参阅 [Windows 组合分发说明](docs/WINDOWS_LICENSE.md)。
