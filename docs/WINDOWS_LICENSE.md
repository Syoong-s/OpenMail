# Windows 组合分发许可

TeleMail 自有代码继续按仓库根目录 MIT LICENSE 授权。第三方文件保留各自的原始版权与许可；不能将整个 Windows 发行目录标为仅适用 MIT。

为保留完整 TIFF 兼容性，本 Windows 发行包使用原始固定版本的 GdkPixbuf、libtiff 和 JBIG-KIT。JBIG-KIT 在 GUI 进程中被间接加载，源码授权为 GPL-2.0-or-later。对于包含该组件的组合作品，本发行按 GPLv3 或后续版本条件提供；MIT 部分保留其额外的宽松授权。完整 GPLv3 正文随包保存于 docs/third_party/licenses/GPL-3.0.txt。此说明不把独立的微软系统组件或其他第三方作品重新授权为 GPL。

Antiword 为独立子进程，保留 GPL-2.0-or-later、完整原源码与构建说明。库的许可证、版本及对应文件见 WINDOWS_RUNTIME_PACKAGES.json、runtime/share/licenses；应用源码和对应的第三方源码通过同一 GitHub Release 免费提供，工作流自动生成和上传。

接收者可按适用许可复制、修改、重新构建并再分发；应用不限制替换兼容的动态库。请一并保留原版权、许可与完整对应源码，不能仅替换根 LICENSE 后忽略组合发行的条件。

依据：[GNU 关于 GPL 兼容许可与组合作品的说明](https://www.gnu.org/licenses/gpl-faq.en.html#WhatDoesCompatMean)。具体第三方来源及未完成的全面权属审查边界见 THIRD_PARTY.md。
