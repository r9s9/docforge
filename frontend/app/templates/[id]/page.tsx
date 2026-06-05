"use client";

import TemplateDetail from "@/components/TemplateDetail";

export default function Page({ params }: { params: { id: string } }) {
  return <TemplateDetail id={params.id} />;
}
