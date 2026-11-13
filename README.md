# 南海数港 Nanhai Digital Port

聚合中美 AI 模型的 API 平台：统一 OpenAI 兼容接口，多租户、预付款模式。

- **骨架**：LiteLLM Proxy（BerriAI/litellm，MIT）——统一代理、虚拟 Key / Team / 预算 / 用量统计 / Admin UI
- **可靠性层**：Portkey Gateway（Portkey-AI/gateway，MIT）——故障转移、重试、语义缓存、护栏
- **多租户治理**：Kong（Kong/kong，Apache-2.0）——Consumer / Consumer Group 多租户模型、按租户限流

取三家之精华拼成一个新平台，不是三家全量合体。详细方案见 [南海数港-API平台方案.md](南海数港-API平台方案.md)。

## 目录

- `deploy/` — 部署包：一键 `docker compose up -d`（LiteLLM + Postgres + Redis + 客户门户）
- `portal/` — 客户门户：邮箱 + 密码注册登录（不要手机验证码），Python 标准库零依赖
- `.github/workflows/nanhai-build.yml` — GitHub Actions 构建验证（浅克隆上游、校验配置、门户冒烟测试）

## 快速开始（目标服务器）

```bash
cp deploy/.env.example deploy/.env   # 填好密钥
cd deploy && docker compose up -d
```

- 客户门户：`http://<服务器>:8080`（邮箱 + 密码注册登录）
- 网关后台：`http://<服务器>:4000/ui`（用户名 `admin`，密码是主密钥）
- 客户调用：`http://<服务器>:4000/v1/chat/completions`（OpenAI 兼容）

## CI

每次 push 到 `main` 或手动触发，GitHub Actions 自动跑构建验证：
浅克隆三个上游仓库 → 校验 `docker-compose.yml` 与 `litellm_config.yaml` →
门户冒烟测试（注册 / 登录 / 错误密码拒绝）。

技术支持：sales@aaronalphax.com
