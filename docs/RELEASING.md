# GitHub 自动发行

项目自有代码采用 MIT；第三方组件各自的许可仍然适用。Windows 保留 JBIG-KIT，包含该组件的组合作品按 GPLv3-or-later 条件分发，详见 WINDOWS_LICENSE.md。工作流为 `.github/workflows/release.yml`。

## 一次性准备

将本仓库推送到自己的 GitHub 仓库，启用 Actions。默认 `GITHUB_TOKEN` 即可，不需要填写个人访问令牌。组织策略需允许工作流发布 Release；只有最终 publish 作业获得 `contents: write`。Actions 固定到提交 SHA，版本与来源记录在 `third_party/github-actions.lock.json`。

## 发布一个版本

1. 修改 `maildesk/__init__.py` 的版本号并提交代码。
2. 推送相同版本的标签，例如当前版本为 `0.55.3` 时推送 `v0.55.3`。
3. 工作流自动执行构建、测试、源码准备和发布。也可以在 Actions 的 **Build and release TeleMail → Run workflow** 中填写已存在的版本标签。

不需要维护者手工生成或上传源码包。GitHub 自带 Source code ZIP/tar.gz；工作流还会自动生成和上传以下完整发行附件：

| 附件 | 内容 |
| --- | --- |
| `telemail-X.Y.Z-windows-amd64.zip` | Windows 可移动程序 |
| `telemail-X.Y.Z-linux-amd64.tar.gz` | Linux 可移动目录，需系统依赖 |
| `telemail-desktop_X.Y.Z_amd64.deb` | Debian/Ubuntu 安装包 |
| `telemail-X.Y.Z-source.tar.gz` | 公开应用源码、构建工具、资源与许可 |
| `telemail-X.Y.Z-third-party-sources.tar` | 固定版本依赖源码、补丁、构建配方、Rust crate 与许可 |
| `SHA256SUMS`、`RELEASE_VERIFICATION.json` | 完整性、测试和构建来源报告 |

## 工作流检查

Linux 托管 runner 使用 Python 3.14 和系统 GTK/WebKit，通过现有 llvm-mingw 交叉构建 Windows，同时构建 Linux DEB 与 tar.gz。Windows 托管 runner 用发行包内 Python、GTK、WebView2 运行原生测试。

两端必须通过完整后端测试和 9 项 PDF 界面检查。检查包括合成密码 PDF；使用仓库中的合成测试文件，不连接真实邮箱。报告绑定到实际包清单哈希、Git 提交和本次工作流 run ID，旧报告不能充当新构建验收。

最终作业重新校验二进制、DEB、所有源码附件及测试来源；全部通过才创建草稿 Release、上传全部附件并公开。任一步失败都不公开新的 Release；若最后的上传/发布失败可能保留草稿。已存在同名 Release 时不覆盖，请检查失败日志，不要移动已发布标签。

托管 runner 上会安装构建依赖，必要时安装 WebView2；这些只发生在临时 CI 机器上。Linux GUI 验收在 Xvfb/DBus 会话中运行，并为 WebKit 保留沙箱所需的用户命名空间。不会修改开发者本机环境。

## 本地开发

本地仍可按 BUILDING.md 构建。默认 `prepare_release.py` 要求匹配当前包的两端 QA 报告；`--stage-only` 只准备候选材料，不表示验收通过；`--use-existing-sources --require-ci-provenance` 是最终 CI 校验。`publish_release.py --dry-run` 仅检查材料，不访问 GitHub。

不得把 `.runtime/`、`dist/`、`.planning/`、用户邮件、凭据或历史 evidence 强制加入 Git。当前构建不包含 Authenticode 签名或统一 OAuth 注册。发布说明保留自动整理服务器邮件的提示。第三方来源、许可和 librsvg 源码超集限制见 THIRD_PARTY.md。
