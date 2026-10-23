# 发票信息录入 Demo

本机 Web Demo：批量上传 PDF，核对识别结果，导出一份按 `reference/invoice_template.docx` 填写的 Word 文档。界面不需要登录。

## 启动

在 PowerShell 中进入项目目录，首次运行时执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

然后运行：

```powershell
.\run_demo.ps1
```

浏览器打开 `http://127.0.0.1:8000`。一次选择多份 PDF，等待识别完成；逐张对照原件修改字段，点击“保存修改”，最后点击右上角“导出 Word”。

本地测试使用了 5 份样例 PDF，导出示例位于本机的 `output/demo_invoice_summary.docx`。原始票据和已填写的输出文件不随公开仓库发布；克隆仓库后可上传自己的 PDF 使用。

## Demo 说明

- 针对扫描 PDF 使用本地 RapidOCR；上传的文件和核对后的数据保存在 `web_demo/data/jobs/`，不会发送到外部 OCR 服务。
- 系统会尝试自动调整票据方向、裁掉大面积白边。OCR 对出租车发票点阵字体等内容可能识别不准，导出前应对照原件核对。
- Word 导出保留模板中的 4 张购物小票和 1 张出租车发票结构，并能增加商品行或额外票据块。未使用的票据块会移除。
- 原票没有明确列出的字段不会凭空补造。购物小票地址缺失时，Word 中显示“原票未载明”；关键的日期、金额或出租车发票号码缺失时，界面会要求补充。
- 详细功能与后续开发方向见 [开发文档](docs/invoice-entry-web-spec.md)。
