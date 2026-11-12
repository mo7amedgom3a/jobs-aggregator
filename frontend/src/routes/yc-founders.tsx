import { createFileRoute } from "@tanstack/react-router";
import { YCFoundersPage } from "@/features/yc/YCFoundersPage";

export const Route = createFileRoute("/yc-founders")({
  head: () => ({
    meta: [
      { title: "YC Founders — sourcing & outreach" },
      {
        name: "description",
        content:
          "Collect YC companies and founders with X, LinkedIn and email contacts, then draft and review outreach for open roles.",
      },
    ],
  }),
  component: YCFoundersPage,
});
