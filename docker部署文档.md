# ImageStudio 本地 Docker + 外部 PostgreSQL 部署文档

本文档只说明一种部署方式：基于当前项目代码在本地构建 Docker 镜像，并连接外部 PostgreSQL 数据库。Compose 只启动 ImageStudio 应用容器，不启动数据库容器。

## 1. 部署结果

部署完成后会启动一个容器：

- `imagestudio`：应用容器，包含后端 FastAPI 和前端静态页面，容器内监听 `9001`

外部依赖：

- 一套已经可访问的 PostgreSQL 数据库

本地访问地址：

```text
http://127.0.0.1:9001
```

管理员登录使用 `config.json` 中的 `auth-key`。

## 2. 前置要求

本机需要安装：

- Docker
- Docker Compose v2，也就是 `docker compose` 命令

外部 PostgreSQL 需要提前准备好：

- 数据库地址和端口
- 数据库名
- 用户名和密码
- 该用户具备连接数据库、建表、读写数据的权限

如果 PostgreSQL 开启了防火墙或白名单，需要允许当前 Docker 主机访问。

## 3. 准备运行文件

进入当前项目根目录：

```bash
cd /path/to/ai2image
```

Windows PowerShell 示例：

```powershell
cd D:\Project\Github\ai2image
```

创建应用运行时目录：

```bash
mkdir -p data
```

Windows PowerShell：

```powershell
New-Item -ItemType Directory -Force data
```

创建 `config.json`：

```bash
cp config.example.json config.json
```

Windows PowerShell：

```powershell
Copy-Item config.example.json config.json
```

`config.json` 需要存在，因为 Compose 会把它挂载到容器内。管理员密钥只从 `config.json` 的 `auth-key` 读取。

## 4. 创建 .env

在项目根目录创建 `.env`：

```dotenv
IMAGESTUDIO_IMAGE=imagestudio:local
IMAGESTUDIO_PORT=9001

DATABASE_URL=postgresql://db_user:db_password@db_host:5432/db_name

CHATGPT2API_BASE_URL=http://127.0.0.1:9001
```

示例：

```dotenv
DATABASE_URL=postgresql://imagestudio:strong_password@192.168.1.10:5432/imagestudio
```

注意：

- `config.json` 中的 `auth-key` 是管理员密钥，登录后台时使用。
- `DATABASE_URL` 指向外部 PostgreSQL，不要写 `postgres:5432`，除非你的外部数据库主机名就叫 `postgres`。
- 如果数据库密码包含 `@`、`:`、`/`、`#`、空格等特殊字符，需要 URL encode。
- 如果本机 `9001` 已被占用，把 `IMAGESTUDIO_PORT` 改成其他端口，例如 `9010`，并同步修改 `CHATGPT2API_BASE_URL`。

## 5. docker-compose.yml

当前项目的 `docker-compose.yml` 应为：

```yaml
services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    image: ${IMAGESTUDIO_IMAGE:-imagestudio:local}
    container_name: imagestudio
    restart: unless-stopped
    ports:
      - "${IMAGESTUDIO_PORT:-9001}:9001"
    volumes:
      - ./data:/app/data
      - ./config.json:/app/config.json
    environment:
      STORAGE_BACKEND: postgres
      DATABASE_URL: ${DATABASE_URL:?DATABASE_URL is required}
      CHATGPT2API_BASE_URL: ${CHATGPT2API_BASE_URL:-}
```

说明：

- `build: .` 表示基于当前项目代码构建镜像。
- `image: imagestudio:local` 是本地构建出的镜像名。
- `STORAGE_BACKEND=postgres` 固定使用 PostgreSQL。
- `DATABASE_URL` 从 `.env` 读取，指向外部 PostgreSQL。
- `./data` 保存应用生成的图片、附件等运行时文件。

## 6. 构建镜像

在项目根目录执行：

```bash
docker build -t imagestudio:local .
```

确认镜像已生成：

```bash
docker image ls imagestudio
```

也可以直接使用 Compose 构建：

```bash
docker compose build app
```

每次修改当前项目代码后，都需要重新构建镜像。

## 7. 启动服务

启动：

```bash
docker compose up -d
```

