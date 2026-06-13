import { PersonStanding } from "lucide-react";

export function HumanoidRobot() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 text-center">
      <PersonStanding className="h-12 w-12 text-muted-foreground/40" />
      <h1 className="text-2xl font-bold">人形机器人</h1>
      <p className="text-sm text-muted-foreground">页面建设中，敬请期待。</p>
    </div>
  );
}
