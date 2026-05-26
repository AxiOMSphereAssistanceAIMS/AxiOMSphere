/**
 * Public deployment security gate for axiomsphereai.com
 *
 * Checks that the dist/ build contains no credentials, internal paths,
 * source maps, or private governance content before any public push.
 *
 * Exit 0 = PASS, Exit 1 = FAIL
 */

import fs from "fs"
import path from "path"
import { fileURLToPath } from "url"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const DIST = path.resolve(__dirname, "../dist")

// ── Helpers ──────────────────────────────────────────────────────────────────

function walk(dir, files = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isSymbolicLink()) {
      files.push({ path: full, isSymlink: true })
    } else if (entry.isDirectory()) {
      walk(full, files)
    } else {
      files.push({ path: full, isSymlink: false })
    }
  }
  return files
}

let passed = 0
let failed = 0
const issues = []

function pass(label) {
  console.log(`  ✓  ${label}`)
  passed++
}

function fail(label, detail = "") {
  console.error(`  ✗  ${label}${detail ? `\n       ${detail}` : ""}`)
  failed++
  issues.push(label + (detail ? ` — ${detail}` : ""))
}

function readText(filePath) {
  try {
    return fs.readFileSync(filePath, "utf8")
  } catch {
    return null
  }
}

// ── Checks ───────────────────────────────────────────────────────────────────

console.log("\n═══════════════════════════════════════════════")
console.log("  AXIOMSPHERE PUBLIC DEPLOY SECURITY GATE")
console.log("═══════════════════════════════════════════════\n")

// 1. Dist directory must exist
if (!fs.existsSync(DIST)) {
  console.error("FATAL: dist/ not found. Run npm run build first.")
  process.exit(1)
}
console.log(`Scanning: ${DIST}\n`)

const allFiles = walk(DIST)

// ── CHECK 1: No symlinks in dist ──────────────────────────────────────────────
console.log("[ 1 ] Symlink scan")
const symlinks = allFiles.filter((f) => f.isSymlink)
if (symlinks.length === 0) {
  pass("No symlinks found in dist/")
} else {
  for (const s of symlinks) {
    fail("Symlink detected in dist/", path.relative(DIST, s.path))
  }
}

// ── CHECK 2: No source maps ───────────────────────────────────────────────────
console.log("\n[ 2 ] Source map scan")
const mapFiles = allFiles.filter((f) => f.path.endsWith(".map"))
if (mapFiles.length === 0) {
  pass("No .map files in dist/")
} else {
  for (const m of mapFiles) {
    fail("Source map file found", path.relative(DIST, m.path))
  }
}

// ── CHECK 3: No .env or backup files ─────────────────────────────────────────
console.log("\n[ 3 ] Env / backup file scan")
const dangerousFiles = allFiles.filter((f) => {
  const name = path.basename(f.path)
  return (
    name === ".env" ||
    name.startsWith(".env.") ||
    name.endsWith(".env") ||
    name.endsWith(".bak") ||
    name.endsWith(".backup") ||
    /\.env\.backup/.test(name)
  )
})
if (dangerousFiles.length === 0) {
  pass("No .env or backup files in dist/")
} else {
  for (const d of dangerousFiles) {
    fail(".env / backup file in dist/", path.relative(DIST, d.path))
  }
}

// ── CHECK 4: No internal Markdown / governance docs ──────────────────────────
console.log("\n[ 4 ] Internal document scan")
const mdFiles = allFiles.filter((f) => f.path.endsWith(".md") || f.path.endsWith(".jsonl"))
if (mdFiles.length === 0) {
  pass("No .md / .jsonl files in dist/")
} else {
  for (const m of mdFiles) {
    fail("Internal document in dist/", path.relative(DIST, m.path))
  }
}

// ── CHECK 5: Prohibited patterns in text files ────────────────────────────────
console.log("\n[ 5 ] Prohibited string scan (HTML/JS/CSS)")

const textExtensions = new Set([".html", ".js", ".css", ".txt", ".json", ".xml", ".svg"])

