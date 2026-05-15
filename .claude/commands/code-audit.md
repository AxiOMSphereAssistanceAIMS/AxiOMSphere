# AIMS — Code Security Audit (Secrets · Injection · OWASP · Permissions)

Audit target: **$ARGUMENTS**

_This skill runs on slot 120 (nemotron-3-super:120b) for deep reasoning._

---

## Phase 0 — Scope

From `$ARGUMENTS` determine:
- **scope**: `file` | `module` | `full-repo` | `diff` (git range)
- **focus**: `secrets` | `injection` | `owasp` | `permissions` | `all` (default)

---

## Phase 1 — Secrets scan

```bash
cd /home/axi_omi_sphere/aims-workspace

# Hardcoded tokens / keys / passwords
grep -rn \
  -e "api_key\s*=\s*['\"][a-zA-Z0-9_\-]\{10,\}" \
  -e "password\s*=\s*['\"]" \
  -e "nvapi-" \
  -e "sk-" \
  -e "AIza" \
  -e "token\s*=\s*['\"][a-zA-Z0-9_\-]\{10,\}" \
  ops/ core/ --include="*.py" | grep -v ".env" | grep -v "test_" | head -30

# .env content accidentally committed
git log --all --full-history -- .env 2>/dev/null | head -5
git diff HEAD .env 2>/dev/null | head -5

# .env in git index
git ls-files .env .env.* 2>/dev/null
```

---

## Phase 2 — Injection scan

```bash
# SQL injection: f-string or % formatting into SQL
grep -rn "execute.*f['\"].*{" ops/ core/ --include="*.py" | head -20
grep -rn "execute.*%.*%" ops/ core/ --include="*.py" | head -20

# Command injection: subprocess with shell=True + user input
grep -rn "shell=True" ops/ core/ --include="*.py" | head -20
grep -rn "os\.system\|os\.popen\|eval(" ops/ core/ --include="*.py" | head -20

# Telegram / HTTP input reaching eval/exec
grep -rn "message\.text.*exec\|update.*eval" ops/ --include="*.py" | head -20
```

---

## Phase 3 — OWASP Top 10 checks

| Risk | Pattern to check | AIMS-specific context |
|------|-----------------|----------------------|
| A01 Broken Access Control | PoliAgent bypass, role checks | ops/agents/poli_agent.py |
| A02 Crypto failures | plaintext secrets in DB | data/aims_registry.db schema |
| A03 Injection | SQL/cmd as above | SQLite execute() calls |
| A05 Security misconfig | debug=True in prod, CORS * | ops/gateway/anthropic_proxy.py |
| A06 Vulnerable components | outdated deps | requirements.txt |
| A07 Auth failures | token validation in proxy | AIMS_CLAUDE_PROXY_TOKEN check |
| A09 Security logging | missing audit trail | aims_workspace/audit/ |

```bash
# Check proxy token validation exists
grep -n "AIMS_CLAUDE_PROXY_TOKEN\|Authorization\|Bearer" ops/gateway/anthropic_proxy.py | head -20

# CORS config
grep -n "allow_origins\|CORSMiddleware" ops/gateway/anthropic_proxy.py | head -10

# Debug mode in production
grep -rn "debug=True\|DEBUG=True" ops/ docker-compose.yml --include="*.py" | grep -v test | head -10
```

---

## Phase 4 — Permission model audit

```bash
# PoliAgent integration — is it called before destructive ops
grep -rn "poli\|PoliAgent\|approval" ops/agents/ ops/workers/ --include="*.py" | head -20

# Repairman forbidden actions — verify CLAUDE.md restrictions in code
grep -rn "exfiltrate\|bypass_poli\|delete_production" ops/ --include="*.py" | head -10

# File permission audit
find ops/ -name "*.sh" -perm /111 | head -20
find data/ -name "*.db" -perm /o+w 2>/dev/null
```

---

## Phase 5 — Output contract

```json
{
  "audit_target": "$ARGUMENTS",
  "scope": "<file|module|repo|diff>",
  "findings": [
    {
      "severity": "critical|high|medium|low|info",
      "category": "secret|injection|owasp|permission",
      "owasp_ref": "A0N",
      "location": "<file:line>",
      "description": "<what was found>",
      "remediation": "<how to fix>"
    }
  ],
  "secrets_found": false,
  "injection_risks": 0,
  "permission_gaps": 0,
  "overall_risk": "critical|high|medium|low|clean",
  "slot_used": "120"
}
```
