# 南海数港 Nanhai Digital Port — 客户门户（Customer Portal）
# 零依赖：只用 Python 标准库（http.server + sqlite3）。启动即用，不用装任何包。
# 本地运行：python3 server.py  → 打开 http://127.0.0.1:8080
# Docker 运行：见 ../deploy/docker-compose.yml 的 portal 服务。
#
# 功能：
#   - 邮箱 + 密码 注册 / 登录（不是手机验证码）
#   - 租户仪表盘：API Key（一键复制）、预付款余额、用量、模型目录、账单记录
#   - 管理员视图：租户列表、给租户充值
#   - 与 LiteLLM 联动：注册时自动在 LiteLLM 建 Team + 虚拟 Key（网关可达时）
#
# 环境变量：
#   PORT                 监听端口（默认 8080）
#   DB_PATH              SQLite 路径（默认 ./portal.db）
#   LITELLM_URL          LiteLLM 网关地址（默认 http://127.0.0.1:4000；留空则不同步）
#   LITELLM_MASTER_KEY   LiteLLM 主密钥（用于建 Team / Key）
#   ADMIN_PASSWORD       管理员密码（默认 changeme，上线前务必改掉）
#
# 技术支持：sales@aaronalphax.com