const PROHIBITED = [
  // Credential patterns
  { pattern: /nvapi-[A-Za-z0-9_-]{10,}/, label: "NVIDIA API key (nvapi-...)" },
  { pattern: /sk-[a-f0-9]{16,}/, label: "Internal token (sk-...)" },
  { pattern: /AIMS_CLAUDE_PROXY_TOKEN\s*=/, label: "Env var AIMS_CLAUDE_PROXY_TOKEN" },
  { pattern: /NVIDIA_API_KEY\s*=/, label: "Env var NVIDIA_API_KEY" },

  // Internal filesystem paths
  { pattern: /\/home\/axi_omi_sphere\/aims-workspace\/(?!website)/, label: "Internal workspace path" },
  { pattern: /aims-private-governance/, label: "Private governance directory name" },

  // Internal service URLs (port in URL context, not bare number)
  { pattern: /localhost:8082/, label: "Internal service port 8082 (gateway)" },
  { pattern: /localhost:8767/, label: "Internal service port 8767 (docagent)" },
  { pattern: /localhost:8765/, label: "Internal service port 8765 (task-registry)" },
  { pattern: /localhost:8010/, label: "Internal service port 8010 (repairman)" },
  { pattern: /localhost:11434/, label: "Internal service port 11434 (ollama)" },
  { pattern: /localhost:6333/, label: "Internal service port 6333 (qdrant)" },
  { pattern: /localhost:4400/, label: "Internal service port 4400 (litellm)" },

  // Internal bot/file names that should never appear in public output
  { pattern: /repairman_api\.py/, label: "Internal file name repairman_api.py" },
  { pattern: /argus_bot\.py/, label: "Internal file name argus_bot.py" },
  { pattern: /axi_bot\.py/, label: "Internal file name axi_bot.py" },
  { pattern: /omi_agent\.py/, label: "Internal file name omi_agent.py" },
  { pattern: /PLAN_INTERNAL/, label: "Internal doc PLAN_INTERNAL" },
  { pattern: /PROJECT_CONSTITUTION/, label: "Internal doc PROJECT_CONSTITUTION" },
  { pattern: /AGENTS_BOTS_COORDINATION/, label: "Internal doc AGENTS_BOTS_COORDINATION" },
  { pattern: /aims-private-governance/, label: "Private governance dir reference" },

  // Internal governance doc name from Credits.tsx (pre-fix check)
  {
    pattern: /AXIOMSPHERE_90_DAY_AGENT_TEAM_AND_CONTROLLED_AUTONOMY_VALIDATION_PLAN/,
    label: "Internal doc name in Credits link (should be removed)",
  },
]

const textFiles = allFiles.filter((f) => {
  const ext = path.extname(f.path).toLowerCase()
  return textExtensions.has(ext) && !f.isSymlink
})

let patternIssues = 0
for (const fileEntry of textFiles) {
  const content = readText(fileEntry.path)
  if (!content) continue
  const rel = path.relative(DIST, fileEntry.path)
  const lines = content.split("\n")

  for (const { pattern, label } of PROHIBITED) {
    for (let i = 0; i < lines.length; i++) {
      if (pattern.test(lines[i])) {
        fail(`Prohibited pattern: ${label}`, `${rel}:${i + 1}`)
        patternIssues++
        break // one report per pattern per file is enough
      }
    }
  }
}
if (patternIssues === 0) {
  pass("No prohibited patterns found in dist/ text files")
}

// ── CHECK 6: Required copyright strings present in index.html ────────────────
console.log("\n[ 6 ] Required copyright / legal strings in index.html")

const indexHtml = readText(path.join(DIST, "index.html"))
if (!indexHtml) {
  fail("index.html not found in dist/")
} else {
  const REQUIRED = [
    "© 2026 AxiOMSphere",
    "All rights reserved",
    "AxiOMSphere and associated product materials are proprietary",
  ]
  for (const str of REQUIRED) {
    if (indexHtml.includes(str)) {
      pass(`Required string present: "${str}"`)
    } else {
      fail(`Required string MISSING: "${str}"`)
    }
  }
}

// ── CHECK 7: Required public content strings in index.html ───────────────────
console.log("\n[ 7 ] Required public content strings in index.html")

if (indexHtml) {
  const PUBLIC_CONTENT = [
    "AxiOMSphere",
    "Privacy-first industrial AI",
    "AIMS work-product",
    "Asset Integrity",
    "90-Day Validation",
  ]
  for (const str of PUBLIC_CONTENT) {
    if (indexHtml.includes(str)) {
      pass(`Public content present: "${str}"`)
    } else {
      fail(`Public content MISSING: "${str}"`)
    }
  }
}

// ── CHECK 8: File type allowlist in dist/ ────────────────────────────────────
console.log("\n[ 8 ] File type allowlist")

const ALLOWED_EXTENSIONS = new Set([
  ".html", ".js", ".css", ".png", ".jpg", ".jpeg",
  ".gif", ".webp", ".avif", ".svg", ".ico", ".woff",
  ".woff2", ".ttf", ".otf", ".mp4", ".webm", ".txt",
  ".xml", ".json",
])

const ALLOWED_NOEXT = new Set(["CNAME", "robots.txt"])

const unallowedFiles = allFiles.filter((f) => {
  const name = path.basename(f.path)
  const ext = path.extname(f.path).toLowerCase()
  return !ALLOWED_EXTENSIONS.has(ext) && !ALLOWED_NOEXT.has(name)
})

if (unallowedFiles.length === 0) {
  pass("All dist/ files have allowed extensions")
} else {
  for (const u of unallowedFiles) {
    fail("Unexpected file type in dist/", path.relative(DIST, u.path))
  }
}

// ── Summary ───────────────────────────────────────────────────────────────────

console.log("\n═══════════════════════════════════════════════")
console.log(`  Checks passed: ${passed}`)
console.log(`  Checks failed: ${failed}`)
console.log("═══════════════════════════════════════════════\n")

if (failed === 0) {
  console.log("  RESULT: PASS — safe to deploy\n")
  process.exit(0)
} else {
  console.error("  RESULT: FAIL — resolve issues before deploying\n")
  for (const issue of issues) {
    console.error(`    • ${issue}`)
  }
  console.error("")
  process.exit(1)
}
