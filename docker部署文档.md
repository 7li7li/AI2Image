# Docker 部署文档

本文档说明如何使用 Docker / Docker Compose 部署本项目。当前镜像内会同时包含后端 FastAPI 服务和前端静态页面，容器默认监听 `9001` 端口。

## 1. 部署前准备

服务器需要安装：

- Docker 24+
- Docker Compose v2，也就是 `docker compose` 命令
- 可访问镜像仓库的网络环境

建议创建独立部署目录：

```bash
mkdir -p /opt/yanai
cd /opt/yanai
```

运行时数据不要写进镜像。本项目的 Docker 镜像不会包含以下内容：

- `config.json`
- `data/`
- `.env`
- 数据库文件
- 本地虚拟环境

这些文件需要通过宿主机挂载到容器中。

## 2. 准备配置文件

从仓库复制示例配置：

```bash
cp config.example.json config.json
mkdir -p data
```

编辑 `config.json`，至少修改 `auth-key`：

```json
{
  "auth-key": "change_this_to_a_long_random_secret",
  "site_title": "Image Studio",
  "site_icon": "/favicon.ico",
  "site_background": "",
  "image_retention_days": 15,
  "log_levels": ["info", "warning", "error"],
  "proxy": "",
  "base_url": "",
  "image_model_mappings": {
    "gpt-image-2": "gpt-5-5",
    "codex-gpt-image-2": "codex-gpt-image-2"
  }
}
```

`auth-key` 就是管理员密钥。管理员登录时选择“管理员”，输入该密钥即可。

也可以不在 `config.json` 写真实密钥，而是用环境变量覆盖：

```bash
export CHATGPT2API_AUTH_KEY="your_long_random_secret"
```

不要把真实密钥写入 Dockerfile、公开仓库、公开 Compose 文件或镜像构建参数。

## 3. 基于当前代码构建镜像

如果要部署当前仓库里的代码，必须先在当前项目根目录构建镜像。直接使用远程已有镜像只能部署该镜像发布时的代码，不一定包含你本地当前代码。

在项目根目录执行：

```bash
docker build -t yanai:local .
```

构建完成后确认镜像存在：

```bash
docker image ls yanai
```

如果服务器和构建机器不是同一台，需要把镜像推送到自己的镜像仓库：

```bash
docker tag yanai:local your-registry/yanai:latest
docker push your-registry/yanai:latest
```

多架构构建示例：

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t your-registry/yanai:latest \
  --push .
```

## 4. 使用构建好的镜像部署

如果镜像是在当前服务器本机用 `docker build -t yanai:local .` 构建的，Compose 可以直接使用本地镜像。

在部署目录创建 `docker-compose.yml`：

```yaml
services:
  app:
    image: ${YANAI_IMAGE:-yanai:local}
    container_name: yanai
    restart: unless-stopped
    ports:
      - "${YANAI_PORT:-9001}:9001"
    volumes:
      - ./data:/app/data
      - ./config.json:/app/config.json
    environment:
      STORAGE_BACKEND: ${STORAGE_BACKEND:-json}
      # 推荐生产环境显式设置管理员密钥，优先级高于 config.json
      # CHATGPT2API_AUTH_KEY: your_long_random_secret
      # 对外访问域名，用于生成图片 URL、OAuth 回调等场景
      # CHATGPT2API_BASE_URL: https://your-domain.com
```

启动服务：

```bash
docker compose up -d
```

查看日志：

```bash
docker compose logs -f app
```

访问：

```text
http://服务器IP:9001
```

健康检查：

```bash
curl http://127.0.0.1:9001/health
```

正常会返回类似：

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "storage": {
    "status": "healthy",
    "backend": "json"
  }
}
```

如果使用的是推送到镜像仓库的镜像，启动时指定镜像名：

```bash
YANAI_IMAGE=your-registry/yanai:latest docker compose up -d
```

如果明确想部署官方/已有发布镜像，而不是当前本地代码，可以指定：

```bash
YANAI_IMAGE=huaiyuechusan/yanai:latest docker compose up -d
```

这种方式适合快速体验，但不保证包含当前仓库的本地改动。

## 5. 端口配置

容器内固定监听 `9001`。宿主机端口通过 `YANAI_PORT` 控制：

```bash
YANAI_PORT=3000 docker compose up -d
```

此时访问：

```text
http://服务器IP:3000
```

如果服务器上已有服务占用 `9001`，只需要改宿主机端口，不需要改容器端口：

```yaml
ports:
  - "3000:9001"
```

## 6. 存储后端配置

项目支持多种存储后端。默认是 `json`，数据保存在挂载目录 `./data` 中。

### JSON 存储

适合单机、小规模使用：

```yaml
environment:
  STORAGE_BACKEND: json
```

### SQLite 存储

适合单机、轻量并发：

```yaml
environment:
  STORAGE_BACKEND: sqlite
  DATABASE_URL: sqlite:////app/data/accounts.db
```

数据库文件会保存在宿主机的 `./data/accounts.db`。

### PostgreSQL 存储

适合多人使用和生产环境：

```yaml
environment:
  STORAGE_BACKEND: postgres
  DATABASE_URL: postgresql://user:password@postgres-host:5432/dbname
```

PostgreSQL 可以是外部数据库，也可以在同一个 Compose 中额外启动。外部数据库更方便备份、监控和迁移。

### Git 存储

适合把运行时配置同步到私有 Git 仓库：

```yaml
environment:
  STORAGE_BACKEND: git
  GIT_REPO_URL: https://github.com/user/private-data-repo.git
  GIT_TOKEN: your_git_token_here
  GIT_BRANCH: main
  GIT_FILE_PATH: accounts.json
```

