#!/usr/bin/env node
/**
 * WorkspaceScout Engine
 *
 * Local-first workspace introspection for Switchbay.
 * Outputs JSON for agent consumption.
 *
 * Tools:
 *   status       — confirm the engine is ready
 *   snapshot     — file tree + git status + stack detection summary
 *   deps_check   — parse package.json, flag missing/outdated hints
 *   git_status   — current branch, dirty files, recent commits
 *   stack_detect — identify the JS/TS/Bun/Node stack in a workspace
 */

import { execSync } from "child_process";
import { existsSync, readdirSync, readFileSync, statSync } from "fs";
import { join, resolve, relative } from "path";
import { parseArgs } from "util";

// ---------------------------------------------------------------------------
// Output helpers
// ---------------------------------------------------------------------------

function out(ok, action, data = {}) {
  console.log(JSON.stringify({ ok, action, ...data }));
  process.exit(ok ? 0 : 1);
}

function fail(action, message, data = {}) {
  out(false, action, { error: message, ...data });
}

// ---------------------------------------------------------------------------
// Shell helper — never throws; returns { stdout, stderr, code }
// ---------------------------------------------------------------------------

function sh(cmd, cwd = process.cwd()) {
  try {
    const stdout = execSync(cmd, {
      cwd,
      encoding: "utf8",
      stdio: ["pipe", "pipe", "pipe"],
      timeout: 10_000,
    });
    return { stdout: stdout.trim(), stderr: "", code: 0 };
  } catch (err) {
    return {
      stdout: (err.stdout || "").trim(),
      stderr: (err.stderr || "").trim(),
      code: err.status ?? 1,
    };
  }
}

// ---------------------------------------------------------------------------
// Guards
// ---------------------------------------------------------------------------

function resolveWorkspace(raw) {
  return raw ? resolve(raw) : process.cwd();
}

function assertDir(path, action) {
  if (!existsSync(path) || !statSync(path).isDirectory()) {
    fail(action, `Not a directory: ${path}`);
    process.exit(1);
  }
}

// ---------------------------------------------------------------------------
// Tool: status
// ---------------------------------------------------------------------------

function cmdStatus() {
  const nodeVersion = process.version;
  const platform = process.platform;
  const cwd = process.cwd();
  out(true, "status", {
    message: "WorkspaceScout engine ready",
    node_version: nodeVersion,
    platform,
    cwd,
  });
}

// ---------------------------------------------------------------------------
// Tool: git_status
// ---------------------------------------------------------------------------

function cmdGitStatus(args) {
  const ws = resolveWorkspace(args.workspace);
  assertDir(ws, "git-status");

  const branch = sh("git rev-parse --abbrev-ref HEAD", ws);
  const dirty = sh("git status --porcelain", ws);
  const log = sh("git log --oneline -5", ws);
  const remote = sh("git remote -v", ws);

  if (branch.code !== 0) {
    out(true, "git-status", { workspace: ws, git: false, message: "Not a git repo" });
    return;
  }

  const dirtyFiles = dirty.stdout
    ? dirty.stdout.split("\n").map((l) => l.trim()).filter(Boolean)
    : [];

  const recentCommits = log.stdout
    ? log.stdout.split("\n").map((l) => l.trim()).filter(Boolean)
    : [];

  out(true, "git-status", {
    workspace: ws,
    git: true,
    branch: branch.stdout,
    dirty: dirtyFiles.length > 0,
    dirty_files: dirtyFiles,
    recent_commits: recentCommits,
    remotes: remote.stdout || null,
  });
}

// ---------------------------------------------------------------------------
// Tool: stack_detect
// ---------------------------------------------------------------------------

