# 南海数港 Nanhai Digital Port — API 平台部署说明

> 品牌：南海数港 Nanhai Digital Port
> 底座：LiteLLM Proxy（MIT 开源，美国 BerriAI，旧金山）+ PostgreSQL + Redis
> 取其精华：骨架是 LiteLLM（统一代理 + 多租户计费），可靠性层取自 Portkey Gateway（故障转移 + 重试 + 语义缓存 + 护栏），多租户治理模式取自 Kong（Consumer Group + 按租户限流）。三家精华拼成一个新平台，不是三家全量合体（详见方案文档 §2.3）。
> 对外接口：统一 OpenAI 兼容 API，`http://<服务器>:4000/v1/chat/completions`
> 技术支持：sales@aaronalphax.com

---

## 1. 部署前准备

- 一台 Linux 服务器（建议 2 核 4GB 起），已装 Docker 与 Docker Compose v2。
- 各模型厂商的 API Key（按需申请，哪个模型要上就申请哪个；不要的留空）。
  - 美国：OpenAI、Anthropic、Google Gemini、xAI
  - 中国：DeepSeek、通义千问（DashScope）、智谱、Kimi（Moonshot）、百度千帆
- 域名（可选）：把 `api.nanhai.example` 之类指到服务器，前面再挂 Nginx + HTTPS（生产必须）。

## 2. 一键启动

```bash
cd deploy
cp .env.example .env
# 编辑 .env：生成 LITELLM_MASTER_KEY、LITELLM_SALT_KEY（openssl rand -hex 32），
# 填 POSTGRES_PASSWORD，填各厂商 API Key（只填要上的）
nano .env

docker compose up -d
docker compose ps          # 四个容器（litellm / db / redis / portal）都 healthy 即正常
docker compose logs -f litellm   # 看启动日志
```

## 3. 验证

```bash
# 健康检查
curl http://127.0.0.1:4000/health

# 管理员调用（用主密钥）
curl http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o", "messages": [{"role": "user", "content": "你好"}]}'
```

## 4. 后台（Admin UI）与客户门户

**网关后台（给运营方）**：打开 `http://<服务器>:4000/ui`，用户名 `admin`，密码就是 `.env` 里的 `LITELLM_MASTER_KEY`。
后台实时可见：

- **Models + Endpoints**：已接模型、连通性测试、单价
- **Virtual Keys**：每个租户的 Key、预算、已用、剩余额度
- **Teams**：租户（团队）列表、成员、模型白名单、预算
- **Usage / Spend**：按 Key / 团队 / 模型的用量与花费
- **Logs**：每次请求的延迟、Token 数、状态
- **Playground**：直接在后台试模型

**客户门户（给客户）**：打开 `http://<服务器>:8080`。
客户用**邮箱 + 密码**注册租户、登录后进仪表盘，可点可用：

- **API Key**：一键复制；网关虚拟 Key 同步后自动更新
- **预付款余额**：实时余额（人民币）
- **用量**：网关已用花费（美元，从 LiteLLM 拉取）
- **模型目录**：中美模型列表（中国／美国标识）
- **账单**：充值与扣费记录
- **管理员视图**：管理员登录后看全部租户、给租户充值

门户是 Python 标准库零依赖服务（`portal/`），已在本机实测通过：注册、登录、仪表盘、管理员充值、错误密码拒绝全部走通。

## 5. 开通一个租户（多租户 + 预付款）

```bash
export LITELLM_BASE_URL=http://127.0.0.1:4000
export LITELLM_MASTER_KEY='sk-...'   # .env 里那个
chmod +x create-tenant.sh
./create-tenant.sh "客户公司名" 5000000 '["gpt-4o","deepseek-chat","qwen-max"]'
```

脚本会做两件事：建一个 Team（租户），再给它生成一把虚拟 API Key（带预算上限）。
把 Key 发给客户，客户用 OpenAI SDK 指到 `http://<服务器>:4000` 就能调。

**预付款怎么落：**
LiteLLM 的 `max_budget` 是按美元计的“花费上限”，它负责两件事：超了就拒绝 + 统计每把 Key 花了多少。
人民币预付款的收钱、汇率换算、余额台账、账单开票不在 LiteLLM 里，由计费层做（见方案文档第 6 节）：
开通时按当时汇率把人民币预付款折成美元预算写入 Key；每月初从 LiteLLM 拉用量对账、扣余额、发账单；余额到零自动停服，续费后调高预算即恢复。

## 6. 日常运维

```bash
# 看日志
docker compose logs -f litellm
# 重启网关（改了 litellm_config.yaml 后）
docker compose restart litellm
# 备份数据库（虚拟 Key、团队、用量全在里面）
docker compose exec db pg_dump -U llmproxy litellm > backup-$(date +%F).sql
# 升级 LiteLLM（先在测试环境验，再升生产；镜像用 -stable 标签）
docker compose pull litellm && docker compose up -d litellm
```

## 7. 安全清单（上线前必做）

- [ ] 4000 端口不要直接暴露公网；前面挂 Nginx + HTTPS，只放行 `/v1/*`，`/ui` 限内网或加 IP 白名单
- [ ] `LITELLM_MASTER_KEY`、`LITELLM_SALT_KEY`、`POSTGRES_PASSWORD` 用 `openssl rand -hex 32` 生成，不要用示例值
- [ ] `.env` 权限 600，不要提交到任何公开仓库
- [ ] 上游厂商 Key 只放环境变量，不要写进 `litellm_config.yaml`
- [ ] 定期备份 Postgres；`LITELLM_SALT_KEY` 单独备份（丢了就解不开存量 Key）
- [ ] 给每个租户的 Key 设 `max_budget` 和模型白名单，不要发不限额的 Key

## 8. 文件说明

| 文件 | 作用 |
|---|---|
| `docker-compose.yml` | LiteLLM + Postgres + Redis + 客户门户 一键部署 |
| `litellm_config.yaml` | 中美模型路由、别名、故障转移（Portkey 精华）、语义缓存（Portkey 精华）、护栏示例（Portkey 精华） |
| `.env.example` | 环境变量模板（只有占位符，无真实密钥） |
| `create-tenant.sh` | 开通租户 + 生成带预算的虚拟 Key（含按租户限流，Kong 精华） |
| `README.md` | 本文件 |

## 9. 故障排除

- **LiteLLM 启动即崩，日志报 `httpx.InvalidURL: Invalid port: ':1]'`**：原因是宿主机 `no_proxy` / `NO_PROXY` 环境变量里有方括号 IPv6 地址（如 `[fd8b:...::1]`），httpx 解析会崩。解法：在启动 LiteLLM 的 shell 里清掉全部代理环境变量（大小写都要清）：`env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy -u no_proxy -u NO_PROXY`。本机 VM 实测：清掉后代理正常启动，`/health` 200、`/v1/models` 200、`/ui` 307。
- **`/key/generate` 报 500**：虚拟 Key 持久化需要 Postgres；检查 `db` 容器是否 healthy、`DATABASE_URL` 是否正确。无 DB 模式下代理能跑，但 Key / Team / 预算不持久化。
- **缓存不生效**：检查 `redis` 容器是否 healthy、`REDIS_HOST` 是否传给 litellm 服务（见 docker-compose.yml）。

技术支持：sales@aaronalphax.com
