# 本地 PDF.js 阅读器（0.55）

PDF 附件和本机 PDF 使用 Mozilla PDF.js 6.4.299，替换原先的 Poppler C API。Windows 继续使用 WebView2；Linux 使用独立的 WebKitGTK 阅读视图。无需系统 PDF 软件、Node.js 运行时、CDN 或云端转换。

功能包括连续滚动、文字选择、上一页/下一页、页码与缩放比例、缩小/放大、适合宽度，以及搜索高亮。底部“搜索 PDF”输入框按回车查找，再次回车跳至下一处。加密 PDF 在本机阅读区域输入密码，密码不写入原生状态、日志或持久存储。扫描件没有文本层时不提供 OCR；XFA、PDF 内脚本、表单交互和附件内嵌内容不执行。

## 数据与安全边界

- 每个活动 PDF 启动一个仅绑定 `127.0.0.1`、随机端口和随机 192 位路径的本机资源服务。应用自动管理，无需手动启动服务器。
- 服务只提供当前 PDF 和固定清单中的阅读器资源，不提供任意文件访问、目录列表、上传接口或跨域许可；校验 Host、Origin 和 Fetch Metadata。
- PDF 页面采用独立 CSP，允许本地可信 PDF.js 模块及其 worker。PDF.js 禁用 `eval` 和 XFA，未创建 PDF scripting manager，不打包 scripting sandbox，禁用文档注释交互。
- Windows 同时在原生请求拦截器中限制为该阅读器的本机地址范围；Linux 使用独立、临时、启用沙箱且不进入邮件视图复用池的 WebKit 上下文。
- 邮件 HTML 的净化、脚本禁用 CSP 和远程图片许可保持原有策略。不会为了运行 PDF.js 放宽邮件正文权限。
- 关闭或切换活动标签会停止渲染、撤销本机地址并释放服务端 PDF 字节；重新打开使用新地址。应用原有附件/标签缓存仍按既有规则保留源文件。
- 工作区原有单文件 30 MiB、最多八个标签及 60 MiB 总预算继续适用。PDF.js 按可见区域渲染，并限制单页画布和图像尺寸。

## 来源、许可与更新

资源位于 `maildesk/desktop_assets/pdfjs/vendor/`，来自官方 npm 包 `pdfjs-dist@6.4.299` 的 legacy 浏览器构建。下载时核验 npm 元数据中的 SHA-512；`vendor/SOURCE.json` 记录归档来源、完整性和每个分发文件的 SHA-256。未从 Codex 或其他应用复制代码。

PDF.js 使用 Apache 2.0；完整 `vendor/LICENSE` 及 cmaps、standard_fonts、wasm、iccs 中的附加许可文件一并保留。PDF.js 的 JBIG2 解码器与以前 libtiff 依赖的 JBIG-KIT 是不同组件。升级时应重新核验官方包、所有资源哈希、浏览器兼容性及附加许可。

新 Windows 构建不再以 Poppler DLL 为根解析运行库，也不复制其数据目录。构建前清理生成的运行库树，避免覆盖构建残留旧 DLL。Linux 新包不再声明 libpoppler 依赖，包含完整当前应用模块及本地 PDF.js 资源。其他原生图像、GTK、Antiword 等依赖仍须分别遵守其许可；此次替换不代表整个发行包已完成所有法律合规工作。

## 构建和验证

本次使用现有 WSL GCC 15.2.0、Python 3.14.4、Windows 包内 Python 3.14.5、现有 llvm-mingw 20261006/UCRT 和 WebView2 SDK 1.0.4258.31。PDF.js 无新增 pip 依赖。Linux 继续需要 Python 3.12+、GTK 3.24+、Fontconfig、OpenSSL 和 WebKitGTK 4.1；Windows 使用发行包内 GTK/Python 及现有 WebView2 Evergreen Runtime。

从项目目录运行：

- Windows：`python3 tools/build_windows.py --output dist/TeleMail-Windows-amd64 --zip`
- Linux：`python3 tools/build_linux.py --cc gcc`
- 资源访问及适配器测试：`python3 -m unittest discover -s tests -p 'test_pdfjs.py' -v`
- Linux 实际阅读器：`python3 tools/verify_pdfjs_desktop.py --output .runtime/pdfjs-check`
- Windows 实际阅读器：使用包内 Python 运行同一脚本，指定 `--bundle` 和 `--output`。

所有界面验证使用临时演示配置，禁止真实 IMAP/SMTP 操作。测试结果另存于工作区诊断目录，不包含真实邮件。

实际 Windows 运行库清单见每个发行包的 `docs/WINDOWS_RUNTIME_PACKAGES.json`。依赖下载锁见 `third_party/windows/`；PDF 资源来源以 vendor/SOURCE.json 为准。

## 本次验证结果

Windows/WebView2 和 Linux/WebKitGTK 各通过 9 项实际界面检查，包含真实画布像素、文字层/搜索高亮、翻页、缩放、无效文件、加密文件错误密码重试，以及反复关闭重开。两端完整后端测试各 320 项，均跳过 2 项平台测试，无失败或错误。此前 15 项旧测试夹具问题已在公开仓库修正，保留历史记录，未修改应用业务代码。

WSLg 关闭部分 WebKit 渲染进程时仍会出现 GLib/GIO 名称释放警告；本次应用正常退出。详细匿名记录见 `PDFJS_VERIFICATION.json`。
