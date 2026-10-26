# 第三方组件

本项目自有代码采用 MIT。各第三方组件保留其原许可与版权归属；项目许可证不替换下列许可。

| 组件 | 来源及许可材料 | 交付方式 |
| --- | --- | --- |
| PDF.js 6.4.299 | `maildesk/desktop_assets/pdfjs/vendor/SOURCE.json`、`LICENSE`，以及 cmaps/standard_fonts/wasm/iccs 中的附加许可 | 两端随应用分发；Apache-2.0 及原附加许可 |
| Noto Sans CJK SC | `docs/THIRD_PARTY_FONTS.md`、字体目录 `OFL.txt` | 原始字体，SIL OFL 1.1 |
| Antiword | `native/third_party/antiword/` 中原许可、完整源码和构建说明 | Windows 中作为独立子进程，GPL-2.0-or-later |
| CPython 3.14.5 | 官方嵌入式归档，Windows 包的 `docs/PYTHON_LICENSE.txt` | 包含原 PSF 和第三方许可；对应源码另随 Release 提供 |
| GTK/GLib/Pango 等 MSYS2 组件 | Windows 包 `docs/WINDOWS_RUNTIME_PACKAGES.json`、`runtime/share/licenses/` | 逐包保留 LGPL/GPL/宽松许可和源码快照 |
| Microsoft WebView2 Loader | SDK 内原许可，Windows 包 `docs/WEBVIEW2_LICENSE.txt` | 原微软许可；Evergreen Runtime 由系统提供 |
| Linux 系统库 | 系统发行版包及其许可 | 本 Linux 包不附带这些系统库 |

Windows 清单按实际分发文件与固定 MSYS2 包逐项匹配，不把 SDK 下载清单等同于实际发行组件。默认 Windows 构建使用原始固定版本 libtiff/JBIG-KIT，保留普通及 JBIG 压缩 TIFF。项目自有代码保留 MIT；包含 JBIG-KIT 的 Windows 组合分发按 GPLv3-or-later 条件提供，见 WINDOWS_LICENSE.md。库的原许可和对应源码随发行材料提供。PDF.js 的 JBIG2 解码组件是另一个项目。Linux 使用系统提供的图像库，本项目不将这些系统库重新标为 MIT。

GTK 等 LGPL 动态库保留为独立、可替换的 DLL，应用不增加阻止用户替换兼容库的校验机制。提供库的源代码、补丁和构建配方；请保留全部原版权与许可文本。

## 对应源码交付

GitHub Actions 为每个二进制 Release 自动生成并同时上传 `telemail-X.Y.Z-source.tar.gz` 和 `telemail-X.Y.Z-third-party-sources.tar`，并提供同位置、免费访问的下载与 SHA-256 校验文件。应用源码包包含构建脚本、PDF.js、字体、Antiword 原源码和许可；第三方源码包包含实际 Windows 运行库的固定版本 MSYS2 源包（上游源码、补丁和 PKGBUILD）、CPython 和 PDF.js 上游包、librsvg 的 Rust crate 源码、源包清单及构建说明。不用浮动 master 链接替代对应源码。

源码快照哈希固定在 `third_party/windows/sources.lock.json`。首次获取时测量归档 SHA-256，之后按锁校验；这不等于取得了独立上游签名背书。

第三方分发许可依据：[GPLv3 第 6 节](https://www.gnu.org/licenses/gpl-3.0.html)、[Apache 与 GPL 兼容说明](https://www.apache.org/licenses/GPL-compatibility)。完整许可正文优先。

## librsvg 的 Rust 依赖

原 MSYS2 配方会把 windows-sys 固定到 0.60.2，但源包不保存这一步之后的 Cargo.lock。本发行额外提供原始 Cargo.lock 中全部 registry crate、该 Windows 版本及兼容 Windows 0.53 目标家族源码，并附逐 crate 哈希与原许可/版权声明；这是明确标注的源码超集，不能称为恢复了原二进制构建的精确后置锁文件。见 `third_party/librsvg-rust.lock.json`。重新构建运行库时应保存实际解析后的 Cargo.lock 和构建日志。本次未重新编译全部 MSYS2 库，也不宣称二进制可逐字节复现。

少数额外源码 crate（difflib、malloc_buf、objc-foundation）的原归档只在 Cargo.toml 声明 MIT，未带独立许可文件；保留原始元数据、MIT 正文，并为前两者补充了固定哈希的上游许可快照。快照来源及范围见 supplemental-licenses.json，不把当前上游文本伪称为原归档文件。objc-foundation 是额外包含的 macOS 源码依赖，未作为 Windows 动态库分发。
