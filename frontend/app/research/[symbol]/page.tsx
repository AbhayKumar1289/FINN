import { Suspense } from "react";
import ResearchView from "@/components/ResearchView";

export default function Page({ params }: PageProps<"/research/[symbol]">) {
  return (
    <Suspense fallback={<div className="skeleton section" style={{ height: 240, marginTop: 24 }} />}>
      <ResearchView params={params} />
    </Suspense>
  );
}
