# 构建和测试

所有命令从仓库根目录运行。构建缓存位于 `.runtime/`，产物位于 `dist/`。不要在真实邮箱配置下运行开发验收。

## Linux

应用运行要求 Python 3.12+、GTK 3.24+、Fontconfig、OpenSSL 3、WebKitGTK 4.1 和 SVG 图像加载器（Debian/Ubuntu：`librsvg2-common`）。构建需要 Linux x86-64、GCC 兼容编译器、binutils、dpkg-deb。

```sh
python3 tools/build_linux.py --cc gcc
./dist/TeleMail-Linux-amd64/TeleMail
```

glibc 的实际下限由所用构建主机决定，应在计划支持的最旧发行版构建并验收。本次测试为 Ubuntu 26.04/WSLg，不能据此保证所有发行版兼容。

## Windows 交叉构建

使用 Linux x86-64 或 WSL2，Python 3.14+（读取 zstd tar 包）、GNU make、主机 GTK/GdkPixbuf、SVG 加载器（Debian/Ubuntu：`librsvg2-common`）和 glib-compile-schemas。不使用 Windows 编译器。脚本下载固定版本归档并解压到项目私有 SDK，不安装系统包、不运行包安装脚本。

```sh
python3 tools/build_windows.py --check-icon
python3 tools/prepare_windows_runtime.py --manifest-only
python3 tools/prepare_windows_runtime.py
python3 tools/build_windows.py --zip
```

`--check-icon` 无需 Windows SDK 和图形桌面，可先验证主机 SVG 解码/PNG 编码。缺少加载器时会显示原始 GdkPixbuf 错误；工作流在下载 SDK 前执行检查。Ubuntu 24.04 的 PR 检查还会隐藏加载器缓存，验证缺依赖时的诊断。

固定 SDK：llvm-mingw 20261006 / LLVM 23.1.3，WebView2 SDK 1.0.4258.31，嵌入式 CPython 3.14.5。二进制归档哈希见 `third_party/windows/`；PDF.js 来源与资源哈希见 `maildesk/desktop_assets/pdfjs/vendor/SOURCE.json`。可复用现有、已校验的私有 SDK；不得将其个人绝对路径提交到仓库。

## 测试

```sh
python3 tools/run_tests.py
python3 tools/verify_pdfjs_desktop.py --output .runtime/pdfjs-check
python3 tools/verify_mail_layout_desktop.py --output .runtime/linux-mail-check
```

第一条把资料目录重定向到临时位置；Windows 使用 `--bundle` 指定运行库，如 TLS 测试需要，可用 `--qa-openssl-dir` 指向已有 OpenSSL 命令行目录（仅测试进程 PATH）。

后端失败时，完整测试名称和 traceback 会输出到工作流日志，同时保留在输出目录的 `tests.txt`；Windows QA 即使失败也上传 `windows-qa-reports`，其中包含日志和已生成的报告。测试失败仍返回非零退出码并阻止发布。使用 Python 3.14+ 标准库运行 `python3 -B -m unittest tests.test_test_runner -v` 可验证成功和失败两条诊断路径。

Windows 注册测试按规范路径比较，允许 `RUNNER~1` 等短路径别名。JBIG TIFF 验收在独立进程中实际编码、读取文件并检查尺寸和全部像素，父进程等待其退出后显式删除文件；不忽略清理错误，也不跳过 JBIG 功能。两项测试使用 Python 3.14.5 标准库、打包的 libtiff/JBIG-KIT 和 GdkPixbuf。使用 `./dist/TeleMail-Windows-amd64/runtime/python/python.exe tools/run_tests.py --bundle dist/TeleMail-Windows-amd64 --qa-openssl-dir <现有OpenSSL目录>` 运行完整 Windows 验收，脚本会设置私有运行库路径和临时资料目录。

第二条要求真实图形桌面及浏览器运行库，使用临时演示资料并禁止 IMAP/SMTP。加密 PDF 的额外验证可使用 `--encrypted` 指定合成测试文件。Windows 使用包内 Python 运行相同脚本并指定 `--bundle`。

第三条在 Linux 的真实 GTK/WebKit 窗口中验证邮件气泡排版、高度、宽度变化、缩放、图片更新、收起重开和脚本阻止。使用临时合成邮件，禁止真实邮箱调用；CI 在 Xvfb 中执行同一检查。

本地编译/解释器：GCC 15.2.0，Linux Python 3.14.4，Windows 包内 Python 3.14.5。窗口管理器、托盘、通知、字体和 WebKit/WebView2 行为需在目标系统验收。

源码收集脚本使用 Python 3.14+ 标准库。`python3 -B -m unittest tests.test_release_sources -v` 可离线验证空缓存下载命名和 SHA-256 校验。上游下载必须保留 `third_party/upstream-sources.lock.json` 的 `filename`：例如 PDF.js 下载地址末尾是版本号，缓存文件仍须命名为 `pdfjs-v6.4.299.tar.gz`，并按该名称校验锁定哈希。`python3 tools/prepare_release_sources.py` 自动准备缓存；无需上传 `.runtime/` 或手工准备源码包。

## MIT 发行边界

项目自有代码为 MIT。Windows 使用原固定版本 libtiff/JBIG-KIT，保留 JBIG 压缩 TIFF。自有代码为 MIT，包含 GPL 组件的 Windows 组合分发按 WINDOWS_LICENSE.md 提供相应条件、许可与源码；Antiword 作为独立 GPL 工具保留原许可与源码。GitHub 自动发行无需维护者手工构建源码包，流程见 RELEASING.md。
