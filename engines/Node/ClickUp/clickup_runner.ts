import { homedir } from "node:os";
import { join } from "node:path";

const [action, ...raw] = Bun.argv.slice(2);
const cup = Bun.which("cup") ?? join(homedir(), ".bun", "bin", "cup");

const commands: Record<string, (args: string[]) => string[]> = {
  auth: () => ["auth", "--json"],
  summary: () => ["summary", "--json"],
  assigned: () => ["assigned", "--json"],
  overdue: () => ["overdue", "--json"],
  sprint: () => ["sprint", "--json"],
  spaces: () => ["spaces", "--json"],
  members: () => ["members", "--json"],
  search: ([query]) => ["search", required(query, "query"), "--json"],
  task: ([taskId]) => ["task", required(taskId, "task_id"), "--json"],
  activity: ([taskId]) => ["activity", required(taskId, "task_id"), "--json"],
  comments: ([taskId]) => ["comments", required(taskId, "task_id"), "--json"],
  subtasks: ([taskId]) => ["subtasks", required(taskId, "task_id"), "--json"],
  tasks_by_status: ([status]) => ["tasks", "--status", required(status, "status"), "--json"],
  tasks_in_list: ([listId]) => ["tasks", "--list", required(listId, "list_id"), "--all", "--json"],
  create_task: ([listId, name, description]) => ["create", "--list", required(listId, "list_id"), "--name", required(name, "name"), "--description", required(description, "description"), "--json"],
  create_subtask: ([parentId, name, description]) => ["create", "--parent", required(parentId, "parent_id"), "--name", required(name, "name"), "--description", required(description, "description"), "--json"],
  update_status: ([taskId, status]) => ["update", required(taskId, "task_id"), "--status", required(status, "status"), "--json"],
  update_priority: ([taskId, priority]) => ["update", required(taskId, "task_id"), "--priority", required(priority, "priority"), "--json"],
  comment: ([taskId, message]) => ["comment", required(taskId, "task_id"), "--message", required(message, "message"), "--json"],
  assign: ([taskId, assignee]) => ["assign", required(taskId, "task_id"), "--to", required(assignee, "assignee"), "--json"],
  delete_task: ([taskId]) => ["delete", required(taskId, "task_id"), "--confirm", "--json"],
};

if (!action || !commands[action]) fail(`Unknown action: ${action || "(missing)"}`);

const command = commands[action]!(raw);
const proc = Bun.spawn([cup, ...command], { stdout: "pipe", stderr: "pipe", env: process.env });
const [stdout, stderr, exitCode] = await Promise.all([new Response(proc.stdout).text(), new Response(proc.stderr).text(), proc.exited]);
if (exitCode !== 0) fail(stderr.trim() || stdout.trim() || `cup exited ${exitCode}`, exitCode);
if (stderr.trim()) console.error(stderr.trim());
console.log(stdout.trim() || JSON.stringify({ ok: true }));

function required(value: string | undefined, name: string): string {
  if (!value?.trim()) fail(`${name} is required`);
  return value;
}
function fail(message: string, code = 1): never {
  console.error(JSON.stringify({ ok: false, error: message }));
  process.exit(code);
}
