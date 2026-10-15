# GitHub 提交指南（含打不开的解决办法）

> 你的本地仓库我已经准备好了：已 `git init` 并完成首次提交（`4790d86`，45 个文件）。
> `data/`、数据库、`config/openapi.env` 都已正确排除，不会上传。
> 你只需要**建远程仓库 + 推送**。

---

## 一、为什么 GitHub 总是打不开

两个原因叠加：

1. **DNS 污染**：`github.com` 的域名解析被返回错误 IP
2. **IP 层阻断**：即使解析对了，连接也常被重置（表现为"转圈很久然后失败"）

所以光换 DNS（比如改 114.114.114.114）通常**没用**，需要能真正绕开这两层的手段。

---

## 二、三个方案，按推荐度排序

### 方案 A：Watt Toolkit（原 Steam++）—— 最省事 ⭐推荐

免费开源，图形界面，一键加速 GitHub，Windows 上最常用的方案。

1. 打开 https://steampp.net/ （或用 Microsoft Store 搜 "Watt Toolkit"）
2. 下载安装 → 打开
3. 左侧选 **「网络加速」**
4. 勾选 **GitHub**（可连同勾选"GitHub 静态资源"、"GitHub 网页"）
5. 点 **「一键加速」**
6. 保持它运行，然后正常访问 github.com 和 push

> 注意：它会修改系统代理设置，用完可以点"停止加速"还原。

### 方案 B：FastGithub —— 后台常驻，自动优选 IP

开源工具，本地起一个服务自动把 GitHub 流量导向可用 IP。

1. 打开 https://github.com/dotnetcore/FastGithub/releases
2. 下载 `fastgithub_win-x64.zip`（自带运行时，无需装 .NET）
3. 解压 → 双击 `FastGithub.UI.exe`
4. 保持后台运行即可

> 如果 GitHub 本身打不开、下载不了它，先用方案 A 把 GitHub 打开，再下载这个。

### 方案 C：改 hosts 文件 —— 备选，容易失效

1. 用管理员身份打开记事本
2. 打开 `C:\Windows\System32\drivers\etc\hosts`
3. 在末尾追加（IP 需要自己去 https://www.ipaddress.com/ 查 `github.com` 和 `github.global.ssl.fastly.net` 的当前可用 IP）：

```
140.82.113.4    github.com
199.232.69.194  github.global.ssl.fastly.net
```

4. 保存后在命令行执行 `ipconfig /flushdns`

> ⚠️ 这些 IP 会变，过一段时间就失效，需要重新查。**不建议作为长期方案。**

### 方案 D：不用 GitHub，改用 Gitee —— 兜底最稳

如果上面都不顺利，Gitee（码云）国内直连、5 分钟搞定，代码完全一样：

1. 打开 https://gitee.com/ → 注册/登录
2. 右上角 `+` → **新建仓库** → 填仓库名 `market-compass` → 创建
3. 把下面的命令里 `github.com` 换成 `gitee.com` 即可

**答辩时说明"代码托管于 Gitee（国内可直连）"是完全没问题的。**

---

## 三、推送代码的完整步骤

### 第 1 步：在 GitHub 建仓库

1. 登录 GitHub → 右上角 `+` → **New repository**
2. Repository name 填：`market-compass`
3. 选 **Public**（公开，方便评审查看）或 Private（如果你更在意隐私）
4. **不要勾选** "Add a README file" / ".gitignore" / "license"（我们本地已经有了，勾了会冲突）
5. 点 **Create repository**

### 第 2 步：生成访问令牌（重要）

**GitHub 早就不支持用密码推送了**，必须用 Personal Access Token（PAT）：

1. 点右上角头像 → **Settings**
2. 左侧拉到底 → **Developer settings**
3. **Personal access tokens** → **Tokens (classic)**
4. 右上 **Generate new token** → **Generate new token (classic)**
5. Note 填 `market-compass`，Expiration 选 90 天
6. 勾选权限：**`repo`**（勾上后子项会自动全选）
7. 点最下面 **Generate token**
8. **立刻复制那串 `ghp_...`**——离开页面就再也看不到了

> 推送时如果弹出登录框：用户名填你的 GitHub 用户名，**密码处粘贴这串 token**（不是你的登录密码）。

### 第 3 步：推送

打开项目文件夹，双击 `2-启动看板.bat` 旁边……不，推送需要命令行。按 `Win + R` 输入 `cmd` 回车，然后：

```cmd
cd /d E:\dsh-workspace\market-compass

git remote add origin https://github.com/你的用户名/market-compass.git
git branch -M main
git push -u origin main
```

等它跑完，刷新 GitHub 页面就能看到代码了。

以后有改动再推：

```cmd
git add -A
git commit -m "更新说明"
git push
```

---

## 四、提交表单各字段怎么填

| 表单字段 | 建议填法 |
|---|---|
| 作品名称 | 商情罗盘 · MarketCompass |
| 作品简介（必填） | 用 `01-作品简介.md` 里的**长版**（约 600 字） |
| 代码仓库链接 | `https://github.com/你的用户名/market-compass`（或 Gitee 地址） |
| 在线演示链接 | 填仓库里的 README 地址，或与代码仓库相同；也可留空并在补充说明里写明"因无公网服务器，提供本地一键运行方式"。**不要填 `127.0.0.1`，评委打不开** |
| 演示 PPT | 上传 `02-演示PPT.pptx` |
| 演示视频 | 按 `03-演示视频脚本.md` 录制后上传 MP4 |
| 补充说明 | 用 `04-补充说明.md` 的内容 |

---

## 五、推送前的最后检查

- [ ] 仓库是 **Public**（除非比赛允许私有）
- [ ] 仓库里**没有** `config/openapi.env`（如果将来配置了凭据，务必确认它没被提交）
- [ ] 仓库里**没有** `data/` 目录（数据库文件很大且可重新生成）
- [ ] README.md 能在 GitHub 页面上正常显示（含中文）
- [ ] 自己用浏览器打开仓库首页看一眼，确认目录结构清晰

本地自查命令：

```cmd
cd /d E:\dsh-workspace\market-compass
git ls-files | findstr /i "openapi.env"
```
**没有任何输出** = 安全。