function cmdStackDetect(args) {
  const ws = resolveWorkspace(args.workspace);
  assertDir(ws, "stack-detect");

  const markers = {
    bun: ["bun.lockb", "bunfig.toml"],
    typescript: ["tsconfig.json", "tsconfig.base.json"],
    vite: ["vite.config.ts", "vite.config.js"],
    next: ["next.config.js", "next.config.ts", "next.config.mjs"],
    react: [], // detected via package.json below
    node: ["package.json"],
    python: ["pyproject.toml", "requirements.txt", "setup.py", "Pipfile"],
    ruby: ["Gemfile", ".ruby-version"],
    go: ["go.mod"],
    rust: ["Cargo.toml"],
  };

  const detected = [];

  for (const [stack, files] of Object.entries(markers)) {
    if (files.length === 0) continue;
    if (files.some((f) => existsSync(join(ws, f)))) {
      detected.push(stack);
    }
  }

  // React: check package.json dependencies
  const pkgPath = join(ws, "package.json");
  if (existsSync(pkgPath)) {
    try {
      const pkg = JSON.parse(readFileSync(pkgPath, "utf8"));
      const allDeps = {
        ...(pkg.dependencies || {}),
        ...(pkg.devDependencies || {}),
      };
      if ("react" in allDeps) detected.push("react");
      if ("vue" in allDeps) detected.push("vue");
      if ("svelte" in allDeps) detected.push("svelte");
      if ("@angular/core" in allDeps) detected.push("angular");
      if ("electron" in allDeps) detected.push("electron");
    } catch {
      // malformed package.json — skip
    }
  }

  // Runtime preference
  const bunAvailable = sh("which bun", ws).code === 0;
  const nodeAvailable = sh("which node", ws).code === 0;

  const runtime = detected.includes("bun") && bunAvailable
    ? "bun"
    : nodeAvailable
    ? "node"
    : "unknown";

  out(true, "stack-detect", {
    workspace: ws,
    detected_stacks: [...new Set(detected)],
    preferred_runtime: runtime,
    bun_available: bunAvailable,
    node_available: nodeAvailable,
  });
}

// ---------------------------------------------------------------------------
// Tool: deps_check
// ---------------------------------------------------------------------------

function cmdDepsCheck(args) {
  const ws = resolveWorkspace(args.workspace);
  assertDir(ws, "deps-check");

  const pkgPath = join(ws, "package.json");
  if (!existsSync(pkgPath)) {
    out(true, "deps-check", {
      workspace: ws,
      has_package_json: false,
      message: "No package.json found in workspace root",
    });
    return;
  }

  let pkg;
  try {
    pkg = JSON.parse(readFileSync(pkgPath, "utf8"));
  } catch (err) {
    fail("deps-check", `Malformed package.json: ${err.message}`);
    return;
  }

  const deps = pkg.dependencies || {};
  const devDeps = pkg.devDependencies || {};
  const peerDeps = pkg.peerDependencies || {};
  const scripts = pkg.scripts || {};

  // Check for lockfile
  const lockfiles = ["bun.lockb", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"];
  const foundLockfile = lockfiles.find((lf) => existsSync(join(ws, lf))) || null;

  // Check node_modules
  const hasNodeModules = existsSync(join(ws, "node_modules"));

  // Outdated (best-effort — runs npm/bun outdated, may be slow)
  let outdated = null;
  if (hasNodeModules) {
    const bunCheck = sh("bun outdated --json 2>/dev/null || echo null", ws);
    const npmCheck = sh("npm outdated --json 2>/dev/null || echo null", ws);
    try {
      outdated = JSON.parse(bunCheck.stdout !== "null" ? bunCheck.stdout : npmCheck.stdout);
    } catch {
      outdated = null;
    }
  }

  out(true, "deps-check", {
    workspace: ws,
    has_package_json: true,
    name: pkg.name || null,
    version: pkg.version || null,
    scripts: Object.keys(scripts),
    dep_count: Object.keys(deps).length,
    dev_dep_count: Object.keys(devDeps).length,
    peer_dep_count: Object.keys(peerDeps).length,
    dependencies: deps,
    dev_dependencies: devDeps,
    lockfile: foundLockfile,
    node_modules_present: hasNodeModules,
    outdated: outdated,
  });
}

// ---------------------------------------------------------------------------
// Tool: snapshot
// ---------------------------------------------------------------------------

function buildTree(dir, depth = 0, maxDepth = 3, ignores = new Set()) {
  if (depth > maxDepth) return [];
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return [];
  }

  const ignored = new Set([
    "node_modules", ".git", ".next", ".nuxt", "dist", "build",
    ".turbo", ".cache", "coverage", "__pycache__", ".venv",
    ...ignores,
  ]);

  const results = [];
  for (const entry of entries) {
    if (ignored.has(entry.name)) continue;
    const fullPath = join(dir, entry.name);
    const isDir = entry.isDirectory();
    results.push({
      name: entry.name,
      path: fullPath,
      is_dir: isDir,
      depth,
    });
    if (isDir && depth < maxDepth) {
      results.push(...buildTree(fullPath, depth + 1, maxDepth, ignores));
    }
  }
  return results;
}

