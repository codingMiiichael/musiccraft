# 组员协作

项目地址：https://github.com/codingMiiichael/musiccraft

仓库已公开。任何人都可以查看、克隆、Fork，并通过 Pull Request 提交修改。直接向本仓库推送分支需要协作者写入权限；组员接受仓库拥有者发出的 GitHub 邀请后即可使用。

## 下载与运行

```bash
git clone https://github.com/codingMiiichael/musiccraft.git
cd musiccraft
python3 -B run.py
```

浏览器打开 http://127.0.0.1:8765 。无需启动服务的课堂展示可直接使用 [在线演示](https://musiccraft-agent-demo.spicypony68.chatgpt.site)。

## 修改与提交

获得写入权限后，每位成员从最新 main 创建自己的功能分支。将下方 feature/your-name 替换成自己的分支名：

```bash
git switch main
git pull --ff-only origin main
git switch -c feature/your-name
```

完成修改后检查差异，只提交自己的代码：

```bash
git diff
git add <本次修改的文件>
git commit -m "Describe the change"
git push -u origin feature/your-name
```

然后在 GitHub 创建 Pull Request，目标分支选 main，由另一位组员检查后合并。尚未获得写入权限的成员可以先 Fork 仓库，再从自己的 Fork 发起 Pull Request。

## 项目约定

- .env、录音、运行数据库和模型权重不提交到 Git；共享配置使用 .env.example。
- 修改核心后端时运行 `python3 -B -m unittest discover -s tests -v`。
- 修改静态在线版时，按 online-demo/README.md 验证。GitHub 推送不会自动重新发布 Sites 网站，需单独更新 Sites 版本。
- 当前在线音频是明确标注的流程占位；真实效果需在 GPU 环境验证。
