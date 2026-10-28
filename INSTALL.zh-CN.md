# Film Desk 安装与首次打开

[English](INSTALL.md) · [项目说明](README.zh-CN.md)

适用于 Film Desk 1.5.1 的 Apple Silicon（M 系列）Mac 安装包，要求 macOS 26 或更高版本。Intel Mac 和 Windows 不能运行此安装包。

## 下载和安装

从 [GitHub 发布页](https://github.com/Tia-Lin/film-desk/releases/tag/v1.5.1) 下载本版本。README 中的百度镜像目前仍为 1.4.0。DMG 和 ZIP 二选一即可。

1. DMG：双击打开，将 Film Desk.app 复制到“应用程序”，然后推出磁盘映像。
2. ZIP：解压后将 Film Desk.app 复制到“应用程序”。
3. 更新时先退出 Film Desk，在原位置替换已有副本，避免保留多个版本。

## 首次打开被 macOS 阻止

当前发布包采用本地 ad hoc 签名，没有 Apple Developer ID 签名，也没有经过 Apple 公证。本地签名不能证明开发者身份，首次打开可能出现“无法验证开发者”或“Apple 无法检查是否包含恶意软件”的提示。

只有在确认下载来源及文件未被改动、并决定信任此应用后，才按以下步骤操作：

1. 在“应用程序”中双击 Film Desk，触发提示后关闭提示。
2. 打开 **系统设置 → 隐私与安全性**，向下找到 Film Desk 的拦截提示。
3. 点击 **仍要打开**，按系统要求验证身份，再确认 **打开**。

这是 Apple 提供的单个应用允许流程；成功后系统会记住该应用的例外。无需关闭整台 Mac 的安全检查。参见 [Apple 官方说明](https://support.apple.com/zh-cn/102445)。

若没有“仍要打开”，再次尝试打开应用后检查；公司或学校管理的 Mac 可能限制此设置，需要联系管理员。

## 文件已损坏或恶意软件警告

若提示“已损坏”“将损坏你的电脑”或已检测到恶意软件，请停止打开。重新从发布页下载、核对校验值，并在 [GitHub Issues](https://github.com/Tia-Lin/film-desk/issues) 提供 macOS 版本、安装包名称和完整报错。不要用删除隔离属性、禁用 Gatekeeper 或 SIP 的命令强行运行。上述提示与单纯未公证的提示不同。[Apple 对这些警告的解释](https://support.apple.com/zh-cn/102445)。

## 可选的 SHA-256 校验

打开“终端”，输入以下命令（路径适用于默认“下载”文件夹；若下载位置不同，请修改路径）：

```sh
shasum -a 256 "$HOME/Downloads/Film-Desk-1.5.1-macOS-arm64.dmg"
```

将结果与发布页 `Film-Desk-1.5.1-SHA256SUMS.txt` 中相同文件名的校验值比较。检查 ZIP 时将命令中的 `.dmg` 改为 `.zip`。校验值一致说明文件字节与发布包相同，不等于 Apple 安全认证；不同则不要打开。

## 照片文件夹权限

选取桌面或文稿中的扫描文件夹时，macOS 可能询问是否允许访问。要处理该文件夹，请点击“允许”。这是照片访问权限，与首次打开的安全提示分开。日常使用无需授予完全磁盘访问权限。

程序离线处理照片，原始 RAW 不会被修改或上传。打开文件夹后，设置同卷已冲洗、未曝光的空白片基参考，再开始转换。