function cmdSnapshot(args) {
  const ws = resolveWorkspace(args.workspace);
  assertDir(ws, "snapshot");

  const maxDepth = args.depth != null ? parseInt(args.depth, 10) : 3;

  // File tree
  const tree = buildTree(ws, 0, maxDepth);
  const treeRelative = tree.map((e) => ({
    ...e,
    path: relative(ws, e.path),
  }));

  // Git
  const branch = sh("git rev-parse --abbrev-ref HEAD", ws);
  const dirty = sh("git status --porcelain", ws);
  const log = sh("git log --oneline -5", ws);

  const git = branch.code === 0
    ? {
        git: true,
        branch: branch.stdout,
        dirty_files: dirty.stdout
          ? dirty.stdout.split("\n").map((l) => l.trim()).filter(Boolean)
          : [],
        recent_commits: log.stdout
          ? log.stdout.split("\n").map((l) => l.trim()).filter(Boolean)
          : [],
      }
    : { git: false };

  // Stack
  const stackMarkers = {
    bun: ["bun.lockb", "bunfig.toml"],
    typescript: ["tsconfig.json"],
    vite: ["vite.config.ts", "vite.config.js"],
    next: ["next.config.js", "next.config.ts", "next.config.mjs"],
    python: ["pyproject.toml", "requirements.txt", "setup.py"],
    ruby: ["Gemfile"],
    go: ["go.mod"],
    rust: ["Cargo.toml"],
  };

  const detectedStacks = [];
  for (const [stack, files] of Object.entries(stackMarkers)) {
    if (files.some((f) => existsSync(join(ws, f)))) {
      detectedStacks.push(stack);
    }
  }
  if (existsSync(join(ws, "package.json"))) {
    detectedStacks.push("node");
    try {
      const pkg = JSON.parse(readFileSync(join(ws, "package.json"), "utf8"));
      const allDeps = { ...(pkg.dependencies || {}), ...(pkg.devDependencies || {}) };
      for (const fw of ["react", "vue", "svelte"]) {
        if (fw in allDeps) detectedStacks.push(fw);
      }
    } catch {
      // skip
    }
  }

  // Package summary
  let pkgSummary = null;
  const pkgPath = join(ws, "package.json");
  if (existsSync(pkgPath)) {
    try {
      const pkg = JSON.parse(readFileSync(pkgPath, "utf8"));
      pkgSummary = {
        name: pkg.name,
        version: pkg.version,
        scripts: Object.keys(pkg.scripts || {}),
        dep_count: Object.keys(pkg.dependencies || {}).length,
        dev_dep_count: Object.keys(pkg.devDependencies || {}).length,
      };
    } catch {
      // skip
    }
  }

  out(true, "snapshot", {
    workspace: ws,
    file_tree: treeRelative,
    file_count: treeRelative.filter((e) => !e.is_dir).length,
    dir_count: treeRelative.filter((e) => e.is_dir).length,
    git,
    detected_stacks: [...new Set(detectedStacks)],
    package_json: pkgSummary,
    scanned_at: new Date().toISOString(),
  });
}

// ---------------------------------------------------------------------------
// CLI routing
// ---------------------------------------------------------------------------

const TOOLS = {
  status: cmdStatus,
  snapshot: cmdSnapshot,
  "git-status": cmdGitStatus,
  "stack-detect": cmdStackDetect,
  "deps-check": cmdDepsCheck,
};

function main() {
  const argv = process.argv.slice(2);
  const tool = argv[0];

  if (!tool || !TOOLS[tool]) {
    fail("init", `Unknown tool: ${tool || "(none)"}. Available: ${Object.keys(TOOLS).join(", ")}`);
    return;
  }

  // Parse remaining flags as --key value pairs
  const rawArgs = argv.slice(1);
  const parsedArgs = {};
  for (let i = 0; i < rawArgs.length; i++) {
    if (rawArgs[i].startsWith("--")) {
      const key = rawArgs[i].slice(2);
      const val = rawArgs[i + 1] && !rawArgs[i + 1].startsWith("--") ? rawArgs[++i] : true;
      parsedArgs[key] = val;
    }
  }

  TOOLS[tool](parsedArgs);
}

main();