查看容器状态：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f app
```

健康检查：

```bash
curl http://127.0.0.1:9001/health
```

如果 `.env` 中修改了 `IMAGESTUDIO_PORT`，健康检查端口也要同步修改。

## 8. 登录后台

打开：

```text
http://127.0.0.1:9001/login
```

选择“管理员”，输入 `config.json` 中的：

```text
auth-key
```

## 9. 更新代码后的部署流程

修改代码后，重新构建并重启应用容器：

```bash
docker build -t imagestudio:local .
docker compose up -d --force-recreate app
```

如果前端页面没有更新，可以强制无缓存构建：

```bash
docker build --no-cache -t imagestudio:local .
docker compose up -d --force-recreate app
```

外部 PostgreSQL 不会因为重建应用镜像而受影响。

## 10. 停止和重启

停止服务但保留容器：

```bash
docker compose stop
```

重启服务：

```bash
docker compose restart
```

停止并删除容器，但保留 `data/`：

```bash
docker compose down
```

删除本地构建镜像：

```bash
docker image rm imagestudio:local
```

不要随意删除：

- `data/`
- `config.json`
- `.env`

否则会丢失应用文件、配置或管理员密钥。数据库数据在外部 PostgreSQL 中，需要按外部数据库自己的备份策略处理。

## 11. 外部 PostgreSQL 检查

可以先在宿主机测试数据库连接：

```bash
psql "postgresql://db_user:db_password@db_host:5432/db_name"
```

如果宿主机能连接，但容器连接失败，通常是以下原因：

- PostgreSQL 只允许本机访问，没有允许 Docker 主机 IP
- 云数据库安全组没有放行 Docker 主机出口 IP
- `DATABASE_URL` 中的主机名在容器内无法解析
- 密码包含特殊字符但没有 URL encode
- 数据库用户没有建表或写入权限

如果外部数据库运行在宿主机本机：

- Docker Desktop Windows / macOS 通常可以用 `host.docker.internal`
- Linux 可以使用宿主机局域网 IP，或额外配置 Docker host-gateway

示例：

```dotenv
DATABASE_URL=postgresql://imagestudio:strong_password@host.docker.internal:5432/imagestudio
```

## 12. 备份

需要备份两类数据：

- 外部 PostgreSQL 数据库
- 本项目本地运行时文件：`data/`、`config.json`、`.env`

外部 PostgreSQL 建议使用数据库平台自己的备份机制，或者使用 `pg_dump`：

```bash
pg_dump "postgresql://db_user:db_password@db_host:5432/db_name" > imagestudio-db.sql
```

备份本地运行时文件：

```bash
tar -czf imagestudio-files-backup.tar.gz data config.json .env
```

Windows 可直接压缩 `data`、`config.json`、`.env`。

## 13. 常见问题

### 1. 提示 auth-key 未设置

检查 `config.json` 是否存在并包含：

```json
{
  "auth-key": "replace_with_a_long_random_admin_key"
}
```

然后重启：

```bash
docker compose up -d --force-recreate app
```

### 2. 提示 DATABASE_URL is required

说明 `.env` 没有配置 `DATABASE_URL`，或当前目录不是 `docker-compose.yml` 所在目录。

检查：

```bash
cat .env
docker compose config
```

### 3. 数据库连接失败

查看日志：

```bash
docker compose logs app
```

重点检查：

- `DATABASE_URL` 是否正确
- 外部 PostgreSQL 是否允许当前机器访问
- 数据库用户是否有权限
- 密码是否需要 URL encode

### 4. 端口被占用

修改 `.env`：

```dotenv
IMAGESTUDIO_PORT=9010
CHATGPT2API_BASE_URL=http://127.0.0.1:9010
```

重启：

```bash
docker compose up -d
```

访问：

```text
http://127.0.0.1:9010
```

### 5. 修改代码后页面没变

重新构建应用镜像：

```bash
docker build --no-cache -t imagestudio:local .
docker compose up -d --force-recreate app
```

然后刷新浏览器缓存。

### 6. 查看当前使用的存储后端

请求健康检查：

```bash
curl http://127.0.0.1:9001/health
```

返回内容中的 `storage.backend` 应该是：

```json
"postgres"
```
