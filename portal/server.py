#!/usr/bin/env python3
"""南海数港 Nanhai Digital Port — 客户门户（Customer Portal）

一个零依赖的客户门户（只用 Python 标准库），提供：
  - 邮箱 + 密码 注册 / 登录（不是手机验证码）
  - 租户仪表盘：API Key、预付款余额、用量、模型目录、账单
  - 管理员视图：租户列表、调余额、发 Key
  - 与 LiteLLM 网关联动：注册时自动在 LiteLLM 建 Team + 虚拟 Key（若网关可达）

运行：python3 server.py  （默认 :8080，数据库 portal.db 在同目录）
环境变量：
  PORT            监听端口（默认 8080）
  DB_PATH         SQLite 路径（默认 ./portal.db）
  LITELLM_URL     LiteLLM 网关地址（默认 http://127.0.0.1:4000；留空则不同步）
  LITELLM_MASTER_KEY  LiteLLM 主密钥（用于建 Team / Key；没有则只发本地 Key）
  ADMIN_PASSWORD  管理员密码（默认 changeme，请务必改掉）
技术支持：sales@aaronalphax.com
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("PORT", "8080"))
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "portal.db"))
LITELLM_URL = os.environ.get("LITELLM_URL", "http://127.0.0.1:4000").rstrip("/")
LITELLM_MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# 模型目录（与 deploy/litellm_config.yaml 保持一致；价格签约前到官方页重核）
MODELS = [
    {"name": "gpt-4o", "provider": "OpenAI", "region": "US", "note": "通用旗舰"},
    {"name": "gpt-4o-mini", "provider": "OpenAI", "region": "US", "note": "轻量快速"},
    {"name": "claude-sonnet-4-5", "provider": "Anthropic", "region": "US", "note": "长文与代码"},
    {"name": "claude-haiku-4-5", "provider": "Anthropic", "region": "US", "note": "轻量快速"},
    {"name": "gemini-2.5-flash", "provider": "Google", "region": "US", "note": "多模态"},
    {"name": "gemini-2.5-pro", "provider": "Google", "region": "US", "note": "多模态旗舰"},
    {"name": "grok-4", "provider": "xAI", "region": "US", "note": "实时性"},
    {"name": "deepseek-chat", "provider": "DeepSeek", "region": "CN", "note": "高性价比"},
    {"name": "deepseek-reasoner", "provider": "DeepSeek", "region": "CN", "note": "深度推理"},
    {"name": "qwen-max", "provider": "Qwen 通义千问", "region": "CN", "note": "中文旗舰"},
    {"name": "qwen-plus", "provider": "Qwen 通义千问", "region": "CN", "note": "均衡"},
    {"name": "qwen-turbo", "provider": "Qwen 通义千问", "region": "CN", "note": "轻量快速"},
    {"name": "glm-4-plus", "provider": "Zhipu 智谱", "region": "CN", "note": "通用旗舰"},
    {"name": "glm-4.7-flash", "provider": "Zhipu 智谱", "region": "CN", "note": "免费层"},
    {"name": "moonshot-v1-8k", "provider": "Kimi 月之暗面", "region": "CN", "note": "长上下文"},
    {"name": "moonshot-v1-32k", "provider": "Kimi 月之暗面", "region": "CN", "note": "长上下文"},
    {"name": "moonshot-v1-128k", "provider": "Kimi 月之暗面", "region": "CN", "note": "超长上下文"},
    {"name": "ernie-4.0-8k", "provider": "Baidu 百度千帆", "region": "CN", "note": "通用"},
    {"name": "ernie-3.5-8k", "provider": "Baidu 百度千帆", "region": "CN", "note": "轻量"},
    {"name": "nanhai-chat", "provider": "Nanhai 精选", "region": "US", "note": "默认对话路由"},
    {"name": "nanhai-chat-cn", "provider": "Nanhai 精选", "region": "CN", "note": "默认中文路由"},
    {"name": "nanhai-reasoning", "provider": "Nanhai 精选", "region": "CN", "note": "默认推理路由"},
    {"name": "nanhai-fast", "provider": "Nanhai 精选", "region": "US", "note": "默认快速路由"},
]


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        tenant_name TEXT NOT NULL,
        api_key TEXT NOT NULL,
        litellm_key TEXT DEFAULT '',
        litellm_team_id TEXT DEFAULT '',
        balance_cny REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'active',
        created_at INTEGER NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS sessions(
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        is_admin INTEGER NOT NULL DEFAULT 0,
        expires_at INTEGER NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS ledger(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        amount_cny REAL NOT NULL,
        note TEXT DEFAULT '',
        created_at INTEGER NOT NULL)""")
    conn.commit()
    return conn


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()


