import { useMemo } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { TimeseriesPoint } from "@/types";

type Field = "cost_usd" | "tokens_in" | "tokens_out" | "events";

interface Props {
  data: TimeseriesPoint[];
  field?: Field;
  height?: number;
  formatValue?: (v: number) => string;
}

const PALETTE = [
  "hsl(251 73% 66%)",
  "hsl(165 100% 36%)",
  "hsl(40 96% 58%)",
  "hsl(12 76% 61%)",
  "hsl(200 90% 60%)",
  "hsl(290 60% 65%)",
  "hsl(150 50% 50%)",
];

interface PivotedRow {
  bucket: string;
  [group: string]: string | number;
}

export function TimeseriesAreaChart({
  data,
  field = "cost_usd",
  height = 280,
  formatValue,
}: Props) {
  const { rows, groups } = useMemo(() => pivot(data, field), [data, field]);
  const fmt = formatValue ?? defaultFormat(field);

  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer>
        <AreaChart
          data={rows}
          margin={{ top: 5, right: 16, bottom: 0, left: 0 }}
        >
          <defs>
            {groups.map((g, i) => (
              <linearGradient
                key={g}
                id={`grad-${i}`}
                x1="0"
                y1="0"
                x2="0"
                y2="1"
              >
                <stop offset="0%" stopColor={PALETTE[i % PALETTE.length]} stopOpacity={0.5} />
                <stop offset="100%" stopColor={PALETTE[i % PALETTE.length]} stopOpacity={0.05} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" />
          <XAxis
            dataKey="bucket"
            stroke="hsl(var(--muted-foreground))"
            fontSize={11}
            tickFormatter={shortDate}
          />
          <YAxis
            stroke="hsl(var(--muted-foreground))"
            fontSize={11}
            tickFormatter={fmt}
            width={64}
          />
          <Tooltip
            contentStyle={{
              background: "hsl(var(--card))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 6,
              fontSize: 12,
            }}
            labelStyle={{ color: "hsl(var(--muted-foreground))" }}
            formatter={(v: number) => fmt(v)}
          />
          {groups.length > 1 && (
            <Legend wrapperStyle={{ fontSize: 11 }} iconType="circle" />
          )}
          {groups.map((g, i) => (
            <Area
              key={g}
              type="monotone"
              dataKey={g}
              stackId="1"
              stroke={PALETTE[i % PALETTE.length]}
              fill={`url(#grad-${i})`}
              strokeWidth={1.5}
              isAnimationActive={false}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function pivot(
  data: TimeseriesPoint[],
  field: Field,
): { rows: PivotedRow[]; groups: string[] } {
  const buckets = new Map<string, PivotedRow>();
  const groups = new Set<string>();
  for (const p of data) {
    const g = p.group ?? field;
    groups.add(g);
    let row = buckets.get(p.bucket);
    if (!row) {
      row = { bucket: p.bucket };
      buckets.set(p.bucket, row);
    }
    row[g] = (Number(row[g] ?? 0) + (p[field] as number)) as number;
  }
  return {
    rows: Array.from(buckets.values()).sort((a, b) =>
      a.bucket.localeCompare(b.bucket),
    ),
    groups: Array.from(groups).sort(),
  };
}

function shortDate(b: string): string {
  // YYYY-MM-DD or YYYY-MM-DDTHH:00:00 → MMM-DD or HH:00
  if (b.length === 10) return b.slice(5);
  if (b.length >= 13) return b.slice(11, 13) + "h";
  return b;
}

function defaultFormat(field: Field): (v: number) => string {
  if (field === "cost_usd") return (v) => `$${v.toFixed(2)}`;
  if (field === "events") return (v) => `${Math.round(v)}`;
  return (v) => `${(v / 1000).toFixed(1)}k`;
}
