# 轻截图

Python + PySide6 编写的 Windows 截图小工具，参考微信的框选和标注流程。

## 启动

需要 Windows 10/11、64 位 Python 3.10 或更新版本。在此目录运行：

```powershell
py -3.10-64 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe screenshot.py
```

安装后也可以双击 `run.bat`，后台运行时在系统托盘显示绿色相机图标。

若使用其他版本的 64 位 Python，请将第一条命令换成对应解释器的 `python -m venv .venv`。依赖只安装 Qt Essentials，不需要浏览器或多媒体模块。

## 使用

- 按 **Alt+A**，拖动框选，松开后进入独立编辑窗口。
- 框选时按 **Esc** 或右键取消。
- 选择矩形、圆形、箭头、画笔、文字或马赛克，在图片上操作；可修改颜色和粗细。
- 文字工具点击后输入，可输入多行。马赛克工具拖出要遮盖的区域。
- **Ctrl+Z / Ctrl+Y** 撤销 / 重做。
- **Ctrl+C** 复制图片；**Ctrl+S** 保存 PNG；**Enter** 复制并关闭。
- 右键托盘图标可截图、重新注册快捷键或退出；双击图标也可截图。
- 关闭尚未复制或保存的截图时，会询问是否放弃。

## 微信快捷键冲突

本工具默认注册 Alt+A。如果微信或其他程序已经占用，会显示提示。请修改微信中的截图快捷键，再右键本工具托盘图标选择“重新注册 Alt+A”。本工具不会修改微信配置或关闭微信。未成功注册时，托盘截图仍然可用。

## 当前范围

- 支持多显示器桌面框选，包括位于主屏左侧的屏幕。
- 图片按桌面逻辑像素合成。高 DPI 屏幕及混合缩放屏幕的输出并非各屏原始物理像素分辨率。
- 标注可撤销、重做；暂不支持选中已有标注后移动、缩放或重新编辑文字。
- 大截图在编辑窗口内通过滚动条查看，目前没有缩放预览、窗口自动吸附和长截图。
- 截图与编辑在本地完成，不上传图片。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

屏幕抓取与托盘使用 Qt API：[QScreen](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QScreen.html)、[QSystemTrayIcon](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QSystemTrayIcon.html)。
