import { useState, type FormEvent } from "react";
import {
  AlertTriangle,
  Bell,
  Copy,
  KeyRound,
  ScrollText,
  ShieldCheck,
  Trash2,
  User as UserIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/EmptyState";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError } from "@/lib/api";
import {
  useAudit,
  useDeleteNotificationRule,
  useDeleteUser,
  useIssueToken,
  useMe,
  useNotificationRules,
  useRevokeToken,
  useTestNotification,
  useUpsertNotificationRule,
  useUpsertUser,
  useUsers,
} from "@/lib/hooks";
import type {
  NotificationChannelType,
  NotificationEventType,
  NotificationRule,
  UserRole,
  UserSummary,
} from "@/types";

const ROLES: UserRole[] = ["admin", "operator", "viewer"];
const EVENTS: NotificationEventType[] = ["budget.exceeded", "gate.enqueued"];
const CHANNELS: NotificationChannelType[] = ["webhook", "slack", "email"];

export function SettingsPage() {
  const me = useMe();
  const isAdmin = me.data?.role === "admin";

  return (
    <div className="space-y-5">
      <ProfileCard />

      {isAdmin && (
        <>
          <UsersCard />
          <NotificationsCard />
          <AuditCard />
        </>
      )}

      {!isAdmin && me.data && (
        <Card>
          <CardContent className="py-10">
            <EmptyState
              icon={ShieldCheck}
              title="Admin 권한 필요"
              description="사용자·토큰·감사 로그·알림 관리는 admin 사용자에게만 노출됩니다."
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 내 프로필
// ---------------------------------------------------------------------------

function ProfileCard() {
  const me = useMe();

  return (
    <Card>
      <CardHeader className="border-b border-border pb-4">
        <CardTitle className="flex items-center gap-2 text-sm">
          <UserIcon className="h-4 w-4 text-muted-foreground" />
          My profile
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-5">
        {me.isLoading ? (
          <Skeleton className="h-12 w-1/2" />
        ) : me.isError ? (
          <EmptyState
            icon={AlertTriangle}
            title="Could not load profile"
            description="API 연결을 확인하세요."
          />
        ) : me.data ? (
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="User ID" value={me.data.user_id} mono />
            <Field label="Name" value={me.data.name || "—"} />
            <Field
              label="Role"
              value={<Badge variant="default">{me.data.role}</Badge>}
            />
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Field({
  label,
  value,
  mono,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div>
      <Label>{label}</Label>
      <div className={mono ? "mt-1 font-mono text-xs" : "mt-1 text-sm"}>
        {value}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 사용자 / 토큰
// ---------------------------------------------------------------------------

function UsersCard() {
  const users = useUsers();
  const upsert = useUpsertUser();
  const del = useDeleteUser();

  const [newId, setNewId] = useState("");
  const [newName, setNewName] = useState("");
  const [newRole, setNewRole] = useState<UserRole>("viewer");

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!newId.trim()) return;
    upsert.mutate(
      { user_id: newId.trim(), name: newName.trim(), role: newRole },
      {
        onSuccess: () => {
          toast.success("User saved");
          setNewId("");
          setNewName("");
          setNewRole("viewer");
        },
        onError: (err: unknown) =>
          toast.error(err instanceof ApiError ? err.message : "Save failed"),
      },
    );
  }

  return (
    <Card>
      <CardHeader className="border-b border-border pb-4">
        <CardTitle className="flex items-center gap-2 text-sm">
          <KeyRound className="h-4 w-4 text-muted-foreground" />
          Users & Tokens
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 pt-5">
        {users.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : users.isError ? (
          <EmptyState title="No multi-user mode" description="config/users.yaml이 비어있거나 단일 토큰 모드입니다." />
        ) : (
          (users.data ?? []).map((u) => (
            <UserRow
              key={u.user_id}
              user={u}
              onDelete={() => {
                if (!confirm(`${u.user_id} 삭제?`)) return;
                del.mutate(u.user_id, {
                  onSuccess: () => toast.success("User deleted"),
                });
              }}
            />
          ))
        )}

        <form
          onSubmit={submit}
          className="grid gap-3 border-t border-border pt-4 sm:grid-cols-[1fr_1fr_140px_auto]"
        >
          <div className="space-y-1.5">
            <Label>User ID</Label>
            <Input
              value={newId}
              onChange={(e) => setNewId(e.currentTarget.value)}
              placeholder="alice"
            />
          </div>
          <div className="space-y-1.5">
            <Label>Display name</Label>
            <Input
              value={newName}
              onChange={(e) => setNewName(e.currentTarget.value)}
              placeholder="(optional)"
            />
          </div>
          <div className="space-y-1.5">
            <Label>Role</Label>
            <Select
              value={newRole}
              onChange={(e) => setNewRole(e.currentTarget.value as UserRole)}
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex items-end">
            <Button type="submit" loading={upsert.isPending} disabled={!newId.trim()}>
              Add / Update
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function UserRow({
  user,
  onDelete,
}: {
  user: UserSummary;
  onDelete: () => void;
}) {
  const issue = useIssueToken();
  const revoke = useRevokeToken();
  const [label, setLabel] = useState("");
  const [issued, setIssued] = useState<string | null>(null);

  function onIssue() {
    issue.mutate(
      { user_id: user.user_id, label },
      {
        onSuccess: (r) => {
          setIssued(r.token);
          setLabel("");
          toast.success("Token issued — copy it now");
        },
        onError: () => toast.error("Issue failed"),
      },
    );
  }

  function onRevoke(token_id: string) {
    if (!confirm("Revoke this token?")) return;
    revoke.mutate(
      { user_id: user.user_id, token_id },
      {
        onSuccess: () => toast.success("Revoked"),
      },
    );
  }

  return (
    <div className="rounded-md border border-border p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium">
            {user.user_id}
            {user.name && (
              <span className="ml-2 text-xs text-muted-foreground">
                {user.name}
              </span>
            )}
          </div>
          <div className="mt-0.5">
            <Badge variant="secondary">{user.role}</Badge>
          </div>
        </div>
        <Button
          size="sm"
          variant="ghost"
          onClick={onDelete}
          aria-label="delete user"
        >
          <Trash2 className="h-3.5 w-3.5" />
          Delete
        </Button>
      </div>

      <div className="mt-3 space-y-2">
        {user.tokens.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No tokens — 발급해야 로그인할 수 있습니다.
          </p>
        ) : (
          <ul className="divide-y divide-border text-xs">
            {user.tokens.map((t) => (
              <li
                key={t.id}
                className="flex items-center justify-between gap-2 py-1.5"
              >
                <div className="min-w-0">
                  <span className="font-mono text-muted-foreground">{t.id}</span>
                  {t.label && (
                    <span className="ml-2 text-foreground/80">· {t.label}</span>
                  )}
                  <span className="ml-2 text-muted-foreground">
                    · {new Date(t.created_at).toLocaleString()}
                  </span>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => onRevoke(t.id)}
                  loading={
                    revoke.isPending && revoke.variables?.token_id === t.id
                  }
                >
                  Revoke
                </Button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex items-center gap-2 pt-1">
          <Input
            value={label}
            onChange={(e) => setLabel(e.currentTarget.value)}
            placeholder="label (e.g. ci, laptop)"
            className="h-8 text-xs"
          />
          <Button size="sm" onClick={onIssue} loading={issue.isPending}>
            Issue token
          </Button>
        </div>

        {issued && (
          <div className="rounded-md border border-warning/40 bg-warning/5 p-3 text-xs">
            <div className="mb-1 font-medium text-warning">
              ⚠ 평문 토큰은 이 화면에서 한 번만 보입니다.
            </div>
            <div className="flex items-center gap-2 break-all font-mono">
              {issued}
              <Button
                size="icon"
                variant="ghost"
                onClick={() => {
                  navigator.clipboard.writeText(issued);
                  toast.success("Copied");
                }}
                aria-label="copy"
              >
                <Copy className="h-3.5 w-3.5" />
              </Button>
            </div>
            <button
              className="mt-2 text-[11px] text-muted-foreground underline"
              onClick={() => setIssued(null)}
            >
              dismiss
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Notifications
// ---------------------------------------------------------------------------

function NotificationsCard() {
  const rules = useNotificationRules();
  const upsert = useUpsertNotificationRule();
  const del = useDeleteNotificationRule();
  const test = useTestNotification();

  const [event, setEvent] = useState<NotificationEventType>("budget.exceeded");
  const [channel, setChannel] = useState<NotificationChannelType>("webhook");
  const [target, setTarget] = useState("");
  const [label, setLabel] = useState("");

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!target.trim()) return;
    upsert.mutate(
      {
        id: null,
        event,
        channel,
        target: target.trim(),
        enabled: true,
        label: label.trim(),
      },
      {
        onSuccess: () => {
          toast.success("Rule saved");
          setTarget("");
          setLabel("");
        },
        onError: (err: unknown) =>
          toast.error(err instanceof ApiError ? err.message : "Save failed"),
      },
    );
  }

  return (
    <Card>
      <CardHeader className="border-b border-border pb-4">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Bell className="h-4 w-4 text-muted-foreground" />
          Notification rules
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 pt-5">
        {rules.isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : rules.isError ? (
          <EmptyState title="Cannot load rules" />
        ) : (rules.data ?? []).length === 0 ? (
          <EmptyState
            title="No rules yet"
            description="아래 폼으로 첫 알림 규칙을 추가하세요."
          />
        ) : (
          <ul className="divide-y divide-border">
            {(rules.data ?? []).map((r) => (
              <RuleRow
                key={r.id ?? Math.random()}
                rule={r}
                onToggle={(next) =>
                  upsert.mutate({ ...r, enabled: next, id: r.id })
                }
                onDelete={() => {
                  if (r.id == null) return;
                  if (!confirm("Delete rule?")) return;
                  del.mutate(r.id, {
                    onSuccess: () => toast.success("Deleted"),
                  });
                }}
                onTest={() => {
                  if (r.id == null) return;
                  test.mutate(r.id, {
                    onSuccess: (res) =>
                      toast.success(`Test: ${res.status}`),
                    onError: () => toast.error("Test failed"),
                  });
                }}
                testing={test.isPending && test.variables === r.id}
              />
            ))}
          </ul>
        )}

        <form
          onSubmit={submit}
          className="grid gap-3 border-t border-border pt-4 sm:grid-cols-[1fr_140px_140px_140px_auto]"
        >
          <div className="space-y-1.5">
            <Label>Target</Label>
            <Input
              value={target}
              onChange={(e) => setTarget(e.currentTarget.value)}
              placeholder="https://hooks.slack.com/..."
            />
          </div>
          <div className="space-y-1.5">
            <Label>Event</Label>
            <Select
              value={event}
              onChange={(e) =>
                setEvent(e.currentTarget.value as NotificationEventType)
              }
            >
              {EVENTS.map((e) => (
                <option key={e} value={e}>
                  {e}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Channel</Label>
            <Select
              value={channel}
              onChange={(e) =>
                setChannel(e.currentTarget.value as NotificationChannelType)
              }
            >
              {CHANNELS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Label</Label>
            <Input
              value={label}
              onChange={(e) => setLabel(e.currentTarget.value)}
              placeholder="optional"
            />
          </div>
          <div className="flex items-end">
            <Button type="submit" loading={upsert.isPending}>
              Add
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function RuleRow({
  rule,
  onToggle,
  onDelete,
  onTest,
  testing,
}: {
  rule: NotificationRule;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
  onTest: () => void;
  testing: boolean;
}) {
  return (
    <li className="flex flex-col gap-1.5 py-2.5 text-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Badge variant={rule.enabled ? "default" : "secondary"}>
              {rule.event}
            </Badge>
            <span className="text-xs uppercase text-muted-foreground">
              · {rule.channel}
            </span>
            {rule.label && (
              <span className="text-xs text-muted-foreground">
                · {rule.label}
              </span>
            )}
          </div>
          <div className="mt-1 truncate font-mono text-xs text-muted-foreground">
            {rule.target}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Switch
            checked={rule.enabled}
            onChange={(e) => onToggle(e.currentTarget.checked)}
            aria-label="enabled"
          />
          <Button
            size="sm"
            variant="ghost"
            onClick={onTest}
            loading={testing}
          >
            Test
          </Button>
          <Button size="icon" variant="ghost" onClick={onDelete}>
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Audit log
// ---------------------------------------------------------------------------

function AuditCard() {
  const [q, setQ] = useState("");
  const [action, setAction] = useState("");
  const audit = useAudit({
    q: q.trim() || undefined,
    action: action.trim() || undefined,
    limit: 200,
  });

  return (
    <Card>
      <CardHeader className="border-b border-border pb-4">
        <CardTitle className="flex items-center gap-2 text-sm">
          <ScrollText className="h-4 w-4 text-muted-foreground" />
          Audit log
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 pt-5">
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-0 flex-1 space-y-1.5">
            <Label>Search</Label>
            <Input
              value={q}
              onChange={(e) => setQ(e.currentTarget.value)}
              placeholder="user / target / detail"
              className="h-8 text-xs"
            />
          </div>
          <div className="w-40 space-y-1.5">
            <Label>Action</Label>
            <Input
              value={action}
              onChange={(e) => setAction(e.currentTarget.value)}
              placeholder="e.g. budget.upsert"
              className="h-8 text-xs"
            />
          </div>
        </div>

        {audit.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : audit.isError ? (
          <EmptyState title="Cannot load audit log" />
        ) : (audit.data ?? []).length === 0 ? (
          <EmptyState title="No matching events" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>User</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>Result</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(audit.data ?? []).map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="font-mono text-[11px]">
                    {new Date(e.timestamp).toLocaleString()}
                  </TableCell>
                  <TableCell className="text-xs">
                    {e.user_id ?? "—"}
                    {e.user_role && (
                      <span className="ml-1 text-muted-foreground">
                        · {e.user_role}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{e.action}</TableCell>
                  <TableCell className="font-mono text-xs">
                    {e.target ?? "—"}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        e.result === "success" ? "success" : "destructive"
                      }
                    >
                      {e.result}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