`GIT_TOKEN` 属于敏感信息，建议放在服务器环境变量或 `.env` 文件中，不要提交到仓库。

## 7. 使用 .env 管理部署变量

可以在部署目录创建 `.env`：

```dotenv
YANAI_IMAGE=yanai:local
YANAI_PORT=9001
STORAGE_BACKEND=json
CHATGPT2API_AUTH_KEY=your_long_random_secret
CHATGPT2API_BASE_URL=https://your-domain.com
```

然后正常启动：

```bash
docker compose up -d
```

Compose 会自动读取当前目录的 `.env`。

## 8. 反向代理配置

生产环境建议使用 Nginx / Caddy / 宝塔面板等反向代理到容器端口。

Nginx 示例：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:9001;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_cache off;
        gzip off;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        add_header X-Accel-Buffering no always;
        add_header Cache-Control "no-cache, no-transform" always;
    }
}
```

如果使用 HTTPS 和域名访问，建议同步设置：

```yaml
environment:
  CHATGPT2API_BASE_URL: https://your-domain.com
```

## 9. 更新部署

拉取新镜像：

```bash
docker compose pull
docker compose up -d
```

如果使用自建镜像：

```bash
docker build -t your-registry/yanai:latest .
docker push your-registry/yanai:latest
YANAI_IMAGE=your-registry/yanai:latest docker compose pull
YANAI_IMAGE=your-registry/yanai:latest docker compose up -d
```

查看当前容器：

```bash
docker compose ps
```

查看镜像版本：

```bash
docker image ls | grep yanai
```

## 10. 停止、重启和卸载

停止服务：

```bash
docker compose stop app
```

重启服务：

```bash
docker compose restart app
```

停止并删除容器，但保留数据：

```bash
docker compose down
```

彻底清理镜像需要额外执行：

```bash
docker image rm yanai:local
```

不要随意删除部署目录下的 `data/` 和 `config.json`，否则运行时数据和管理员密钥会丢失。

## 11. 数据备份

至少备份：

- `config.json`
- `data/`
- 如果使用外部 PostgreSQL，还要备份对应数据库

JSON / SQLite 部署可直接备份目录：

```bash
tar -czf yanai-backup-$(date +%F).tar.gz config.json data
```

恢复：

```bash
docker compose down
tar -xzf yanai-backup-2026-06-30.tar.gz
docker compose up -d
```

迁移存储后端前，先停止写入并备份：

```bash
docker compose stop app
tar -czf yanai-pre-migration-$(date +%F).tar.gz config.json data
```

项目内置迁移脚本位于 `scripts/`，迁移前建议先阅读脚本参数并做 dry-run。

## 12. 常见问题

### 1. 容器启动后提示 auth-key 未设置

说明没有挂载有效的 `config.json`，或者没有设置 `CHATGPT2API_AUTH_KEY`。

检查：

```bash
docker compose logs app
cat config.json
```

解决方式：

- 在 `config.json` 中填写 `"auth-key"`
- 或在 Compose 的 `environment` 中设置 `CHATGPT2API_AUTH_KEY`

### 2. 访问不了页面

先确认容器状态：

```bash
docker compose ps
docker compose logs --tail=100 app
```

再确认端口是否监听：

```bash
curl http://127.0.0.1:9001/health
```

如果宿主机端口被占用，修改：

```yaml
ports:
  - "3000:9001"
```

### 3. 生成的图片 URL 不是公网域名

设置 `CHATGPT2API_BASE_URL`：

```yaml
environment:
  CHATGPT2API_BASE_URL: https://your-domain.com
```

或在 `config.json` 中设置：

```json
{
  "base_url": "https://your-domain.com"
}
```

环境变量优先级高于 `config.json`。

### 4. 反向代理下流式接口不实时返回

需要关闭代理缓冲和压缩。Nginx 至少配置：

```nginx
proxy_buffering off;
proxy_request_buffering off;
proxy_cache off;
gzip off;
add_header X-Accel-Buffering no always;
```

### 5. 管理员怎么登录

打开部署地址 `/login`，切换到“管理员”，输入 `auth-key`。

`auth-key` 来源优先级：

1. 环境变量 `CHATGPT2API_AUTH_KEY`
2. `config.json` 中的 `"auth-key"`

## 13. 推荐生产 Compose 模板

下面模板默认使用前面基于当前代码构建出的 `yanai:local` 镜像。如果镜像来自私有仓库，把 `YANAI_IMAGE` 改成你的仓库地址。

```yaml
services:
  app:
    image: ${YANAI_IMAGE:-yanai:local}
    container_name: yanai
    restart: unless-stopped
    ports:
      - "${YANAI_PORT:-9001}:9001"
    volumes:
      - ./data:/app/data
      - ./config.json:/app/config.json:ro
    environment:
      STORAGE_BACKEND: ${STORAGE_BACKEND:-json}
      CHATGPT2API_AUTH_KEY: ${CHATGPT2API_AUTH_KEY}
      CHATGPT2API_BASE_URL: ${CHATGPT2API_BASE_URL:-}
```

配套 `.env`：

```dotenv
YANAI_IMAGE=yanai:local
YANAI_PORT=9001
STORAGE_BACKEND=json
CHATGPT2API_AUTH_KEY=replace_with_a_long_random_secret
CHATGPT2API_BASE_URL=https://your-domain.com
```

启动：

```bash
docker compose up -d
```

确认：

```bash
curl http://127.0.0.1:9001/health
docker compose logs --tail=50 app
```
