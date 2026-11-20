# MusicCraft 在线流程演示源码

此目录提供无需 Python 后端的静态演示版。所有音频、任务和收藏保存在访问者自己的浏览器中，不共享不同访客的数据。输出为合成 WAV 占位，未调用真实 LLM、音乐生成或声音转换模型。

在此目录运行：

```bash
python3 -m http.server 8771 --bind 127.0.0.1 --directory dist
```

然后打开 http://127.0.0.1:8771 。自动检查可运行 `node check.mjs`。

- dist/browser-engine.js：浏览器规则规划、IndexedDB、任务模拟、WAV 合成。
- dist/app.js：工作台交互与音频 Blob URL 绑定。
- dist/index.html、style.css：沿用项目品牌，增加在线演示引导。

实际 Sites 部署使用独立的托管源码目录与 .openai/hosting.json，以避免混用 GitHub 和 Sites 的 Git 远端。主项目的真实模型服务保持在 musiccraft/、workers/ 和 deploy/ 中。
