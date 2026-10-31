# TeleMail

本地桌面邮件客户端，当前版本 **0.55.3**，支持 Windows 11 x64 与 Linux x86-64。

支持 IMAP/SMTP、多账号、文件夹管理、邮件搜索、过滤器、通讯录、草稿、稍后发送和附件预览。PDF 使用随应用分发的 PDF.js 6.4.299，支持连续滚动、文字选择、翻页、缩放、搜索高亮和密码文件，无需上传文档。

## 安装与启动

- **Windows**：解压 `telemail-0.55.3-windows-amd64.zip`，双击 `TeleMail-Windows-amd64/TeleMail.exe`。保留整个目录。自带 Python/GTK，需要 Microsoft WebView2 Evergreen Runtime；不需要 WSL。
- **Debian/Ubuntu**：安装 `telemail-desktop_0.55.3_amd64.deb`，从应用菜单启动。安装器处理系统依赖。
- **Linux 可移动包**：解压 `telemail-0.55.3-linux-amd64.tar.gz`，运行其中的 `TeleMail`。需要系统 Python 3.12+、GTK 3.24+、Fontconfig、OpenSSL 3、WebKitGTK 4.1 及兼容 glibc。不是完全自带依赖的包。

首次启动在设置中添加自己的邮箱，使用服务商支持的授权码、密码或自行注册的 OAuth 客户端。项目没有预置统一 Google/Microsoft OAuth 应用；公开源码不代表服务商已审核通过。两端共用核心功能，系统集成与网页渲染引擎存在差异，尚未完成全功能对等认证。

**使用前请检查“设置 → 储存空间”的自动整理设置：当前默认会把收件箱中超过 365 天、未置顶的邮件移到服务器垃圾箱；服务商可能随后永久清空垃圾箱。可关闭或修改保留天数。**

稍后发送需要应用运行；关闭期间到期的任务在下次启动时处理。阅读回执取决于收件人客户端。扫描 PDF 不提供 OCR。

## 自动发布

提交代码并推送与应用版本一致的标签（例如 `v0.55.3`），GitHub Actions 会构建 Windows ZIP、Linux **DEB 和 tar.gz**，测试后自动创建 Release。应用源码包、第三方源码包和校验文件也自动生成，无需手工打包；详见[自动发行说明](docs/RELEASING.md)。

## 开发与发布

- [构建和测试](docs/BUILDING.md)
- [发行步骤及对应源码](docs/RELEASING.md)
- [隐私说明](docs/PRIVACY.md)
- [第三方组件与许可](docs/THIRD_PARTY.md)
- [PDF 阅读器设计](docs/PDFJS_READER.md)
- [更新记录](docs/CHANGELOG.md)

本仓库不包含用户邮件、账号配置、凭据、历史分析证据或旧发行包。`dist/` 是本地构建输出，受 Git 忽略；发行包和对应源码通过 GitHub Release 附件交付。

## 许可

本项目自有代码采用 **MIT**，见 [LICENSE](LICENSE)。第三方文件沿用原许可，不能统一改称 GPL；具体归属见 [NOTICE](NOTICE) 和第三方清单。

Windows 包保留 JBIG 压缩 TIFF 阅读及独立的 Antiword 工具，因此仍包含 GPL 组件。项目自有代码采用 MIT；Windows 组合分发还须遵守适用的 GPL 条件，不能把整个包标为纯 MIT。许可和对应源码由工作流自动附带，见[Windows 组合分发说明](docs/WINDOWS_LICENSE.md)。

## 独立的数据与配置

TeleMail 使用独立的配置、数据、缓存和下载目录，以及 `org.telemail.Desktop` 应用标识和 `TELEMAIL_*` 环境变量；不会查找或迁移 Maildesk 的账号、邮件、草稿和存储位置索引。启动新版后按需添加账号。MIT 许可证及第三方许可不变，原有版权署名保留。

内部 Python 包名 `maildesk` 仅用于源码组织，不参与旧版数据兼容。
