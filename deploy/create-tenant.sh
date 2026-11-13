#!/usr/bin/env bash
# 南海数港 Nanhai Digital Port — 新租户开通脚本
# 作用：给一个客户建一个 LiteLLM Team（租户）+ 一把虚拟 API Key（带预算上限）
# 用法：LITELLM_BASE_URL=http://127.0.0.1:4000 LITELLM_MASTER_KEY='sk-...' \
#         ./create-tenant.sh "客户公司名" 5000000 '["gpt-4o","deepseek-chat","qwen-max"]'
#   参数1：租户名；参数2：预付款额度（美元，LiteLLM 预算以美元计）；参数3：可用模型 JSON 数组
# 注意：本脚本只做开通演示；正式的预付款台账（人民币入账、余额扣减、账单）见方案文档第 6 节，
#      由计费层按 LiteLLM 的用量统计对账，LiteLLM 本身只负责“预算上限 + 用量统计”，不管人民币收钱。
set -euo pipefail

BASE_URL="${LITELLM_BASE_URL:-http://127.0.0.1:4000}"
MASTER_KEY="${LITELLM_MASTER_KEY:?请先 export LITELLM_MASTER_KEY}"
TENANT_NAME="${1:?用法：./create-tenant.sh \"客户公司名\" 预算(美元) '[\"模型1\",\"模型2\"]'}"
BUDGET_USD="${2:?缺少预算（美元）}"
MODELS_JSON="${3:-[]}"

echo "== 1/2 创建租户 Team：$TENANT_NAME =="
TEAM_RESP=$(curl -fsS "$BASE_URL/team/new" \
  -H "Authorization: Bearer $MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"team_alias\": \"$TENANT_NAME\", \"models\": $MODELS_JSON, \"max_budget\": $BUDGET_USD, \"budget_duration\": \"1y\", \"tpm_limit\": 1000000, \"rpm_limit\": 1000}")
TEAM_ID=$(echo "$TEAM_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('team_id',''))")
echo "Team ID: $TEAM_ID"

echo "== 2/2 为该租户生成虚拟 API Key（预算 ${BUDGET_USD} 美元，1 年） =="
# —— 取自 Kong AI Gateway 的精华：按租户（Consumer）做速率限制
# Kong 以 Consumer / Consumer Group 多租户 + 每 Consumer 限流（ai-rate-limiting）见长；
# LiteLLM 的 Team（租户）+ Key（租户的调用凭证）正好对应 Kong 的 Consumer Group + Consumer，
# 这里给 Key 也加上 rpm/tpm 上限（与 Team 的上限一致），防止单个租户把网关打满。
KEY_RESP=$(curl -fsS "$BASE_URL/key/generate" \
  -H "Authorization: Bearer $MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"team_id\": \"$TEAM_ID\", \"models\": $MODELS_JSON, \"max_budget\": $BUDGET_USD, \"budget_duration\": \"1y\", \"rpm_limit\": 1000, \"tpm_limit\": 1000000, \"metadata\": {\"tenant\": \"$TENANT_NAME\", \"plan\": \"nanhai-prepaid\"}}")
echo "$KEY_RESP" | python3 -m json.tool
echo
echo "把上面 key 字段里的 sk-... 发给客户即可。客户调用示例："
echo "curl $BASE_URL/v1/chat/completions -H \"Authorization: Bearer <客户的虚拟Key>\" -d '{\"model\": \"gpt-4o\", \"messages\": [{\"role\": \"user\", \"content\": \"你好\"}]}'"
echo "用量查询：Admin UI $BASE_URL/ui ，或 GET $BASE_URL/team/info?team_id=$TEAM_ID"