def new_api_key():
    return "sk-nanhai-" + secrets.token_urlsafe(24)


def litellm_call(path, payload):
    """调用 LiteLLM 管理 API；网关不可达时返回 None（不抛错）。"""
    if not LITELLM_MASTER_KEY:
        return None
    try:
        req = urllib.request.Request(
            LITELLM_URL + path,
            data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + LITELLM_MASTER_KEY,
                     "Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def litellm_spend(api_key):
    """查一把虚拟 Key 的已用花费（美元）；拿不到返回 None。"""
    if not LITELLM_MASTER_KEY or not api_key:
        return None
    try:
        req = urllib.request.Request(
            LITELLM_URL + "/key/info?key=" + api_key,
            headers={"Authorization": "Bearer " + LITELLM_MASTER_KEY},
            method="GET")
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode())
            info = d.get("info", d)
            return {"spend_usd": info.get("spend"),
                    "max_budget_usd": info.get("max_budget"),
                    "expires": info.get("expires")}
    except Exception:
        return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # ---------- helpers ----------
    def send_json(self, code, obj, extra_headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_html_file(self, name, code=200):
        path = os.path.join(STATIC_DIR, name)
        try:
            with open(path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode())
        except Exception:
            return {}

    def current_user(self):
        cookie = self.headers.get("Cookie") or ""
        m = re.search(r"nanhai_session=([^;]+)", cookie)
        if not m:
            return None
        conn = db()
        row = conn.execute(
            "SELECT * FROM sessions WHERE token=? AND expires_at>?",
            (m.group(1), int(time.time()))).fetchone()
        if not row:
            conn.close()
            return None
        if row["is_admin"]:
            conn.close()
            return {"id": 0, "email": "admin", "is_admin": True}
        u = conn.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone()
        conn.close()
        if not u:
            return None
        return dict(u) | {"is_admin": False}

    def set_session(self, user_id, is_admin=False):
        token = secrets.token_urlsafe(32)
        conn = db()
        conn.execute("INSERT INTO sessions(token,user_id,is_admin,expires_at) VALUES(?,?,?,?)",
                     (token, user_id, 1 if is_admin else 0, int(time.time()) + 86400))
        conn.commit()
        conn.close()
        return token

    # ---------- routes ----------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/login", "/register", "/dashboard", "/admin"):
            return self.send_html_file("index.html")
        if path == "/api/me":
            u = self.current_user()
            if not u:
                return self.send_json(401, {"error": "未登录"})
            if u.get("is_admin"):
                return self.send_json(200, {"email": "admin", "is_admin": True})
            spend = litellm_spend(u.get("litellm_key") or u["api_key"])
            return self.send_json(200, {
                "email": u["email"], "tenant_name": u["tenant_name"],
                "api_key": u["api_key"],
                "litellm_key": u.get("litellm_key") or "",
                "balance_cny": u["balance_cny"], "status": u["status"],
                "created_at": u["created_at"], "litellm_spend": spend,
            })
        if path == "/api/models":
            return self.send_json(200, {"models": MODELS})
        if path == "/api/ledger":
            u = self.current_user()
            if not u or u.get("is_admin"):
                return self.send_json(401, {"error": "未登录"})
            conn = db()
            rows = conn.execute(
                "SELECT kind, amount_cny, note, created_at FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 50",
                (u["id"],)).fetchall()
            conn.close()
            return self.send_json(200, {"ledger": [dict(r) for r in rows]})
        if path == "/api/admin/tenants":
            u = self.current_user()
            if not u or not u.get("is_admin"):
                return self.send_json(401, {"error": "需要管理员登录"})
            conn = db()
            rows = conn.execute(
                "SELECT id, email, tenant_name, balance_cny, status, created_at FROM users ORDER BY id DESC").fetchall()
            conn.close()
            return self.send_json(200, {"tenants": [dict(r) for r in rows]})
        if path == "/api/health":
            return self.send_json(200, {"ok": True, "service": "nanhai-portal",
                                         "litellm_reachable": litellm_call("/health", {}) is not None})
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        data = self.read_json()

        if path == "/api/register":
            email = (data.get("email") or "").strip().lower()
            password = data.get("password") or ""
            tenant = (data.get("tenant_name") or "").strip()
            if not EMAIL_RE.match(email):
                return self.send_json(400, {"error": "邮箱格式不正确"})
            if len(password) < 8:
                return self.send_json(400, {"error": "密码至少 8 位"})
            if not tenant:
                return self.send_json(400, {"error": "请填写公司 / 租户名"})
            salt = secrets.token_hex(16)
            conn = db()
            try:
                cur = conn.execute(
                    "INSERT INTO users(email,password_hash,salt,tenant_name,api_key,balance_cny,created_at) VALUES(?,?,?,?,?,?,?)",
                    (email, hash_password(password, salt), salt, tenant, new_api_key(), 0, int(time.time())))
                uid = cur.lastrowid
                conn.commit()
            except sqlite3.IntegrityError:
                conn.close()
                return self.send_json(400, {"error": "该邮箱已注册，请直接登录"})
            # 尝试在 LiteLLM 建 Team + 虚拟 Key（网关不可达则只发本地 Key，管理员后续补配）
            lit_key, team_id = "", ""
            team = litellm_call("/team/new", {"team_alias": tenant, "models": [m["name"] for m in MODELS],
                                               "max_budget": 0, "budget_duration": "1y"})
            if team and team.get("team_id"):
                team_id = team["team_id"]
                key = litellm_call("/key/generate", {"team_id": team_id,
                                                     "models": [m["name"] for m in MODELS],
                                                     "max_budget": 0, "budget_duration": "1y",
                                                     "metadata": {"tenant": tenant, "email": email}})
                if key and key.get("key"):
                    lit_key = key["key"]
            if team_id or lit_key:
                conn.execute("UPDATE users SET litellm_team_id=?, litellm_key=? WHERE id=?",
                             (team_id, lit_key, uid))
                conn.commit()
            conn.close()
            token = self.set_session(uid)
            return self.send_json(200, {"ok": True, "litellm_provisioned": bool(lit_key)},
                                  {"Set-Cookie": f"nanhai_session={token}; HttpOnly; Path=/; Max-Age=86400"})

        if path == "/api/login":
            email = (data.get("email") or "").strip().lower()
            password = data.get("password") or ""
            conn = db()
            u = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            conn.close()
            if not u or not hmac.compare_digest(hash_password(password, u["salt"]), u["password_hash"]):
                return self.send_json(401, {"error": "邮箱或密码不正确"})
            if u["status"] != "active":
                return self.send_json(403, {"error": "该账号已停用，请联系技术支持"})
            token = self.set_session(u["id"])
            return self.send_json(200, {"ok": True},
                                  {"Set-Cookie": f"nanhai_session={token}; HttpOnly; Path=/; Max-Age=86400"})

        if path == "/api/admin/login":
            if (data.get("password") or "") != ADMIN_PASSWORD or ADMIN_PASSWORD == "changeme":
                return self.send_json(401, {"error": "管理员密码不正确（或未改默认密码）"})
            token = self.set_session(0, is_admin=True)
            return self.send_json(200, {"ok": True},
                                  {"Set-Cookie": f"nanhai_session={token}; HttpOnly; Path=/; Max-Age=86400"})

        if path == "/api/logout":
            cookie = self.headers.get("Cookie") or ""
            m = re.search(r"nanhai_session=([^;]+)", cookie)
            if m:
                conn = db()
                conn.execute("DELETE FROM sessions WHERE token=?", (m.group(1),))
                conn.commit()
                conn.close()
            return self.send_json(200, {"ok": True},
                                  {"Set-Cookie": "nanhai_session=; HttpOnly; Path=/; Max-Age=0"})

        if path == "/api/admin/topup":
            u = self.current_user()
            if not u or not u.get("is_admin"):
                return self.send_json(401, {"error": "需要管理员登录"})
            user_id = data.get("user_id")
            amount = float(data.get("amount_cny") or 0)
            note = data.get("note") or "管理员充值"
            if not user_id or amount == 0:
                return self.send_json(400, {"error": "参数不正确"})
            conn = db()
            conn.execute("UPDATE users SET balance_cny = balance_cny + ? WHERE id=?", (amount, user_id))
            conn.execute("INSERT INTO ledger(user_id,kind,amount_cny,note,created_at) VALUES(?,?,?,?,?)",
                         (user_id, "topup", amount, note, int(time.time())))
            conn.commit()
            conn.close()
            return self.send_json(200, {"ok": True})

        self.send_response(404)
        self.end_headers()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    db()
    print(f"Nanhai Digital Port portal running on http://127.0.0.1:{PORT}")
    print("Support: sales@aaronalphax.com")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
