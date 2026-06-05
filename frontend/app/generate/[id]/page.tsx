"use client";

import GeneratePage from "@/components/GeneratePage";

export default function Page({ params }: { params: { id: string } }) {
  return <GeneratePage initialId={params.id} />;
}
