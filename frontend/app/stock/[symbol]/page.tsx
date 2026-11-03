import { Suspense } from "react";
import StockView from "@/components/StockView";

export default function Page({ params }: PageProps<"/stock/[symbol]">) {
  return (
    <Suspense fallback={<div className="skeleton section" style={{ height: 320, marginTop: 24 }} />}>
      <StockView params={params} />
    </Suspense>
  );
}
