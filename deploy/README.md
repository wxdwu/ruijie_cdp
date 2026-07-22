# Ruijie CDP — 部署套件

本目录按部署场景拆分为两套独立套件：

| 目录 | 场景 | 服务 | 数据库 |
|---|---|---|---|
| [`deploy_cloud/`](./deploy_cloud) | 公网 / 独立服务器部署 | 本机 docker MySQL + 后端 + 前端(Nginx) | 本机 MySQL（首次启动自动初始化） |
| [`deploy_local/`](./deploy_local) | 局域网内部署（仅前后端） | 后端 + 前端(Nginx) | 远程云 MySQL（`backend/.env.development`） |

## 如何选择

- **公网 / 不同公网 IP 独立部署全套（含本地数据库）** → 用 `deploy_cloud/`。
  适合对外提供服务、希望数据库与应用同机或同网段、首次部署自动建表灌数的场景。
- **局域网内只跑前后端、统一连云端数仓** → 用 `deploy_local/`。
  不部署 MySQL、不执行 sql_init，backend 通过 `APP_ENV=development` 连 `192.168.159.22:33307` 云库。

两套均使用 `network_mode: host`（规避 podman 3.x 的 CNI 问题），构建上下文均为**项目根目录**，
`docker-compose.yml` 内 `context: ../../` + `dockerfile: deploy/<套件>/xxx.Dockerfile`。

详细步骤分别见各子目录的 `README.md`。
