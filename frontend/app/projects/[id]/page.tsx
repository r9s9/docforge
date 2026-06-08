"use client";

import ProjectDetail from "@/components/ProjectDetail";

export default function Page({ params }: { params: { id: string } }) {
  return <ProjectDetail id={params.id} />;
}
