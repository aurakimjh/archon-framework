import { Construction } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface PlaceholderProps {
  title: string;
  slice: string;
}

export function PlaceholderPage({ title, slice }: PlaceholderProps) {
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center justify-center gap-3 py-16 text-center">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-secondary text-muted-foreground">
          <Construction className="h-5 w-5" aria-hidden />
        </div>
        <div>
          <div className="text-base font-semibold">{title}</div>
          <p className="mt-1 text-sm text-muted-foreground">
            이 페이지는 다음 슬라이스에서 도착합니다.
          </p>
        </div>
        <Badge variant="outline">{slice}</Badge>
      </CardContent>
    </Card>
  );
}
